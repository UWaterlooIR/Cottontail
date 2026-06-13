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

**Still TODO — the query/CLI side is NOT built.** It's specced in
**`docs/stemming.md`** (on branch `claude/tool-agent`): add `--stem` to the JSONL
indexer (build with the `stemming` tokenizer) and query tool (run the same
cover-density ranking with Porter active on the handle). The rankers already
branch on `warren->stemmer()` (`src/ranking.cc`), and a burrow opens exact by
default (constructor defaults `stemmer_` to NullStemmer).

**Landmine to remember:** `Warren::set_stemmer()` (`src/warren.h`) **persists** the
stemmer into the burrow dna (`set_parameter_` → `set_parameter_in_dna`,
`simple_warren.cc:142`). Never use it for a per-query `--stem` toggle — it would
make stemming the permanent global default and kill exact-by-default. Activate
Porter in-memory only. See [[pr-jsonl-cli]] for the related JSONL CLI work.
