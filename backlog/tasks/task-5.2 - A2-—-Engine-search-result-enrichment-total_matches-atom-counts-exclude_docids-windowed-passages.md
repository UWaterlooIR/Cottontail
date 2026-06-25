---
id: TASK-5.2
title: >-
  A2 — Engine: cover_search enrichment (total/unjudged matches, atom_counts,
  exclude=cp, window)
status: To Do
assignee: []
created_date: '2026-06-17 13:36'
updated_date: '2026-06-25 21:23'
labels:
  - engine
  - cpp
  - searcher
dependencies:
  - TASK-5.11
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
2. `search_gcl` — pure GCL primitive, a DIFFERENT, separate tool. LEAVE ALONE. (Because
   cover_search is its own new tool, this task adds NOTHING to and removes NOTHING from
   search_gcl — there is no result_count/truncated/stemmed cleanup to do; cover_search
   is designed clean from the start in A1.)
3. `cover_search` (the tool from A1) — ALL of this task's additions go here.
4. Python isj agent — separate track; consumes the cover_search request/response below.

May modify: `apps/jsonl_core.{h,cc}`, `apps/jsonl_json.{h,cc}`,
`apps/cottontail-jsonl-server.cc` (the cover_search handler), `apps/cottontail-jsonl-query.cc`;
tests in `test/jsonl.cc`, `test/jsonl_cli.cc`, `test/jsonl_server.cc`; docs cli-spec +
server-spec. Must NOT modify `search_gcl` or the GCL core. Language: C++. DEPENDS ON A1 (it
extends A1's cover_search and reuses A1's word*->feature helper and summary).

## The one input, its faces

