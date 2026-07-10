#!/usr/bin/env bash
#
# Launch one cottontail-jsonl-server per sub-burrow (TASK-34): one server per part on
# ports BASE_PORT+i. This is the N-single-burrow-servers arrangement a
# MultiShardSearchEngine fans out over. Works for any part set (test or full) via IDXPARENT.
# Servers are detached (setsid) so they survive the shell; logs under <IDXPARENT>/logs.
#
# Env overrides:
#   IDXPARENT     parent dir holding part*.burrow (default the test set)
#   BASE_PORT     first port (default 7000; part00 -> BASE_PORT, part01 -> BASE_PORT+1, ...)
#   THREADS       --threads: concurrent request handlers per server (default 8)
#   RANK_THREADS  --rank-threads: threads INSIDE one ranking pass per server (default 4).
#                 With N shard servers on one box, set this deliberately: the per-server
#                 auto-budget does NOT know about sibling shard servers, so the real ceiling
#                 is N x THREADS x RANK_THREADS. 4 is a modest per-shard default.
#
# Stop them with:  scripts/launch-full-shard-servers.sh stop
#
set -euo pipefail
cd "$(dirname "$0")/.."

IDXPARENT=${IDXPARENT:-/share/indexes/climbmix_full_shards}
BASE_PORT=${BASE_PORT:-7000}
THREADS=${THREADS:-8}
RANK_THREADS=${RANK_THREADS:-4}
SERVER_BIN="bazel-bin/apps/cottontail-jsonl-server"
LOGDIR="$IDXPARENT/logs"

if [ "${1:-}" = stop ]; then
  echo ">> stopping servers over $IDXPARENT" >&2
  pkill -f "cottontail-jsonl-server --burrow $IDXPARENT/" && echo "stopped." >&2 || echo "(none running)" >&2
  exit 0
fi

mkdir -p "$LOGDIR"
echo ">> building the server binary (-c opt)" >&2
bazel build -c opt //apps:cottontail-jsonl-server >&2

mapfile -t BURROWS < <(ls -d "$IDXPARENT"/part*.burrow 2>/dev/null | sort)
[ "${#BURROWS[@]}" -gt 0 ] || {
  echo "ABORT: no part burrows under $IDXPARENT -- build them first (build-test-shards.sh / build-full-shards.sh)" >&2
  exit 1
}

echo ">> launching ${#BURROWS[@]} servers from port $BASE_PORT (threads=$THREADS rank-threads=$RANK_THREADS)" >&2
i=0
for burrow in "${BURROWS[@]}"; do
  port=$((BASE_PORT + i))
  log="$LOGDIR/server-$port.log"
  setsid "$SERVER_BIN" --burrow "$burrow" --host 127.0.0.1 --port "$port" \
    --threads "$THREADS" --rank-threads "$RANK_THREADS" --no-auth > "$log" 2>&1 < /dev/null &
  echo "  port $port <- $(basename "$burrow")  (pid $!, log $log)" >&2
  i=$((i + 1))
done

sleep 3
echo ">> health checks:" >&2
i=0
for burrow in "${BURROWS[@]}"; do
  port=$((BASE_PORT + i))
  printf "  %s: " "$port" >&2
  curl -s --max-time 5 "http://127.0.0.1:$port/healthz" >&2 || printf "(not up yet)" >&2
  echo >&2
  i=$((i + 1))
done
urls=""
for ((j = 0; j < ${#BURROWS[@]}; j++)); do
  urls+="${urls:+, }http://127.0.0.1:$((BASE_PORT + j))"
done
echo ">> shard base_urls: $urls" >&2
echo ">> stop with: scripts/launch-full-shard-servers.sh stop  (IDXPARENT=$IDXPARENT)" >&2
