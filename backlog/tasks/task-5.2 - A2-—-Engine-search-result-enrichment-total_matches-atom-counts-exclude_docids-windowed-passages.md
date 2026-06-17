---
id: TASK-5.2
title: >-
  A2 — Engine: cover_search enrichment (total/unjudged matches, atom_counts,
  exclude_docids, windowed passages)
status: To Do
assignee: []
created_date: '2026-06-17 13:36'
updated_date: '2026-06-17 16:48'
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
`search_gcl` (the pure GCL primitive) or the GCL core.

1. GCL core — `src/parse.cc`, `src/gcl.h`. DO NOT MODIFY.
2. `search_gcl` — pure GCL primitive, a DIFFERENT tool/profile. LEAVE ALONE. (Because
   cover_search is its own new tool, this task adds NOTHING to and removes NOTHING from
   search_gcl — there is no result_count/truncated/stemmed cleanup to do; cover_search
   is designed clean from the start in A1.)
3. `cover_search` (the isj-profile tool from A1) — ALL of this task's additions go here.
4. Python isj agent — separate track; consumes the cover_search request/response below.

May modify: `apps/jsonl_core.{h,cc}`, `apps/jsonl_json.{h,cc}`,
`apps/cottontail-jsonl-server.cc` (the cover_search handler/registration),
`apps/cottontail-jsonl-query.cc`; tests in `test/jsonl.cc`, `test/jsonl_cli.cc`,
`test/jsonl_server.cc`; docs `docs/cottontail-jsonl-cli-spec.md`,
`docs/cottontail-search-server-spec.md`. Must NOT modify `search_gcl` or the GCL core.
Language: C++. DEPENDS ON A1 (it extends A1's cover_search and reuses A1's word*->feature
helper; A1 in turn depends on A0).

## The one input, its faces

cover_search's canonical input is its request struct in `apps/jsonl_core.h` (a QuerySpec
or a dedicated CoverQuery), consumed by the cover_search function. It is populated from:
- HTTP: `POST /tools/cover_search` JSON body, parsed by the cover_search handler in
  `apps/cottontail-jsonl-server.cc`. THIS is the request the Python agent sends.
- CLI: a cover_search invocation in `cottontail-jsonl-query` (for testing).
- `GET /describe?profile=isj` (A0) advertises the schema via describe_json.
"Add X to the request" = add a field to the struct, parse it in the HTTP handler and the
CLI, and advertise it in describe_json (isj profile).

## What this task adds to cover_search, in two pictures

### REQUEST (POST /tools/cover_search)
```
// A1 base
{ "query": "(^ black bear* attack*)", "top_k": 10 }

// AFTER A2 (two new optional inputs)
{ "query": "(^ black bear* attack*)", "top_k": 10,
  "exclude_docids": ["shard_00012_0003", "shard_00018_0044"],   // NEW: judged set to skip
  "window": 30 }                                                // NEW: MINIMUM total passage size in tokens, centered on the cover
```

### RESPONSE (cover_search)
```
// A1 base
{ "results": [
    { "rank": 1, "score": 12.3, "docid": "shard_00012_0003",
      "best_passage": { "start": 4123, "end": 4127, "text": "<the raw cover text>" } } ] }

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
      "best_passage": {
        "start": 4123, "end": 4127,                // raw cover span — score/rank computed on THIS
        "window_start": 4108, "window_end": 4142,  // NEW: the window span actually returned
        "text": "<the cover, centered in a window of at least `window` tokens>"  // CHANGED
      } } ] }
```

UNITS (state in docs): total_matches and unjudged_matches are DOCUMENT counts (matching
:item rows); atom_counts[i].count is the atom's total OCCURRENCE count in the corpus
(collection frequency), NOT a document count; `window` is a MINIMUM total token count
(see below).

## Why these signals (the ISJ loop)

The agent makes ONE tool call per turn (no parallel calls), so each signal rides on the
one cover_search response:
- total_matches  -> "How broad is this query?" (independent of judging)
- unjudged_matches -> "How much NEW vs. already-judged?" The agent passes judged docids
  as exclude_docids; the engine skips them (MultiText 'Next' button).
- atom_counts    -> "Did an atom match NOTHING?" count 0 flags a typo/dead expansion.
- windowed passage -> enough context to judge a possibly-tiny cover.
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
  Both are DOCUMENT counts. Optional: unjudged_matches = total_matches minus excluded
  docids that match Q. Empty exclude -> equal.
