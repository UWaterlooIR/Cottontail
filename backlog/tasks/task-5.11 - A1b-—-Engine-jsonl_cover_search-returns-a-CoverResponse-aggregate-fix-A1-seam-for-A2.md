---
id: TASK-5.11
title: >-
  A1b — Engine: jsonl_cover_search returns a CoverResponse aggregate (fix A1
  seam for A2)
status: To Do
assignee: []
created_date: '2026-06-18 18:25'
updated_date: '2026-06-21 19:35'
labels:
  - searcher
dependencies:
  - TASK-5.1
parent_task_id: TASK-5
ordinal: 6500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why this task exists (read first)

A1 (TASK-5.1) shipped jsonl_cover_search with the signature
`bool jsonl_cover_search(std::shared_ptr<Warren>, const CoverSpec&, std::vector<CoverHit>*, std::string*)`.
That was a planning miss: A2 (TASK-5.2) extends the cover_search RESPONSE into an aggregate
(total_matches, unjudged_matches, atom_counts, results) -- the shape B1 (TASK-5.5) already
mirrors in Python as SearchResponse. A1 should have returned that aggregate from the start
(populating only `results`), so A2 would be a pure fill-in with no signature churn. A1 is
already committed AND PUSHED, so its history is not rewritten; this small task makes the
correction forward, isolating "fix the seam" from A2's real feature work so neither commit
is muddied and git blame stays honest.

## Scope: a pure, behavior-preserving refactor

Introduce the aggregate return type and switch jsonl_cover_search to it. The on-the-wire
JSON and ALL behavior stay BYTE-FOR-BYTE identical to A1 -- only the C++ types / call form
change. A2 then populates and serializes the new response fields and adds the request fields.

## Where this lives / may modify

C++ only: apps/jsonl_core.{h,cc}, apps/jsonl_json.{h,cc}, apps/cottontail-jsonl-server.cc,
apps/cottontail-jsonl-query.cc; tests test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc.
MUST NOT modify search_gcl, the GCL core, or any other tool. No docs change (the JSON is
unchanged). DEPENDS ON A1 (TASK-5.1); BLOCKS A2 (TASK-5.2).

## What to do

