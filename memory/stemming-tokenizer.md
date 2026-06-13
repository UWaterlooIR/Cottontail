---
name: stemming-tokenizer
description: StemmingTokenizer merged to main (PR #2); query-side --stem CLI work still TODO, specced in docs/stemming.md
metadata:
  type: project
---

A general **`StemmingTokenizer`** (`src/stemming_tokenizer.{h,cc}`, tokenizer
name `"stemming"`) was added and **merged to `main` via PR #2**
(https://github.com/UWaterlooIR/Cottontail/pull/2, merged 2026-06-13). Designed
with Charlie Clarke: a decorator that wraps any inner tokenizer + any stemmer
(both in its nested `name`/`recipe` recipe) and emits a **co-located** stem
feature at the same address as each token, but only when the stemmer's `bool`
out-param reports it actually stemmed (no-op short/non-alpha terms get no stem
feature; Porter self-namespaces with a `porter:` prefix). Exact + stemmed
features share addresses, so one index carries both streams — no stats, no second
text store. Only `tokenize` is specialized; `skip`/`split` delegate; recipe
round-trips through dna.

**Query/CLI side is now BUILT** (open PR #3 on `claude/tool-agent`): the JSONL
indexer takes `--stem porter` (builds with the `stemming` tokenizer) and
`--tokenizer ascii|utf8`; the query tool takes `--stem` (stems terms into
`porter:` GCL atoms, ranks via ssr). See `docs/stemming.md`. Note the implemented
mechanism does NOT use `warren->stemmer()` — that path only stems in
`icover_ranking`, and `Warren::set_stemmer()` persists to dna; instead jsonl_core
stems the query and targets the stemmed features directly.

**Landmine to remember:** `Warren::set_stemmer()` (`src/warren.h`) **persists** the
stemmer into the burrow dna (`set_parameter_` → `set_parameter_in_dna`,
`simple_warren.cc:142`). Never use it for a per-query `--stem` toggle — it would
make stemming the permanent global default and kill exact-by-default. Activate
Porter in-memory only. See [[pr-jsonl-cli]] for the related JSONL CLI work.
