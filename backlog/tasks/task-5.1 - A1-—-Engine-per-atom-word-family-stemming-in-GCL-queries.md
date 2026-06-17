---
id: TASK-5.1
title: 'A1 — Engine: cover_search tool with per-atom word* family stemming'
status: To Do
assignee: []
created_date: '2026-06-17 12:49'
updated_date: '2026-06-17 15:53'
labels:
  - engine
  - cpp
  - searcher
dependencies:
  - TASK-5.3
references:
  - docs/searcher-agent-lessons-June-16-2026.md
  - docs/stemming.md
  - docs/cottontail-jsonl-cli-spec.md
  - apps/jsonl_core.cc
  - apps/jsonl_core.h
  - src/parse.cc
  - test/jsonl.cc
  - test/jsonl_cli.cc
  - CLAUDE.md
parent_task_id: TASK-5
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives (architecture — read before touching anything)

C++ change in the JSONL search-tool layer. This task CREATES A NEW TOOL, `cover_search`
— it does NOT modify the existing `search_gcl`.

1. GCL core — `src/parse.cc`, `src/gcl.h`, the hoppers. DO NOT MODIFY. Read only.
2. `search_gcl` — the existing tool, a PURE interface to GCL. LEAVE IT ALONE: it must NOT
   learn about `word*`. (The earlier POC agent perverted search_gcl by piling agent
   conveniences onto it; we are undoing that by separating concerns.)
3. NEW tool `cover_search` — the ISJ agent's search tool. ALL of this task's behavior
   goes here: a new function in `apps/jsonl_core.{h,cc}`, a new endpoint
   `POST /tools/cover_search`, registered into the `isj` profile via A0's registry.
4. Python isj agent — separate track; it later calls `cover_search`.

May modify: `apps/jsonl_core.{h,cc}`, `apps/jsonl_json.{h,cc}` (cover_search schema +
serialization), `apps/cottontail-jsonl-server.cc` (register the endpoint),
`apps/cottontail-jsonl-query.cc` (a way to run cover_search for testing); tests in
`test/jsonl.cc`, `test/jsonl_cli.cc`, `test/jsonl_server.cc`; docs `docs/stemming.md`,
`docs/cottontail-jsonl-cli-spec.md`, `docs/cottontail-search-server-spec.md`.
Must NOT modify: `src/parse.cc`, `src/gcl.h`, the GCL core, or `search_gcl`'s behavior.
Language: C++. DEPENDS ON A0 (the tool registry / isj profile this tool registers into).

## Context

The ISJ agent (separate track) writes Boolean cover queries and wants a word AND its
morphological family without enumerating inflections or knowing the engine's stem
encoding. The agent-facing surface is a trailing asterisk on a single word: `bear*` =
"match bear and its family (bears, attacked, ...)". Validated across gpt-oss-120b,
Qwen3.6-27B, gemma-4-31B (docs/searcher-agent-lessons-June-16-2026.md): models reliably
write the FULL word + `*` but mis-stem if asked to write the engine's raw `porter:` form.

`cover_search` is the dedicated tool that understands `word*`. `search_gcl` stays a pure
GCL primitive (and keeps its own whole-query `--stem` flag for human power users); the
two coexist in different profiles. Why the translation is C++ in this tool and not
Python: the stemmed feature is `porter:` + Cottontail's Porter(word); resolving via the
burrow's own Porter (`stem_atom(burrow_stemmer(warren), word)`) guarantees parity, where
a second (Python) Porter would drift.

How the stemmed stream works (docs/stemming.md sections 4-5): an index built with
`--stem porter` co-locates a stemmed stream; a stemmed feature is `porter:`+Porter(word);
GCL leaves featurize verbatim, so `porter:<stem>` resolves to it.

## Required behavior (the contract) — all in the NEW cover_search tool

1. cover_search takes a GCL cover query that MAY use `word*`, ranks covers within `:item`
   via `ssr` (cover density), and returns ranked passages. Its BASE response (this task)
   is: results: [ { rank, score, docid, best_passage:{ start, end, text } } ]. (A2 adds
   total_matches/unjudged_matches/atom_counts/exclude_docids/windowing.)
2. `word*` (a single word token ending in a literal `*`, e.g. `bear*`, `statistics*`) is
   translated to the stemmed-stream atom via a SHARED helper:
   resolve_family_atom(stemmer, word) = stem_atom(stemmer, word) (= `porter:<stem>`).
   cover_search ALWAYS interprets `word*` (that is its purpose; no flag).
3. Symmetric fallback: an unstemmable word (short/non-alpha, e.g. `ox`) resolves to the
   exact term (no `porter:` prefix), so `ox*` matches `ox`. No silent miss.
4. Bare terms WITHOUT `*` are exact. Operators, parens, `:tags` (`:item`, `:docno`), and
   quoted phrases with no `*` are unmodified.
