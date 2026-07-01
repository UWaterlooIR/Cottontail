---
id: TASK-19
title: TieredQuery queryable over a native tiered_query_search server endpoint
status: To Do
assignee: []
created_date: '2026-06-30 21:48'
updated_date: '2026-07-01 02:54'
labels: []
dependencies:
  - TASK-18
references:
  - docs/design/agent-architecture.txt
priority: medium
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add the second concrete Queryable (tiered_query_search) by exposing Cottontail's NATIVE tiered ranking as a server tool, rather than reimplementing the cascade in Python. Depends on the Queryable seam (TASK-18). The Controller already calls queryable.execute(...) and reads the trace via the descriptor, so this task adds a new server endpoint plus a thin Python TieredQuery and touches NO controller code.

## Why native, not a Python cascade
Cottontail already implements the MultiText precise->broad cascade in C++ (src/ranking.cc tiered_ranking, citing the TREC-4 Shortest Substring Ranking paper): ssr per tier, cross-tier de-dup by container, tier-order scoring. It is stranded only because the HTTP server exposes just cover_search, and the agent talks only to that server. Reimplementing the cascade in Python would duplicate the reference logic and risk drift. Instead we expose the cascade over HTTP and keep the Python side thin. (This folds in the native-endpoint work the earlier Python-only draft of this task had deferred.)

## Design (agreed in conversation)
The tiered RESPONSE shape is byte-identical to cover_search (total_matches, unjudged_matches, atom_counts, results[rank,score,cp,summary]). So CoverResponse and cover_results_json (C++) and the Python SearchResponse model are reused unchanged. Only the REQUEST differs: a tiers string-array replaces the single query.

### C++ -- new enriched handler jsonl_tiered_query_search
Built entirely from existing helpers (cover_rewrite, cover_leaves, cover_ranking, cover_summary); no new ranking math and no src/ edits.
- TieredSpec mirrors CoverSpec with a std::vector<std::string> tiers replacing query (same top_k / exclude / window / max_covers / max_words).
- Rewrite and validate each tier (word-star family marker -> stemmed stream; malformed GCL is a reported error, same as cover_search).
- atom_counts = UNION across every tier's cover_leaves, deduped by term (first-seen order), each carrying its corpus occurrence count. Present and deterministic on every call, so a count of 0 unambiguously means a dead atom and never an un-run tier.
- total_matches and unjudged_matches = EXACT union: one cover_ranking depth=0 counting pass over the OR of the tiers (+ tier1 ... tierN) counts the distinct docs matching ANY tier. 0 if and only if every tier is dry. (Exact, not the sum upper bound of the earlier Python design.)
- Cascade with provenance: loop the tiers in order; per tier run cover_ranking(tier, depth=top_k+|exclude|, exclude); merge with cross-tier cp de-dup, appending in tier order, and RECORD the surfacing tier per cp.
- Faithful per-tier summaries: post-filter exclude, cap top_k; for each survivor re-walk ITS surfacing tier's hopper within [cp,cq] and call cover_summary (cover_search's phase-2, but per surfacing tier).
- Score: tier-monotonic (like native fake_score = depth - position) so the precise->broad tier order survives the final list's (grade, score) tiebreak; per-tier cover-density scores are not comparable across tiers.

### Server + JSON
- tiered_spec_from(json) reads tiers[] / top_k / exclude / window / max_covers / max_words; the response reuses cover_results_json.
- New route POST /tools/tiered_query_search mirrors the cover_search route.

### Python -- thin, mirrors CoverQuery
- The SearchEngine Protocol (engine/base.py) gains tiered_search(tiers, *, top_k, exclude, window) -> SearchResponse.
- HttpSearchEngine implements it (POST /tools/tiered_query_search; body {tiers, top_k, exclude, window}; parse the reused SearchResponse).
- FakeEngine gains tiered_search (returns the next scripted SearchResponse and records the call). No KeyedFakeEngine is needed -- the cascade and de-dup now live in C++, so the Python fake just returns a pre-merged response.
- TieredQuery(tiers) implements Queryable: tool_name tiered_query_search; schema {tiers: array of string, required tiers}; from_tool_arguments validates a non-empty list of strings; trace_arguments returns a {tiers: [...]} dict; query_string returns the tiers joined by " ; " (a plain string, never a dict); execute forwards to engine.tiered_search(self.tiers, ...) (a thin forwarder).

## Degenerate / base case
A single-tier tiered_query_search must behave identically to cover_search (same results, ranking, counts, and summaries). Locked with a C++ test.

## Out of scope
The TieredSearcher agent and its prompt (TASK-20); any Controller or BaseSearcher change; auto-generated tiers (build_tiers) -- v1 takes an explicit tier list from the Searcher; native src/ ranking.cc edits.

## Perf note (not in scope)
The handler re-runs all tiers on each execute() call (the Controller pages by re-calling with a grown exclude). A later optimization can cache the merged list server-side and page it in memory -- which also keeps atom_counts complete. Document, do not implement.

