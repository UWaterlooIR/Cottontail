#!/usr/bin/env bash
#
# Build the FULL ClimbMix collection as N sub-burrows for TASK-34 (MultiShardSearchEngine):
# split ALL corpus shards across PARTS (default 8) and build each sub-burrow concurrently via
# the cottontail-index front door (each gets its own docno-cp.sqlite). Sharding the index this
# way turns the ~days-long single-burrow build into a parallel one. Serve the parts with
# scripts/launch-shard-servers.sh (one server per part) behind a MultiShardSearchEngine.
#
# Indexes as usual: utf8 tokenizer + porter stemmed stream. Uses a LARGER builder buffer than
# the tool default (2x by default) to spill less -- there is RAM headroom on the build host.
#
# Env overrides: CORP, IDXPARENT, STAGE, PARTS, TOKENIZER, STEM, BUFFER, FORCE (=1 to overwrite).
#
set -euo pipefail
cd "$(dirname "$0")/.."

CORP=${CORP:-/share/corpora/climbmix-400b-corpus-jsonl}
IDXPARENT=${IDXPARENT:-/share/indexes/climbmix_full_shards}
STAGE=${STAGE:-/share/indexes/climbmix-full-staging}
PARTS=${PARTS:-8}
TOKENIZER=${TOKENIZER:-utf8}
STEM=${STEM:-porter}
# Builder buffer in RECORDS. Tool default is 268435456 (256Mi); use 2x to spill less.
BUFFER=${BUFFER:-536870912}
FORCE=${FORCE:-0}
LOGDIR="$IDXPARENT/logs"
INDEX_BIN="bazel-bin/apps/cottontail-jsonl-index"

if compgen -G "$IDXPARENT/part*.burrow" >/dev/null 2>&1 && [ "$FORCE" != 1 ]; then
  echo "ABORT: $IDXPARENT already has part burrows. Set FORCE=1 to overwrite." >&2
  exit 1
fi
mkdir -p "$IDXPARENT" "$LOGDIR" "$STAGE"

echo ">> building optimized binaries (-c opt)" >&2
bazel build -c opt //apps:cottontail-jsonl-index //apps:cottontail-jsonl-query >&2
# Warm the uv env once so the concurrent index runs below don't race on a first sync.
uv run --directory isj python -c "pass" >&2

# ALL corpus shards
mapfile -t SHARDS < <(ls "$CORP"/*.jsonl.gz | sort)
TOTAL=${#SHARDS[@]}
echo ">> $TOTAL shards over $PARTS parts (tokenizer=$TOKENIZER stem=$STEM buffer=$BUFFER) -> $IDXPARENT" >&2
[ "$TOTAL" -gt 0 ] || { echo "ABORT: no shards matched under $CORP" >&2; exit 1; }

# Distribute TOTAL across PARTS via staging dirs of symlinks (cottontail-index reads a dir).
base=$(( TOTAL / PARTS )); rem=$(( TOTAL - base*PARTS )); idx=0
declare -a BURROWS PIDS
for p in $(seq 0 $((PARTS-1))); do
  part=$(printf "part%02d" "$p")
  d="$STAGE/$part"; rm -rf "$d"; mkdir -p "$d"
  burrow="$IDXPARENT/$part.burrow"; rm -rf "$burrow"
  n=$base; [ "$p" -lt "$rem" ] && n=$((base+1))
  first=$idx; last=$((idx+n-1))
  for i in $(seq "$first" "$last"); do ln -s "${SHARDS[$i]}" "$d/"; done
  idx=$((last+1))
  echo "$part: $n shards [$(basename "${SHARDS[$first]}") .. $(basename "${SHARDS[$last]}")] -> $burrow" >&2
  BURROWS[$p]="$burrow"
done
[ "$idx" = "$TOTAL" ] || { echo "ABORT: assignment mismatch ($idx != $TOTAL)" >&2; exit 1; }

# Build the PARTS burrows CONCURRENTLY (each: burrow + docno-cp.sqlite via index.py).
echo ">> START $(date '+%F %T') -- building $PARTS burrows concurrently" >&2
for p in $(seq 0 $((PARTS-1))); do
  part=$(printf "part%02d" "$p")
  uv run --directory isj python -m isj_agent.index \
    --input "$STAGE/$part" --burrow "${BURROWS[$p]}" \
    --index-bin "$INDEX_BIN" \
    --tokenizer "$TOKENIZER" --stem "$STEM" --buffer "$BUFFER" --overwrite --verbose \
    > "$LOGDIR/$part.log" 2>&1 &
  PIDS[$p]=$!
  echo "launched $part pid=${PIDS[$p]} (log: $LOGDIR/$part.log)" >&2
done
rc=0
for p in $(seq 0 $((PARTS-1))); do wait "${PIDS[$p]}" || rc=1; done
[ "$rc" = 0 ] || { echo "ABORT: a part build failed -- see $LOGDIR/*.log" >&2; exit 1; }

echo ">> ALL $PARTS BURROWS COMPLETE $(date '+%F %T')" >&2
ls -d "$IDXPARENT"/part*.burrow >&2
echo ">> next: scripts/launch-full-shard-servers.sh   (one server per part, ports 7000+)" >&2
