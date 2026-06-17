---
id: TASK-5.2
title: >-
  A2 — Engine: cover_search enrichment (total/unjudged matches, atom_counts,
  exclude_docids, windowed passages)
status: To Do
assignee: []
created_date: '2026-06-17 13:36'
updated_date: '2026-06-17 22:01'
labels:
  - engine
  - cpp
  - searcher
dependencies:
  - TASK-5.1
references:
  - docs/searcher-agent-lessons-June-16-2026.md
  - docs/cottontail-jsonl-cli-spec.md
  - docs/cottontail-search-server-spec.md
  - apps/jsonl_core.cc
  - apps/jsonl_core.h
  - apps/jsonl_json.cc
  - apps/jsonl_json.h
  - apps/cottontail-jsonl-server.cc
  - test/jsonl.cc
  - test/jsonl_cli.cc
  - test/jsonl_server.cc
  - CLAUDE.md
parent_task_id: TASK-5
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives (architecture — read before touching anything)

C++ change that EXTENDS the `cover_search` tool created in A1. It does NOT touch
`search_gcl` or the GCL core.

1. GCL core — DO NOT MODIFY.
2. `search_gcl` — pure GCL primitive, different tool/profile. LEAVE ALONE. (cover_search
   is a clean new tool, so there is NO result_count/truncated/stemmed cleanup.)
3. `cover_search` (the isj-profile tool from A1) — ALL additions go here.
4. Python isj agent — separate track; consumes the request/response below.