Key files: apps/jsonl_core.{h,cc} (TieredSpec + jsonl_tiered_query_search), apps/jsonl_json.{h,cc} (tiered_spec_from; reuse cover_results_json), apps/cottontail-jsonl-server.cc (route), isj/isj_agent/engine/{base,http,fake}.py, isj/isj_agent/protocol/queryable.py (TieredQuery), and tests in test/jsonl.cc and isj/tests/.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. C++ handler. In apps/jsonl_core.h add struct TieredSpec (mirror CoverSpec, std::vector<std::string> tiers replacing query) and declare jsonl_tiered_query_search(warren, TieredSpec, CoverResponse* out, error). In apps/jsonl_core.cc implement it from existing helpers only (cover_rewrite, cover_leaves, cover_ranking, cover_summary): union atom_counts across tiers; exact union total/unjudged via a depth=0 cover_ranking over (+ tier1 ... tierN); per-tier cascade with cross-tier cp de-dup and recorded surfacing tier; faithful per-tier summaries; tier-monotonic score. No src/ edits.
2. JSON + route. In apps/jsonl_json.{h,cc} add tiered_spec_from(json) and reuse cover_results_json for the response. In apps/cottontail-jsonl-server.cc register POST /tools/tiered_query_search, mirroring the cover_search route (parse -> tiered_spec_from -> jsonl_tiered_query_search -> cover_results_json).
3. C++ tests. Add TEST(JsonlTiered, ...) cases to test/jsonl.cc against a real burrow: cross-tier de-dup, exact union counts, per-tier summaries, exclude handling, and single-tier == cover_search (base case). Run bazel test //test:jsonl_test.
4. Python engine. Add tiered_search to the SearchEngine Protocol (engine/base.py), implement it in HttpSearchEngine (engine/http.py; POST /tools/tiered_query_search), and add a scripted tiered_search to FakeEngine (engine/fake.py).
5. Python queryable. Add TieredQuery to protocol/queryable.py: schema/from_tool_arguments/trace_arguments/query_string plus a thin execute that forwards to engine.tiered_search.
6. Python tests. Extend test_queryable.py (schema, from_tool_arguments incl. validation, trace/string forms, execute forwarding), test_http_engine.py (tiered POST hits the right route with the tiers body via MockTransport), and test_controller.py (a TieredQuery-emitting stub -> judged-results payload leads with "tiers", surfacing_query is the joined string, controller unchanged). Run uv run --directory isj python -m pytest.
7. Build + live check. bazel build the server; run the hand-authored 5-tier Yellowstone cascade against a porter burrow for the live end-to-end AC (needs the running stack).
<!-- SECTION:PLAN:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A new server tool POST /tools/tiered_query_search accepts a tiers string-array request and returns the cover_search response shape (total_matches, unjudged_matches, atom_counts, results with rank/score/cp/summary)
- [ ] #2 jsonl_tiered_query_search runs the tiers as a cascade using Cottontail existing ranking primitives (no Python cascade and no src/ ranking edits) with cross-tier de-duplication, so a cp returned by an earlier tier never reappears
- [ ] #3 cps in the incoming exclude never appear in the results
- [ ] #4 Results are merged in tier order (tighter tiers rank above looser) and capped at top_k, and every tier still runs even when earlier tiers already fill top_k so atom_counts and the counts stay complete
- [ ] #5 atom_counts is the union of every tier leaves deduped by term, present and deterministic on every call, so a count of 0 means a dead atom and never an un-run tier
- [ ] #6 total_matches and unjudged_matches are the EXACT distinct union across tiers (a depth=0 counting pass over the OR of the tiers) and are 0 if and only if every tier is dry
- [ ] #7 Each result summary is built against the specific tier that surfaced that document (faithful per-tier biasing) reusing cover_summary
- [ ] #8 A single-tier tiered_query_search returns results identical to cover_search for the same query, locked by a C++ base-case test in test/jsonl.cc
- [ ] #9 C++ tests in test/jsonl.cc drive jsonl_tiered_query_search against a real burrow and assert cross-tier de-dup, exact union counts, per-tier summaries, and exclude handling
- [ ] #10 The SearchEngine Protocol gains tiered_search and HttpSearchEngine posts to /tools/tiered_query_search with a tiers/top_k/exclude/window body, parsing the reused SearchResponse
- [ ] #11 TieredQuery implements Queryable with tool_name tiered_query_search and a tiers string-array argument, from_tool_arguments validates a non-empty list of strings, trace_arguments returns a tiers-keyed dict and query_string returns the tiers joined into a plain string (never a dict), and execute forwards to engine.tiered_search
- [ ] #12 The Controller and BaseSearcher are unchanged, and a controller-level Python test drives a TieredQuery-emitting searcher stub and asserts the judged-results payload leads with the tiers field and surfacing_query records the joined tier string
- [ ] #13 Python tests (test_queryable.py, test_http_engine.py) cover the schema, from_tool_arguments, trace/string forms, and the HTTP forwarding, and the full pytest suite plus bazel test //test:jsonl_test pass
- [ ] #14 A live end-to-end run of the hand-authored 5-tier Yellowstone cascade returns a merged, de-duplicated, per-tier-summarized ranked list
<!-- AC:END -->
