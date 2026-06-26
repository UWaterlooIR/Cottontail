---
id: TASK-8
title: 'isj Searcher logs the outgoing query (going out), then the response separately'
status: Done
assignee:
  - '@claude'
created_date: '2026-06-26 14:09'
updated_date: '2026-06-26 14:33'
labels:
  - isj
  - observability
dependencies: []
priority: high
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
During the TASK-5.9 (C3) live gate the cottontail-jsonl-server crashed mid-run, and the isj trace could not tell us WHICH query was in flight: the Searcher logs the query only on the SUCCESS path (the 'search' response event), while the 'engine_error' bounce records just the transport message. So a request that fails/crashes the server leaves no record of what was sent, and --verbose shows the bounce without the query.

FIX (decided with the user): a search query must be logged WHEN IT IS MADE (going out), and the response logged SEPARATELY (success or failure). The request event exists regardless of outcome; the response is its own event.

Engine boundary unchanged; this is trace/observability only. Pairs with the server-side request/response logging (sibling task) for end-to-end visibility across the wire.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 isj_agent/agents/searcher.py emits a new 'search_request' TraceEvent the moment a query is dispatched (BEFORE the engine.search call), carrying query + top_k + window + exclude(=sorted judged cps); this is logged for every search regardless of outcome.
- [x] #2 The response is logged separately: on success the existing 'search' event (response: counts/atom_counts/results), on failure the 'engine_error' bounce which now ALSO carries the query (so the failure is self-contained). Event order is llm_turn -> search_request -> search (success) and llm_turn -> search_request -> engine_error (failure).
- [x] #3 C2 run_output.py rewrites the 'search_request' event's exclude cps -> docnos (consistent with the 'search' event) so the request event is docno-on-disk; a docno-less corpus keeps cps.
- [x] #4 cli.py --verbose renders the 'search_request' event (the outgoing query is visible live), in addition to the response events.
- [x] #5 Tests updated/added (no network): test_searcher asserts the search_request-before-search order and that engine_error carries the query; test_run_output covers the search_request exclude cp->docno rewrite. uv run --directory isj pytest exits 0; no test touches a network or a real model.
- [x] #6 isj/README.md documents 'search_request' (the request, logged going out) vs 'search' (the response), and the query now on 'engine_error'.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. searcher.py (search branch): set ts=time.time(); emit('search_request', ts, 0.0, query, top_k, window, exclude=sorted(judged)) BEFORE engine.search; on EngineError add query=query to the engine_error bounce; keep the success 'search' response event (still carries query). Update the module docstring event list.
2. run_output.py _event_dict: add a 'search_request' branch rewriting exclude cps->docnos (mirror the 'search' branch).
3. cli.py _render_event: add a 'search_request' line (e.g. '-> request: <query> (exclude=N)').
4. tests/test_searcher.py: update the event-type sequence assertion to include search_request before search; assert engine_error carries query.
5. tests/test_run_output.py: add a search_request event to the fixture; assert exclude cp->docno rewrite (and cps kept with no map).
6. isj/README.md: document search_request vs search and query-on-engine_error.
GATE: uv run --directory isj pytest green. (No live re-run; blocked by the server crash TASK-7.)
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
IMPLEMENTED. searcher.py: in the search branch, exclude=sorted(judged) computed once; emit('search_request', ts, 0.0, query, top_k, window, exclude) BEFORE engine.search; the engine_error bounce now carries query=query; the success 'search' response event unchanged (still query+counts+results). run_output.py _event_dict: added a 'search_request' branch rewriting its exclude cps->docnos. cli.py _render_event: added a 'search_request' line ('-> request: <query> (exclude=N)'). Tests: test_searcher asserts llm_turn->search_request->search order + req.query/exclude, and that the engine_error bounce carries query and a search_request was logged for the failing query; test_run_output adds a search_request event to the fixture and asserts exclude cp->docno rewrite (and cps kept with no map). README trace bullet documents search_request (going out) vs search (response) + query on engine_error. GATE: uv run pytest = 61 passed, 1 skipped (live-gated http); no network/model. No live re-run (blocked by TASK-7 server crash).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
The Searcher now logs a search query when it is dispatched (a new 'search_request' TraceEvent: query + top_k + window + exclude), separately from the response (the 'search' event on success; the 'engine_error' bounce, now carrying the query, on failure). So a request that crashes the engine/server is no longer invisible -- the in-flight query is on record in the trace and in --verbose. C2 rewrites the request event's exclude cps to docnos like every other persisted cp. 61 pytest pass with no network/model; README updated. (The live re-run is deferred to TASK-7, which fixes the server crash.)
<!-- SECTION:FINAL_SUMMARY:END -->
