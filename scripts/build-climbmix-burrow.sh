#!/usr/bin/env bash
#
# Build a Cottontail burrow over the ClimbMix JSONL shards, using the Unicode
# (utf8) tokenizer with a co-located Porter-stemmed stream. Reproducible: run it
# again to rebuild (it overwrites).
#
# Override any default via an environment variable, e.g.:
#   LIMIT=5000 ./scripts/build-climbmix-burrow.sh        # quick smoke build
#   BURROW=/tmp/my.burrow INPUT=/data/shards ./scripts/build-climbmix-burrow.sh
#
# Defaults:
#   INPUT   corpus dir to recurse for *.jsonl / *.jsonl.gz
#   BURROW  output burrow path (gitignored under Scrapheap/)
#   LIMIT   cap total rows (unset = whole corpus)
#   BUFFER  builder token/annotation buffer in records (unset = tool default 256Mi;
#           raise on big-RAM hosts to spill less)
set -euo pipefail

# Run from the repo root regardless of where this is invoked.
cd "$(dirname "$0")/.."

INPUT="${INPUT:-/share/corpora/climbmix-400b-corpus-jsonl}"
BURROW="${BURROW:-Scrapheap/climbmix-utf8-porter.burrow}"
TOKENIZER="${TOKENIZER:-utf8}"
STEM="${STEM:-porter}"

if [[ ! -d "$INPUT" ]]; then
  echo "error: input corpus dir not found: $INPUT" >&2
  echo "       set INPUT=/path/to/jsonl/shards and re-run." >&2
  exit 1
fi

# Build both binaries in the same (-c opt) config so the bazel-bin symlink points
# at a tree that has the query tool too (the agent's default --query-bin).
echo ">> building optimized index + query binaries" >&2
bazel build -c opt //apps:cottontail-jsonl-index //apps:cottontail-jsonl-query >&2
INDEX_BIN="bazel-bin/apps/cottontail-jsonl-index"

# Assemble the command. utf8 + porter is the point of this script; --overwrite
# makes reruns idempotent; --verbose streams per-file progress to stderr.
cmd=("$INDEX_BIN"
     --input "$INPUT"
     --burrow "$BURROW"
     --tokenizer "$TOKENIZER"
     --stem "$STEM"
     --overwrite
     --verbose)
[[ -n "${LIMIT:-}" ]] && cmd+=(--limit "$LIMIT")
[[ -n "${BUFFER:-}" ]] && cmd+=(--buffer "$BUFFER")

echo ">> ${cmd[*]}" >&2
# Index summary (JSON) goes to stdout; progress/warnings to stderr.
"${cmd[@]}"

echo ">> done: $BURROW" >&2
echo ">> query it, e.g.:" >&2
echo "   bazel-bin/apps/cottontail-jsonl-query --burrow $BURROW --text \"<words>\"" >&2