May modify: `apps/jsonl_core.{h,cc}`, `apps/jsonl_json.{h,cc}`,
`apps/cottontail-jsonl-server.cc`, `apps/cottontail-jsonl-query.cc`; tests in
`test/jsonl.cc`, `test/jsonl_cli.cc`, `test/jsonl_server.cc`; docs cli-spec + server-spec.
Must NOT modify `search_gcl` or the GCL core. Language: C++. DEPENDS ON A1 (it extends
A1's cover_search, reuses A1's word*->feature helper, and configures A1's summary).

## The one input, its faces

cover_search's request struct (apps/jsonl_core.h) is populated from: the
`POST /tools/cover_search` JSON body (parsed by the cover_search handler in the server —
THIS is the agent's request), the CLI, and advertised via describe_json at
`GET /describe?profile=isj`. "Add X to the request" = add a field to the struct, parse it
in the handler and CLI, advertise it in describe_json.

## What this task adds to cover_search, in two pictures

### REQUEST (POST /tools/cover_search)
```
// A1 base
{ "query": "(^ black bear* attack*)", "top_k": 10 }

// AFTER A2 (two new optional inputs)
{ "query": "(^ black bear* attack*)", "top_k": 10,
  "exclude_docids": ["shard_00012_0003", "shard_00018_0044"],   // NEW: judged set to skip
  "window": 75 }                                                // NEW: summary window size in tokens (default 75)
```

### RESPONSE (cover_search)
```
// A1 base
{ "results": [
    { "rank": 1, "score": 12.3, "docid": "shard_00012_0003",
      "summary": "<A1 cover-biased extractive summary>" } ] }

// AFTER A2
{
  "total_matches": 50,        // NEW: DOCUMENTS matching the query in the whole corpus (ignores exclude_docids)
  "unjudged_matches": 4,      // NEW: matching DOCUMENTS not in exclude_docids; the results below are these
  "atom_counts": [            // NEW: per query leaf -> total OCCURRENCES of that atom in the corpus
    { "term": "black",   "count": 1840 },
    { "term": "bear*",   "count": 9004 },
    { "term": "attack*", "count": 5200 }
  ],
  "results": [
    { "rank": 1, "score": 12.3, "docid": "shard_00018_0044",
      "summary": "<cover-biased extractive summary, built with the requested window>" } ]
}
```

UNITS (state in docs): total_matches and unjudged_matches are DOCUMENT counts (matching
:item rows); atom_counts[i].count is the atom's total OCCURRENCE count in the corpus
(collection frequency), NOT a document count; `window` is the summary window size in
TOKENS (the per-cover context width; see A1 for the summary algorithm).

## Why these signals (the ISJ loop)

The agent makes ONE tool call per turn (no parallel calls), so each signal rides on the
one cover_search response:
- total_matches  -> "How broad is this query?" (independent of judging)
- unjudged_matches -> "How much NEW vs. already-judged?" The agent passes judged docids
  as exclude_docids; the engine skips them (MultiText 'Next' button).
- atom_counts    -> "Did an atom match NOTHING?" count 0 flags a typo/dead expansion.
- window         -> how much context each cover gets in the summary the agent reads.
The searcher has NO concept of index streams; atom_counts is {term, count} only (no
stream), and term is the atom AS WRITTEN (bear*), never the internal porter: form.

## How each is computed

EXCLUSION LIVES IN THE CONTAINER, NOT THE QUERY. cover_search ranks a query Q within a
CONTAINER (default :item). exclude_docids carves the container:
- exclude_docids -> rank within (!> :item (+ (>> :docno "d1") ...)) using the exact-string
  :docno match jsonl_get uses; excluded rows are never produced, so top_k FILLS (NOT a
  post-filter). No exclusions -> plain :item. Per-request; server stateless.
- total_matches vs unjudged_matches = SAME Q over TWO containers:
    total_matches    = count of Q within :item                  (no carve; ignores exclusions)
    unjudged_matches = count of Q within the carved (!> :item ...) container
  Both DOCUMENT counts. Optional: unjudged_matches = total_matches minus excluded docids
  that match Q. Empty exclude -> equal.
- atom_counts: per leaf {term, count}; term as written; count = total OCCURRENCES of the
  feature it resolves to (idx()->count) via A1's shared helper (bear* -> family
  occurrences; ox* -> exact feature); 0 if nothing; no stream. (Fix the misnamed `df`.)
- window: the request field that sets the SUMMARY window size in tokens (default 75 when
  absent). A2 does NOT re-implement the summary — A1 builds it (per-cover windows centered
  and sized max(window, cover_length), union, merge overlapping/touching, join
  non-contiguous extents with the spaced-dots separator, document order). A2 just plumbs
  `window` through to A1's summary builder. Larger window -> more context per cover.
  Ranking/scoring stay on the raw covers (UNCHANGED) regardless of window.

RANK/SCORE: score is exclusion-INVARIANT (ssr scores each doc independently — no idf/
stats). rank is 1-based WITHIN the returned post-exclusion results, RESTARTING at 1 each
call, no gaps; NOT an absolute position and NOT the TREC submission rank.

## Non-goals

- Do NOT modify search_gcl or the GCL core.
- Do NOT re-implement A1's word* translation or A1's summary algorithm — reuse them.
- Do NOT add new ranking models or change ssr scoring (window only affects the summary
  text, not rank/score).
- Do NOT add server-side session/judged-set state (exclude_docids is per-request) or any
  stream/exact-stemmed field, and never expose porter:.
- Do NOT touch the Python isj agent.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 cover_search response includes total_matches: DOCUMENTS matching the query within the plain :item container (ignoring exclude_docids), equal to a plain :item count for that query, independent of top_k.
- [ ] #2 cover_search response includes unjudged_matches: matching DOCUMENTS not in exclude_docids (the query counted within the exclude-carved container); results are drawn from these; equals total_matches when exclude_docids is empty.
- [ ] #3 cover_search response includes atom_counts: per query leaf a {term, count} entry, term as written (e.g. bear*, never the porter: form), count = total OCCURRENCES of the feature it resolves to; count 0 if it matches nothing; NO stream field.
- [ ] #4 A word* atom in atom_counts reports its resolved family's occurrences via A1's shared helper; an unstemmable word* such as ox* resolves to the exact feature.
- [ ] #5 cover_search request accepts exclude_docids; exclusion is via container-carve DURING ranking (not a post-filter), so with top_k=K and some excluded the response still returns up to K non-excluded hits.
- [ ] #6 Excluding a docid that would otherwise rank first yields a result whose rank 1 is the next-best non-excluded document; each surviving document's score is identical with and without the exclusion (cover density is per-document).
- [ ] #7 rank is the 1-based position within the returned post-exclusion results, restarting at 1 each call with no gaps; it is NOT an absolute corpus position and NOT the TREC submission rank.
- [ ] #8 search_gcl is untouched (regression check); cover_search carries NO legacy fields (no result_count, truncated, or stemmed).
- [ ] #9 The server cover_search is stateless: two requests with different exclude_docids do not interfere.
- [ ] #10 GET /describe?profile=isj advertises cover_search's exclude_docids and window inputs and the total_matches/unjudged_matches/atom_counts/windowed response.
- [ ] #11 Determinism: tests assert on docid SET membership, not tied order.
- [ ] #12 bazel test //test:tests //test:hazel_test //test:jsonl_test is green, with new cases in test/jsonl.cc, test/jsonl_cli.cc, and test/jsonl_server.cc.
- [ ] #13 docs/cottontail-jsonl-cli-spec.md and docs/cottontail-search-server-spec.md document the cover_search additions: total_matches/unjudged_matches as DOCUMENT counts, atom_counts.count as total OCCURRENCES (no stream), exclude_docids, window, and the rank/score semantics.
- [ ] #14 cover_search request accepts window: the summary window size in tokens (default 75 when absent), plumbed into A1's summary builder as the per-cover context width; A2 does not re-implement the summary.
- [ ] #15 Increasing window yields a longer summary (more context per cover) while rank and score are unchanged; the response per result is {rank, score, docid, summary} plus the new top-level total_matches/unjudged_matches/atom_counts.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Depends on A1 (extends cover_search; reuses A1's word*->feature helper and summary). Adapt.

1. Read A1's cover_search function (its summary builder + request struct + handler), the
   ssr_ranking container, the exact-string :docno match in jsonl_get, and
   apps/jsonl_json.{h,cc} + the server's cover_search registration.
2. cover_search request struct: add exclude_docids (vector<string>) and window (tokens).
   Response carrier gains total_matches, unjudged_matches, atom_counts (vector {term,count}).
3. Effective container: no exclusions -> ":item"; with exclusions ->
   (!> :item (+ (>> :docno "d1") ...)) via exact-string :docno match. Rank within it so
   excluded rows never appear and top_k fills.
4. total_matches = count Q over ":item"; unjudged_matches = count Q over the carved
   container (or total minus excluded-that-match). Both document counts.
5. atom_counts: per leaf, resolve via A1's helper, count = idx()->count(resolved) =
   occurrences; emit {term-as-written, count}; no stream. Fix the misnamed `df`.
6. window: pass the request `window` (default 75 when absent) into A1's summary builder;
   do not duplicate the algorithm. Verify a larger window yields a longer summary with
   unchanged rank/score.
7. Serialize total_matches/unjudged_matches/atom_counts in apps/jsonl_json.{h,cc}; parse
   exclude_docids/window in the cover_search handler and CLI; advertise them in
   describe_json (isj profile). Server stays stateless.
8. Tests (test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc): total_matches vs a
   plain :item count; unjudged after exclusion; excluding the would-be #1 hit; score
   unchanged under exclusion; rank restarts at 1; atom_counts {term,count} incl. a zero
   and a word* family count; window override changes summary length but not rank/score;
   statelessness. Determinism: assert docid SET membership.
9. Docs: cli-spec + server-spec document the cover_search additions (units: matches =
   documents, atom_counts.count = occurrences/no stream, window = summary window in
   tokens default 75), exclude_docids, and the rank/score semantics.

Build (per CLAUDE.md): bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example
Test: bazel test //test:tests //test:hazel_test //test:jsonl_test (plus server test).
<!-- SECTION:PLAN:END -->
