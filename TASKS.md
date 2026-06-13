# Tasks

## Done

### Tokenizer choice: `--tokenizer ascii|utf8` for the index CLI

The indexer can build either an ASCII or a Unicode-aware (`utf8`) index. The query
tool needs no flag — it reconstructs the tokenizer (and any `stemming` wrapper)
from the burrow's dna, so query-time tokenization always matches the index.

- [x] `--tokenizer <ascii|utf8>` on `cottontail-jsonl-index`
      (`IndexOptions.tokenizer`), **default `utf8`**.
- [x] `jsonl_index` builds the inner tokenizer from the choice; an unknown value
      is a reported error.
- [x] `--stem` wraps the **selected** inner tokenizer (all four combos: ascii,
      utf8, ascii+stem, utf8+stem).
- [x] Build summary reports `"tokenizer"`.
- [x] Query tool: no new flag; verified over `utf8` and `stemming(utf8,…)`
      burrows (`JsonlTokenizer.*`).
- [x] Docs: `cli-spec` §3.2/§3.4 updated (and stale "no --stemmer" note fixed);
      `stemming.md §6` non-ASCII caveat relaxed.
- [x] Tests: accented-word whole-token (utf8) vs split (ascii); default-is-utf8;
      utf8+stem recall; unknown-tokenizer error (`JsonlTokenizer.*` in
      `test/jsonl.cc`).
- [x] `bazel test //test:tests //test:hazel_test //test:jsonl_test` green
      (existing ASCII-English fixtures tokenize equivalently under the utf8
      default — suite stayed green).

### Stemming CLI: expose opt-in stemming through the JSONL CLIs

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
