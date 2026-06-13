# Tasks

## Done

### Stemming CLI: expose opt-in stemming through the JSONL CLIs

Query/index CLI surface for the merged `StemmingTokenizer`
(`src/stemming_tokenizer.*`, in `main` via PR #2), per `docs/stemming.md`.

- [x] `cottontail-jsonl-index --stem <name>`: build with the `stemming`
      tokenizer (wrapping `ascii`/`noxml` + the named stemmer) instead of plain
      `ascii`; report `"stemmer"` in the build summary.
- [x] `cottontail-jsonl-query --stem`: stem query terms into `porter:` GCL atoms
      and rank via `ssr` (cover density). Works for `--text` and `--gcl`;
      unstemmable terms fall back to their exact surface atom.
- [x] Detect a stemmed stream by the burrow's dna tokenizer name (`stemming`);
      `--stem` against a non-stem burrow exits 2 (no silent fallback).
- [x] Search output: add `"stemmed": true|false`. `--explain`: per-leaf
      `"stream"` (`exact`|`stemmed`) and df from that stream.
- [x] Tests: stemmed recall, exact preserved, no-op fallback, missing-stream
      error, over-stem pinned, explain stream labeling (`JsonlStem.*` in
      `test/jsonl.cc`; `--stem` build+query and exit-2 in `test/jsonl_cli.cc`).
- [x] `bazel test //test:tests //test:hazel_test //test:jsonl_test` green.

Mechanism note: the engine only stems inside `icover` (not `ssr`/`--gcl`), so we
stem in `jsonl_core` and target the stemmed stream via GCL atoms — no core change,
no use of `Warren::set_stemmer()` (which persists to dna).