cover_search's request struct (apps/jsonl_core.h) is populated from: the
`POST /tools/cover_search` JSON body (parsed by the cover_search handler in the server —
THIS is the agent's request), the CLI, and advertised via describe_json at `GET /describe`.
"Add X to the request" = add a field to the struct, parse it in the handler and CLI,
advertise it in describe_json.

## What this task adds to cover_search, in two pictures

### REQUEST (POST /tools/cover_search)
```
// A1 base
{ "query": "(^ black bear* attack*)", "top_k": 10 }

// AFTER A2 (two new optional inputs)
{ "query": "(^ black bear* attack*)", "top_k": 10,
  "exclude": ["shard_00012_0003", "shard_00018_0044"],   // NEW: judged set to skip
  "window": 75 }                                                // NEW: MINIMUM total passage size in tokens, centered on the cover
```

### RESPONSE (cover_search)
```
// A1 base
{ "results": [
    { "rank": 1, "score": 12.3, "docid": "shard_00012_0003",
      "summary": "<A1 cover-biased extractive summary>" } ] }

// AFTER A2
{
  "total_matches": 50,        // NEW: DOCUMENTS matching the query in the whole corpus (ignores exclude)
  "unjudged_matches": 4,      // NEW: matching DOCUMENTS not in exclude; the results below are these
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
TOKENS (a MINIMUM total per the summary algorithm; see A1).

## Why these signals (the ISJ loop)

The agent makes ONE tool call per turn (no parallel calls), so each signal rides on the
one cover_search response:
- total_matches  -> "How broad is this query?" (independent of judging)
- unjudged_matches -> "How much NEW vs. already-judged?" The agent passes judged docids
  as exclude; the engine skips them (MultiText 'Next' button).
- atom_counts    -> "Did an atom match NOTHING?" count 0 flags a typo/dead expansion.
- window         -> how much context each cover gets in the summary the agent reads.
The searcher has NO concept of index streams; atom_counts is {term, count} only (no
stream), and term is the atom AS WRITTEN (bear*), never the internal porter: form.

## How each is computed

EXCLUSION IS A DIRECT cp POST-FILTER (doc-6). cover_search ranks a query Q within plain
:item; exclude is a list of cp integers (the cps the agent saw in prior results); the
engine over-fetches depth = top_k + |exclude| and drops any ranked result whose cp is in
the exclude set (an integer membership test). No exclusions -> plain ranking. Per-request;
server stateless; NO sidecar, NO docno. Each returned hit carries its cp (the cp->docno
rewrite is C2 persistence).
- total_matches and unjudged_matches are a BYPRODUCT of that single ssr ranking pass (which
  visits every matching container), not separate enumerations:
    total_matches    = matching containers counted as the ssr loop closes each (ignores exclude)
    unjudged_matches = those whose cp is NOT in the exclude set
  Both DOCUMENT counts; integer-only. Empty exclude -> equal.
- atom_counts: per leaf {term, count}; term as written; count = total OCCURRENCES of the
  feature it resolves to (idx()->count) via A1's shared word*->feature helper (bear* ->
  family occurrences; ox* -> exact feature); 0 if nothing; no stream. (Fix the misnamed `df`.)
- window: the request field that sets the SUMMARY window in tokens (default 75 when absent).
  A2 does NOT re-implement the summary — A1 builds it (per-cover windows centered, MINIMUM
  total size, union, merge, join with spaced dots, document order). A2 just plumbs `window`
  through to A1's summary builder. Larger window -> more context per cover. Ranking/scoring
  stay on the raw covers (UNCHANGED) regardless of window.

RANK/SCORE: score is exclusion-INVARIANT (ssr scores each doc independently — no idf/
stats). rank is 1-based WITHIN the returned post-exclusion results, RESTARTING at 1 each
call, no gaps; NOT an absolute position and NOT the TREC submission rank.

## Non-goals

- Do NOT modify search_gcl or the GCL core.
- Do NOT re-implement A1's word* translation or A1's summary algorithm — reuse them.
- Do NOT add new ranking models or change ssr scoring (window only affects the summary
  text, not rank/score).
- Do NOT add server-side session/judged-set state (exclude is per-request), any
  stream/exact-stemmed field, or any per-agent/profile filtering; never expose porter:.
- Do NOT touch the Python isj agent.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 cover_search response includes total_matches: DOCUMENTS matching the query within the plain :item container (ignoring exclude), equal to a plain :item count for that query, independent of top_k.
- [ ] #2 cover_search response includes unjudged_matches: matching DOCUMENTS whose cp is NOT in the exclude set, computed as a byproduct of the single ssr ranking pass; results are drawn from these; equals total_matches when exclude is empty.
- [ ] #3 cover_search response includes atom_counts: per query leaf a {term, count} entry, term as written (e.g. bear*, never the porter: form), count = total OCCURRENCES of the feature it resolves to; count 0 if it matches nothing; NO stream field.
- [ ] #4 A word* atom in atom_counts reports its resolved family's occurrences via A1's shared helper; an unstemmable word* such as ox* resolves to the exact feature.
- [ ] #5 cover_search request accepts exclude (a list of cp integers); it excludes by a direct cp POST-FILTER on the ranked results, over-fetching depth = top_k + size of exclude, so with top_k=K and some excluded the response still returns up to K non-excluded hits.
- [ ] #6 Excluding a cp that would otherwise rank first yields a result whose rank 1 is the next-best non-excluded document; each surviving document's score is identical with and without the exclusion (cover density is per-document).
- [ ] #7 rank is the 1-based position within the returned post-exclusion results, restarting at 1 each call with no gaps; it is NOT an absolute corpus position and NOT the TREC submission rank.
- [ ] #8 search_gcl is untouched (regression check); cover_search carries NO legacy fields (no result_count, truncated, or stemmed).
- [ ] #9 The server cover_search is stateless: two requests with different exclude do not interfere.
- [ ] #10 Determinism: tests assert on cp SET membership, not tied order.
- [ ] #11 bazel test //test:tests //test:hazel_test //test:jsonl_test is green, with new cases in test/jsonl.cc, test/jsonl_cli.cc, and test/jsonl_server.cc.
- [ ] #12 docs/cottontail-jsonl-cli-spec.md and docs/cottontail-search-server-spec.md document the cover_search additions: total_matches/unjudged_matches as DOCUMENT counts, atom_counts.count as total OCCURRENCES (no stream), exclude, window, and the rank/score semantics.
- [ ] #13 cover_search request accepts window: the summary window size in tokens (default 75 when absent), plumbed into A1's summary builder as the per-cover context width; A2 does not re-implement the summary.
- [ ] #14 Increasing window yields a longer summary (more context per cover) while rank and score are unchanged; the response per result is {rank, score, cp, summary} plus the new top-level total_matches/unjudged_matches/atom_counts.
- [ ] #15 GET /describe lists cover_search and its request fields (including exclude and window) and its response shape; the server advertises all its tools with no per-agent/profile filtering.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Depends on A1b (TASK-5.11), which already introduced the CoverResponse aggregate
(total_matches/unjudged_matches/atom_counts/results) + AtomCount{term,count} and switched
jsonl_cover_search to return CoverResponse*. A2 POPULATES those fields and adds the request
fields; it does not reintroduce the types. Reuses A1's word*->feature helper and summary. Adapt.

CONFIRMED DESIGN DECISIONS (Q1-Q6, agreed with the user 2026-06-18):
- Q1 [REVISED per doc-6] Exclusion is an EXACT cp post-filter, not a GCL containment carve.
  Resolving each docno to its cp (sidecar reverse) and testing cp membership is exact and
  collision-free by construction, so the old containment / over-exclusion caveat no longer
  applies (and there is nothing to document about it).
- Q2 unjudged_matches = matching containers whose cp is NOT in the exclude-cp set =
  total_matches - (the excluded docids that ACTUALLY match Q). It is NOT total -
  len(exclude): excluding a docid that does not match Q (or is absent) leaves the
  count unchanged. STATE this explicitly in code comments and docs.
- Q3 total_matches/unjudged_matches are EXACT, computed as a byproduct of the single ssr
  ranking pass (ssr already visits every matching cover) -- no separate enumeration passes
  and no precomputed df. (Cost governed by query selectivity, not top_k -- accepted.)
- Q4 atom_counts leaves: dedup by term-AS-WRITTEN (first-seen order); a quoted phrase
  contributes each inner WORD as a leaf; bare vs word* counted from the resolved feature.
- Q5 "Fix the misnamed df" = cover_search uses `count` (occurrences); do NOT rename the
  legacy explain tool's df (different tool, out of scope).
- Q6 The CLI --cover mode gains --window N and --exclude <docid> (repeatable) for testing.
- B1 CONSTRAINT: B1's SearchResponse is extra="forbid", so cover_results_json must emit
  EXACTLY {total_matches, unjudged_matches, atom_counts, results} and NOTHING else (no query
  echo, no elapsed_ms, no result_count/truncated). Field names/types must match B1 exactly.

1. Read A1's cover_search function (its summary builder + CoverSpec + handler), A1b's
   CoverResponse/AtomCount, the ssr_ranking container arg, the docid phrase in jsonl_get
   (single token, or (... t1 t2 ...)), and apps/jsonl_json.{h,cc} + the server's handler.
2. CoverSpec (request) gains exclude (vector<string>) and window (size_t, default 75).
   CoverResponse already carries total_matches/unjudged_matches/atom_counts (A1b) -- A2 fills.
3. Exclusion: resolve exclude -> cp via the sidecar (cached). Rank Q within plain
   ":item", over-fetching depth = top_k + |exclude|; drop ranked results whose cp is in the
   exclude-cp set (integer membership). No exclusions -> rank plain ":item", no post-filter.
4. Counts as a byproduct of the SAME ranking pass (no separate (>> container Q) enumerations):
   - total_matches = matching containers counted as the ssr loop closes each (ignores exclude; independent of top_k).
   - unjudged_matches = those whose cp is not in the exclude-cp set = total - (excluded docids
     that actually match Q). Equal to total when exclude is empty. NOT total -
     len(exclude) (Q2) -- comment this in code. Both are DOCUMENT counts, EXACT (Q3).
5. atom_counts -- ENUMERATE THE QUERY'S LEAVES, one {term, count} per content term:
   - A "leaf" is a content term (bare word or word* marker). Operators
     (^ + ... <> << >> !> !< # @), parens, and :tags are NOT leaves. EXTEND is_gcl_operator
     to the full parser table (add !> !< # @, src/parse.cc:19) so operators are never
     miscounted (cover_rewrite/explain benefit too).
   - Quoted phrases: each WORD inside is its own leaf ("black bear*" -> black, bear*), not the
     quote-mangled tokens. Dedup by term-AS-WRITTEN, first-seen order (Q4).
   - term shown = AS WRITTEN (bear*, never porter:); COUNT from the RESOLVED feature: word* ->
     resolve_family_atom (A1's helper) -> porter:<stem> (or exact fallback, e.g. ox*); bare ->
     exact. count = idx()->count(featurize(resolved)) = total OCCURRENCES, 0 if none. NO stream.
   - Implement a focused leaf collector (a scan like gcl_terms, but word*-aware, phrase-aware,
     full operator set). Input is the ORIGINAL spec.query (already validated by cover_rewrite,
     so no mid-token '*' reaches here).
   - "Fix the misnamed df": the field is `count` = occurrences, NOT `df`; do NOT rename the
     legacy explain tool's df (Q5).
6. window: pass spec.window (default 75) into A1's cover_summary instead of the kCoverWindow
   constant; do NOT duplicate the algorithm. Larger window -> longer summary; rank/score
   unchanged.
7. Serialize total_matches/unjudged_matches/atom_counts in cover_results_json -- and ONLY
   those four keys (B1 extra="forbid"). Parse exclude/window in cover_spec_from (server)
   and the CLI --cover mode (add --exclude repeatable + --window, Q6). Advertise
   exclude/window in describe_json. Server stays stateless.
8. Tests (assert docid SET membership, Q10):
   - test/jsonl.cc: total_matches vs a plain :item count and top_k-independence; unjudged after
     exclusion (= total - excluded-that-match); excluding the would-be #1 promotes next-best; a
     survivor's score unchanged under exclusion; rank restarts at 1; atom_counts incl. a ZERO
     case (zzz*), a word* FAMILY count, a bare exact count, term-as-written, phrase-word
     leaves, dedup; window larger -> longer summary, rank/score unchanged; excluding a
     non-matching/absent docid leaves unjudged == total.
   - test/jsonl_cli.cc: --cover --window N (longer summary) and --cover --exclude <docid>.
   - test/jsonl_server.cc: exclude over HTTP (excluded docid gone, unjudged decremented,
     total present); statelessness across two different excludes; NO legacy fields
     (result_count/truncated/stemmed) in the JSON; /describe lists exclude + window.
9. Docs: cli-spec §4.8 + server-spec §3 document the additions: total_matches/unjudged_matches
   as DOCUMENT counts (unjudged = total - excluded-that-match, Q2), atom_counts.count =
   OCCURRENCES/no stream, leaves = the query's content terms, window = MINIMUM total tokens
   centered (cover never truncated), exclude (with the Q1 containment-match caveat),
   and the rank/score semantics. (A1 already wrote the "A2 adds ..." stubs.)

Build (per CLAUDE.md): bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example
Test: bazel test //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). SUPERSEDES the prior docno/sidecar note. Exclusion is a DIRECT cp post-filter: the request `exclude` is a list of cp integers (no docno, no resolution, no sidecar/cache); over-fetch top_k + |exclude|; drop hits whose cp is in the exclude set. Each returned hit carries its cp (response {rank, score, cp, summary}). total/unjudged_matches are a byproduct of the single ssr pass (unjudged = matching cps not in exclude). atom_counts/window/rank/score unchanged. Authoritative: doc-6 + docs/indexing.md section 4.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @claude
created: 2026-06-25 21:23
---
NAMING (doc-7) + cp-native (doc-6): the response examples in this task showing {"docid": ...} predate cp-native -- results now carry cp (doc-6), and the canonical persisted id is docno (doc-7), never docid. exclude is cp integers. Use docno/text internally when implementing.
---
<!-- COMMENTS:END -->