- atom_counts: per leaf {term, count}; term as written; count = total OCCURRENCES of the
  feature it resolves to (idx()->count), via A1's shared word*->feature helper (so bear*
  reports the stemmed family's occurrences; ox* the exact feature); 0 if nothing; no stream.
  (The existing ExplainLeaf field is misnamed `df` but holds occurrences — fix the wording.)
- windowed passages: ranking/scoring stay on the RAW cover (r.p(), r.q()) UNCHANGED.
  `window` W is the MINIMUM total passage size in TOKENS (corpus term positions — NOT
  characters, NOT model tokens), centered on the cover. The returned passage length is
  max(cover_length, W): if the cover is already >= W, the passage IS the cover (W has no
  effect); otherwise pad to W total -- L = cover length; pad = W - L; left = floor(pad/2);
  right = pad - left; span = [p-left, q+right]. Clamp to the :item body (body_start ..
  container_q); if one side clamps, shift the leftover to the other side to still reach W
  where possible. Set best_passage.text to that span, keep start/end as the raw cover,
  report window_start/window_end. Default W when window is absent.

RANK/SCORE: score is exclusion-INVARIANT (ssr scores each doc independently — no idf/
stats). rank is 1-based WITHIN the returned post-exclusion results, RESTARTING at 1 each
call, no gaps; NOT an absolute position and NOT the TREC submission rank (assigned later
by the Compiler).

## Non-goals

- Do NOT modify search_gcl or the GCL core.
- Do NOT re-implement A1's word* translation (reuse A1's shared helper).
- Do NOT add new ranking models or change ssr scoring (the window is presentation only).
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
- [ ] #14 cover_search request accepts window: the MINIMUM total passage size in tokens (corpus term positions, not characters or model tokens), centered on the cover; if the cover is longer than window the whole cover is returned; sensible default when absent.
- [ ] #15 best_passage.text is the matched cover centered in a passage of length max(cover length, window) tokens, clamped to the :item with the leftover shifted to the other side when one side clamps; start/end remain the raw cover and window_start/window_end report the returned span; rank and score are unchanged.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Depends on A1 (extends cover_search; reuses A1's word*->feature helper). Adapt as needed.

1. Read A1's cover_search function + request struct + handler, the ssr_ranking call and
   container, the best_passage construction (r.p()/r.q()/container_q()), the exact-string
   :docno match in jsonl_get, and apps/jsonl_json.{h,cc} + the server's cover_search
   registration from A0/A1.
2. cover_search request struct: add exclude_docids (vector<string>) and window (MINIMUM
   total tokens). Response carrier gains total_matches, unjudged_matches, atom_counts
   (vector of {term,count}); best_passage gains window_start/window_end and text becomes
   the windowed span.
3. Effective container: no exclusions -> ":item"; with exclusions ->
   (!> :item (+ (>> :docno "d1") ...)) via exact-string :docno match. Rank within it so
   excluded rows never appear and top_k fills.
4. total_matches = count Q over ":item"; unjudged_matches = count Q over the carved
   container (or total minus excluded-that-match). Both document counts.
5. atom_counts: for each leaf, resolve via A1's helper, count = idx()->count(resolved) =
   occurrences; emit {term-as-written, count}; no stream. Fix the misnamed `df`.
6. windowing: window W = MINIMUM total passage size in tokens, centered on the cover.
   passage length = max(cover_len, W). If cover_len >= W, span = the cover. Else
   pad = W - cover_len; left = floor(pad/2); right = pad - left; span = [p-left, q+right];
   clamp to the :item body, shifting any clamped remainder to the other side to reach W.
   Set best_passage.text + window_start/window_end; keep start/end = raw cover; scoring
   unchanged.
7. Serialize the additions in apps/jsonl_json.{h,cc}; parse exclude_docids/window in the
   cover_search HTTP handler and CLI; advertise them in describe_json (isj profile). Keep
   the server stateless.
8. Tests (test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc): total_matches vs a
   plain :item count; unjudged after exclusion; excluding the would-be #1 hit; score
   unchanged under exclusion; rank restarts at 1; atom_counts {term,count} incl. a zero
   and a word* family count; window as a minimum total size centered (incl. cover-longer-
   than-window -> passage equals cover, and an edge-clamp case) with unchanged score;
   statelessness. Determinism: assert docid SET membership.
9. Docs: cli-spec + server-spec document the cover_search additions (units: matches =
   documents, atom_counts.count = occurrences/no stream, window = MINIMUM total tokens
   centered, cover never truncated), exclude_docids, window, and the rank/score semantics.

Build (per CLAUDE.md): bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example
Test: bazel test //test:tests //test:hazel_test //test:jsonl_test (plus server test).
<!-- SECTION:PLAN:END -->