1. In apps/jsonl_core.h define (mirroring B1's SearchResponse, TASK-5.5):
     struct AtomCount { std::string term; long count = 0; };
     struct CoverResponse {
       long total_matches = 0;              // populated by A2
       long unjudged_matches = 0;           // populated by A2
       std::vector<AtomCount> atom_counts;  // populated by A2
       std::vector<CoverHit> results;       // populated here (the A1 hits)
     };
   Keep CoverHit and CoverSpec exactly as A1 left them.
2. Change the signature to:
     bool jsonl_cover_search(std::shared_ptr<Warren> warren, const CoverSpec& spec,
                             CoverResponse* out, std::string* error = nullptr);
   The body is A1's, unchanged, except it fills out->results (instead of *hits) and clears
   out at the top. total_matches/unjudged_matches/atom_counts keep their defaults (A2 fills).
3. apps/jsonl_json.{h,cc}: cover_results_json takes const CoverResponse& and emits EXACTLY
   the A1 shape: { "results": [ {rank,score,cp,summary} ] }. Do NOT serialize
   total_matches/unjudged_matches/atom_counts yet (A2 adds them). The emitted JSON is
   identical to A1, byte for byte.
4. Update the two callers -- the server POST /tools/cover_search handler and the CLI --cover
   mode -- to declare a CoverResponse, pass &resp, and hand resp to cover_results_json.
5. Update the A1 tests (test/jsonl.cc JsonlCover.*, test/jsonl_cli.cc, test/jsonl_server.cc)
   to the new call form: a CoverResponse local with assertions over resp.results (the
   cover_cps helper still takes a vector<CoverHit>, so pass resp.results). The MEANING of
   every assertion is unchanged.

## Non-goals

- No new response fields in the JSON (A2 adds total_matches/unjudged_matches/atom_counts).
- No request-side fields (A2 adds exclude/window).
- No behavior change of any kind; no search_gcl / GCL-core / docs changes.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 apps/jsonl_core.h defines AtomCount{term,count} and CoverResponse{total_matches,unjudged_matches,atom_counts:vector<AtomCount>,results:vector<CoverHit>} (mirroring B1's SearchResponse), and jsonl_cover_search returns its results via a CoverResponse* out-param: jsonl_cover_search(warren, const CoverSpec&, CoverResponse*, std::string*).
- [ ] #2 The cover_search JSON is byte-for-byte identical to A1: cover_results_json(const CoverResponse&) emits exactly {"results":[{rank,score,cp,summary}]}; total_matches/unjudged_matches/atom_counts are NOT serialized in this task (deferred to A2).
- [ ] #3 Both callers (server POST /tools/cover_search; CLI --cover) and all A1 tests (test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc) are updated to the CoverResponse form, with every assertion unchanged in meaning.
- [ ] #4 jsonl_cover_search behavior is unchanged from A1 (same hits, ranks, scores, summaries, error paths); search_gcl and the GCL core are untouched.
- [ ] #5 Full build (//... minus the Boost-blocked targets) is green and //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test all pass.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Pure, behavior-preserving refactor. The emitted cover_search JSON stays BYTE-FOR-BYTE
identical to A1; only the C++ return type / call form changes. Call sites enumerated below
from the current tree. On branch claude/trec-rag-2026-design (do NOT branch).

1. apps/jsonl_core.h: between `struct CoverHit {...}` and the jsonl_cover_search declaration,
   add (mirroring B1's SearchResponse):
     struct AtomCount { std::string term; long count = 0; };        // A2 populates
     struct CoverResponse {
       long total_matches = 0;              // A2 populates
       long unjudged_matches = 0;           // A2 populates
       std::vector<AtomCount> atom_counts;  // A2 populates
       std::vector<CoverHit> results;       // populated here (the A1 hits)
     };
   Change the declaration's out-param from std::vector<CoverHit>* to CoverResponse*.
   CoverHit / CoverSpec are unchanged.
2. apps/jsonl_core.cc (jsonl_cover_search): param -> CoverResponse* out; at top
   out->results.clear() (replacing hits->clear()); the push becomes
   out->results.push_back(std::move(h)). Everything else (stemmer check, cover_rewrite,
   ssr_ranking, phase-2 cover recovery, cover_summary, all error returns) is UNTOUCHED. The
   aggregate fields keep their defaults.
3. apps/jsonl_json.{h,cc}: cover_results_json takes const CoverResponse& and iterates
   resp.results; it still emits EXACTLY {"results":[{rank,score,cp,summary}]} -- no new
   fields (A2 adds them). Identical bytes.
4. Callers (2): apps/cottontail-jsonl-server.cc (POST /tools/cover_search handler) and
   apps/cottontail-jsonl-query.cc (--cover mode): declare a CoverResponse, pass &resp, hand
   resp to cover_results_json; add `using cottontail::jsonl::CoverResponse;`.
5. test/jsonl.cc (9 JsonlCover.* tests): each `std::vector<CoverHit> hits;` -> `CoverResponse
   resp;`; each jsonl_cover_search(..., &hits, ...) -> &resp; each cover_cps(hits) ->
   cover_cps(resp.results) (the cover_cps HELPER signature stays vector<CoverHit>&).
   ResponseShape: hits[0]/hits.empty() -> resp.results[0]/resp.results.empty().
   SummaryWindowingAndGap: `for (const auto &h : hits)` -> resp.results.
   test/jsonl_cli.cc and test/jsonl_server.cc drive the binary over CLI/HTTP and assert on
   JSON, not the C++ type; since the JSON is unchanged they need NO edits and pass as-is
   (AC#3 is vacuously satisfied for them -- confirm by running, not editing).
6. NO changes to search_gcl, the GCL core, describe_json, or any doc (wire contract unchanged).

Verify:
- bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example
- bazel test //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test (all green).
  The existing JsonlCover.* assertions remain valid -> their passing IS the AC#4 regression proof.

Commit: one commit "refactor(jsonl): jsonl_cover_search returns CoverResponse aggregate (A1b)",
noting it corrects the A1 seam and keeps JSON byte-identical; then check the 5 ACs and set Done.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). SUPERSEDES the prior note. The CoverResponse aggregate shape (total_matches, unjudged_matches, atom_counts, results) is unchanged; each result (CoverHit) carries cp, not docid: {rank, score, cp, summary}. Authoritative: doc-6.
<!-- SECTION:NOTES:END -->
