#!/usr/bin/env bash
#
# Launch one cottontail-jsonl-server per TEST sub-burrow (TASK-34 live setup): ports 7000+.
# This is the N-single-burrow-servers arrangement a MultiShardSearchEngine fans out over.
# Servers are detached (setsid) so they survive the shell; logs under <IDXPARENT>/logs.
#
# Env overrides: IDXPARENT, BASE_PORT (default 7000), THREADS.
#   Stop them with:  scripts/launch-test-shard-servers.sh stop
#
set -euo pipefail
cd "$(dirname "$0")/.."

IDXPARENT=${IDXPARENT:-/share/indexes/climbmix_test_shards}
BASE_PORT=${BASE_PORT:-7000}
THREADS=${THREADS:-8}
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
  echo "ABORT: no part burrows under $IDXPARENT -- run scripts/build-test-shards.sh first" >&2
  exit 1
}

echo ">> launching ${#BURROWS[@]} servers from port $BASE_PORT" >&2
i=0
for burrow in "${BURROWS[@]}"; do
  port=$((BASE_PORT + i))
  log="$LOGDIR/server-$port.log"
  setsid "$SERVER_BIN" --burrow "$burrow" --host 127.0.0.1 --port "$port" \
    --threads "$THREADS" --no-auth > "$log" 2>&1 < /dev/null &
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
echo ">> stop with: scripts/launch-test-shard-servers.sh stop" >&2