5. `word*` is honored INSIDE a quoted phrase too. A phrase is sugar:
   `expand_phrases` desugars "w1 ... wn" into (>> (# n) (... w1 ... wn)); so "black bear*"
   becomes (>> (# 2) (... black <stem-of-bear>)), matching the family at that position
   (exact/stemmed share addresses). Do the phrase translation in cover_search BEFORE the
   normal expand_phrases pass so the tokenizer's split() cannot drop the `*`. The ONLY
   error case is a NON-TRAILING, mid-token `*` (e.g. at*ack, or a star mid-word in a
   phrase): a clear error (CLI exit 2 / server 400), no crash.
6. `word*` needs a stemmed stream. If the burrow has none (`burrow_stemmer()` null) and
   the query contains any `word*`, fail with a clear error (CLI exit 2 / server 400); do
   NOT silently fall back to exact.
7. Register cover_search into A0's registry under the `isj` profile, with a request/
   response schema in describe_json so `GET /describe?profile=isj` advertises it.

## Non-goals

- Do NOT modify `search_gcl` (it stays pure GCL) or the GCL core (`src/parse.cc`,
  `src/gcl.h`, hoppers).
- Do NOT add total_matches/unjudged_matches/atom_counts/exclude_docids/windowing — that
  is A2 (it extends cover_search).
- Do NOT give cover_search a whole-query stem flag; per-atom `word*` is its mechanism.
- Do NOT touch the Python isj agent. Do NOT write a warren-level stemmer into dna (the
  stemming.md landmine) — only READ the burrow's stemmer.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Depends on A0 (register cover_search into the isj profile). Adapt as needed.

1. Read A0's tool registry, docs/stemming.md (4-5), burrow_stemmer()/stem_atom()/
   stem_gcl() in apps/jsonl_core.cc, and expand_phrases() in src/parse.cc (read-only:
   a phrase desugars to (>> (# n) (... ...))).
2. Add ONE shared helper, e.g. resolve_family_atom(stemmer, word) -> stem_atom(...). It
   is the single place word* becomes a feature atom; A2's atom_counts reuses it so the
   feature searched and any count reported cannot drift.
3. Add a cover_search function in apps/jsonl_core.{h,cc}: input a cover query (+ top_k);
   rewrite word* atoms over the GCL string (bare-word case) and word* inside quoted
   phrases (desugar-with-stem case, before expand_phrases), error on a non-trailing
   mid-token `*`; if any word* present require burrow_stemmer()!=null (else error); rank
   covers within :item via ssr; return ranked passages {rank,score,docid,best_passage}.
   Leave search_gcl and its path untouched.
4. Register cover_search in A0's registry: POST /tools/cover_search handler + a schema in
   describe_json, added to the isj profile. apps/jsonl_json.{h,cc} gains cover_search
   request parsing and response serialization.
5. CLI: a way to invoke cover_search for testing (e.g. a --cover mode on
   cottontail-jsonl-query, or a dedicated path); minimal.
6. Docs: docs/stemming.md gains a "per-atom word* marker (cover_search)" subsection
   (note it is honored inside phrases); server-spec/cli-spec describe the cover_search
   tool, distinct from search_gcl and the whole-query --stem flag.

Build (per CLAUDE.md): bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example
Test: bazel test //test:tests //test:hazel_test //test:jsonl_test (plus server test).
Determinism: stemmed and exact share addresses — assert docid SET membership, not order.
<!-- SECTION:PLAN:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A new cover_search tool exists (a jsonl_core function + POST /tools/cover_search), registered into the isj profile via A0; search_gcl is unchanged and remains a pure GCL interface with no word* handling.
- [ ] #2 In cover_search on a --stem porter burrow, bear* matches a row whose body contains only 'bears' (family recall).
- [ ] #3 In cover_search, the bare term bear (no asterisk) does NOT match a row containing only 'bears'; an index built without --stem is unaffected.
- [ ] #4 Mixed cover (^ black bear*) matches with black exact and bear* as a family; a quoted phrase with no asterisk is left exact.
- [ ] #5 Symmetric fallback: ox* matches a row containing 'ox' (Porter leaves 'ox' unchanged, so the asterisk is dropped and the exact word matches) with no error.
- [ ] #6 A starred word inside a quoted phrase is honored: a phrase of black followed by bear* matches a row containing 'black bears' (desugar-with-stem before expand_phrases; adjacency preserved via shared addresses).
- [ ] #7 A non-trailing, mid-token asterisk (e.g. at*ack, or a star mid-word in a phrase) produces a clear error (CLI exit 2 / server 400), with no crash.
- [ ] #8 A cover_search query using word* against a burrow with no stemmed stream fails with a clear error (CLI exit 2 / server 400) and does NOT silently fall back to exact.
- [ ] #9 Operators and :tags are untouched: (<< bear* :item) parses and runs with :item intact and only bear* translated.
- [ ] #10 The word*-to-feature translation is a SINGLE shared helper (used by cover_search ranking and reusable by A2's atom_counts) so the feature searched cannot drift; an unstemmable word* resolves through it to the exact feature.
- [ ] #11 cover_search's base response is results:[{rank, score, docid, best_passage:{start,end,text}}] (A2 later adds total_matches, unjudged_matches, atom_counts, exclude_docids, windowing).
- [ ] #12 search_gcl's behavior and response are unchanged (regression check).
- [ ] #13 cover_search is registered in describe_json so GET /describe?profile=isj advertises it.
- [ ] #14 bazel test //test:tests //test:hazel_test //test:jsonl_test is green, with new cases in test/jsonl.cc, test/jsonl_cli.cc, and test/jsonl_server.cc; docs/stemming.md and the cli/server specs document cover_search and the word* marker as distinct from search_gcl and the whole-query --stem flag.
<!-- AC:END -->
