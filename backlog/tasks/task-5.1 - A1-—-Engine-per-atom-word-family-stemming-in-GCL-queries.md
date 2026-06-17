---
id: TASK-5.1
title: 'A1 — Engine: cover_search tool with per-atom word* family stemming'
status: To Do
assignee: []
created_date: '2026-06-17 12:49'
updated_date: '2026-06-17 21:55'
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
   learn about `word*`.
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
Qwen3.6-27B, gemma-4-31B (docs/searcher-agent-lessons-June-16-2026.md).

`cover_search` is the dedicated tool that understands `word*`. `search_gcl` stays a pure
GCL primitive (and keeps its own whole-query `--stem` flag); the two coexist in different
profiles. Stem parity: the stemmed feature is `porter:` + Cottontail's Porter(word), so
resolve via the burrow's own Porter (`stem_atom(burrow_stemmer(warren), word)`); a second
(Python) Porter would drift. Porter::stem sets stemmed=true and returns `porter:<stem>`
for any alphabetic word >= 3 chars (even when the stem equals the word), so the stemmed
stream is symmetric: `porter:bear` matches both "bear" and "bears". Short/non-alpha words
fall back to the exact surface form.

How the stemmed stream works (docs/stemming.md 4-5): an index built with `--stem porter`
co-locates a stemmed stream; a stemmed feature is `porter:`+Porter(word); GCL leaves
featurize verbatim, so `porter:<stem>` resolves to it.

How ssr scores (so you know what covers are): ssr enumerates the query's minimal COVERS
(p,q) and, per :item, scores the document as the SUM over its covers of 1/(K + q - p).
A document typically contains MULTIPLE covers. (Today's ssr returns only the CONTAINER
span as a result and jsonl_core mislabels it `best_passage` = the document head — this
task replaces that with a real cover-biased summary, see below.)

## Required behavior (the contract) — all in the NEW cover_search tool

