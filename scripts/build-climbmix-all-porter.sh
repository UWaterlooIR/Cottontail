#!/usr/bin/env bash
#
# Rebuild the FULL ClimbMix (400B) index in the current format via the
# cottontail-index front door (isj_agent.index):
#   - a cp-native burrow: utf8 tokens + a co-located Porter-stemmed stream, and
#   - the docno-cp.sqlite map (cp<->docno), which the query/server stack needs.
#
# The old /share/indexes/climbmix400b-burrows/climbmix-all-utf8-porter.burrow is
# the pre-front-door format (no docno-cp.sqlite); this rebuilds it correctly.
#
# Reproducible: rerun to rebuild (--overwrite). Output is OUTSIDE the repo by
# design (a ~1.5 TB burrow); the corpus and index paths live under /share.
#
set -euo pipefail
cd "$(dirname "$0")/.."

INPUT=/share/corpora/climbmix-400b-corpus-jsonl
BURROW=/share/indexes/climbmix-all-porter.burrow

echo ">> building optimized binaries (so bazel-bin points at -c opt)" >&2
bazel build -c opt //apps:cottontail-jsonl-index //apps:cottontail-jsonl-query >&2

echo ">> building index -> $BURROW" >&2
# index.py: runs cottontail-jsonl-index (burrow + docno-cp.tsv dump), then loads
# the dump into docno-cp.sqlite and removes the dump on success.
uv run --directory isj python -m isj_agent.index \
  --input  "$INPUT" \
  --burrow "$BURROW" \
  --tokenizer utf8 --stem porter --overwrite --verbose

echo ">> done: $BURROW" >&2