1. cover_search takes a GCL cover query that MAY use `word*`, ranks documents (:item) by
   `ssr` cover density (score = sum over the document's covers of 1/(K+q-p)), and returns
   per document: { rank, score, docid, summary }. `summary` REPLACES the old
   `best_passage` (which was merely the document head). (A2 adds the request `window`
   override plus total_matches/unjudged_matches/atom_counts/exclude_docids.)
2. `word*` (a single word token ending in a literal `*`) -> the stemmed-stream atom via a
   SHARED helper resolve_family_atom(stemmer, word) = stem_atom(stemmer, word). cover_search
   ALWAYS interprets `word*` (no flag). Symmetric fallback for unstemmable words (`ox*` ->
   exact `ox`).
3. Bare terms without `*` are exact. Operators, parens, `:tags`, and quoted phrases with
   no `*` are unmodified.
4. `word*` is honored INSIDE a quoted phrase: a phrase desugars to (>> (# n) (... ...));
   do the translation BEFORE the normal expand_phrases pass. A non-trailing, mid-token
   `*` is a clear error (CLI exit 2 / server 400), no crash.
5. `word*` needs a stemmed stream; if the burrow has none and the query uses `word*`,
   fail with a clear error (CLI exit 2 / server 400) — no silent fallback to exact.
6. Register cover_search into A0's registry under the `isj` profile, with a schema in
   describe_json so `GET /describe?profile=isj` advertises it.

## The `summary` field — a cover-biased extractive summary

For each returned document, build `summary` from the query's covers within it (the same
covers ssr summed). Window size W is in TOKENS (corpus term positions), default 75
(about 3 sentences at ~25 words); A2 lets the request override it.

Algorithm:
1. Enumerate the query's covers within the document, in DOCUMENT ORDER.
2. For each cover (p,q): width T = max(W, cover_length). Center a T-token window on the
   cover. If it runs past the document body start or end, SHIFT it inward to keep T
   tokens (clamp to the whole body if the body is shorter than T). If W < cover_length,
   the cover itself is the window.
3. Take the UNION of these windows in document order (never reorder).
4. MERGE windows that overlap or touch into one longer extent (do NOT repeat material).
5. Render each merged extent (translate its tokens to text); join consecutive
   (non-contiguous) extents with the separator space-dot-space-dot-space-dot-space
   ( . . . ) to show a gap. A single extent has no separator.
`summary` is that joined string. (Optionally also return the merged extents' token
offsets for later grounding; the text is the required deliverable.)

## Non-goals

- Do NOT modify `search_gcl` (pure GCL) or the GCL core.
- Do NOT add total_matches/unjudged_matches/atom_counts/exclude_docids or the request-side
  `window` override — that is A2 (A2 reuses this summary, parameterized by `window`).
- Do NOT give cover_search a whole-query stem flag; per-atom `word*` is its mechanism.
- Do NOT touch the Python isj agent. Do NOT write a warren-level stemmer into dna; only
  READ the burrow's stemmer.
<!-- SECTION:DESCRIPTION:END -->

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
- [ ] #11 search_gcl's behavior and response are unchanged (regression check).
- [ ] #12 cover_search is registered in describe_json so GET /describe?profile=isj advertises it.
- [ ] #13 bazel test //test:tests //test:hazel_test //test:jsonl_test is green, with new cases in test/jsonl.cc, test/jsonl_cli.cc, and test/jsonl_server.cc; docs/stemming.md and the cli/server specs document cover_search and the word* marker as distinct from search_gcl and the whole-query --stem flag.
- [ ] #14 cover_search's per-document response is {rank, score, docid, summary}: score is the ssr sum over the document's covers of 1/(K+q-p), rank is 1-based, and summary REPLACES the old best_passage.
- [ ] #15 summary is a cover-biased extractive summary: for each of the query's covers (in document order) center a window of max(window, cover_length) tokens on the cover, shifting inward at a document boundary to preserve the width (clamped to the body); take the union of the windows; merge overlapping or touching windows into one extent with no repeated text.
- [ ] #16 summary renders each merged extent and joins non-contiguous extents with a spaced-dots separator ( . . . ); extents are never reordered (always document start to end); a single extent has no separator.
- [ ] #17 The summary window size is a parameter in tokens with default 75 (about 3 sentences at ~25 words); cover_search collects the query's covers within each returned :item to build the summary; A2 adds the request field to override the window.
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Depends on A0 (register cover_search into the isj profile). Adapt as needed.

1. Read A0's tool registry, docs/stemming.md (4-5), burrow_stemmer()/stem_atom()/
   stem_gcl() in apps/jsonl_core.cc, expand_phrases() in src/parse.cc (read-only), and
   ssr_ranking() + RankingResult in src/ranking.cc (note ssr currently emits the
   CONTAINER span, which is why best_passage was the document head).
2. ONE shared helper resolve_family_atom(stemmer, word) -> stem_atom(...). The single
   place word* becomes a feature atom; A2's atom_counts reuses it.
3. cover_search function in apps/jsonl_core.{h,cc}: input a cover query (+ top_k);
   rewrite word* atoms (bare and phrase-internal, before expand_phrases), error on a
   non-trailing mid-token `*`; require burrow_stemmer()!=null if word* present; rank docs
   by ssr within :item. Leave search_gcl untouched.
4. Build summary per returned doc: enumerate the query's covers WITHIN that :item (e.g.
   a cover hopper restricted to the doc's container) and apply the summary algorithm
   (window default 75 tokens; center max(W,cover) per cover; shift at body edges; union;
   merge overlapping/touching; join non-contiguous extents with the spaced-dots
   separator; document order). Translate extents to text via txt()->translate.
5. Register cover_search in A0's registry: POST /tools/cover_search handler + describe_json
   schema in the isj profile; response { rank, score, docid, summary }.
6. CLI: a way to invoke cover_search for testing (e.g. a --cover mode); minimal.
7. Docs: docs/stemming.md per-atom word* marker (cover_search, honored in phrases);
   server-spec/cli-spec describe cover_search and the summary field, distinct from
   search_gcl and the whole-query --stem flag.

Build (per CLAUDE.md): bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example
Test: bazel test //test:tests //test:hazel_test //test:jsonl_test (plus server test).
Determinism: stemmed and exact share addresses — assert docid SET membership, not order.
<!-- SECTION:PLAN:END -->
