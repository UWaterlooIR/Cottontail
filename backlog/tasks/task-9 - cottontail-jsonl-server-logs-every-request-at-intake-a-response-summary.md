---
id: TASK-9
title: cottontail-jsonl-server logs every request (at intake) + a response summary
status: Done
assignee:
  - '@claude'
created_date: '2026-06-26 14:10'
updated_date: '2026-06-26 14:42'
labels:
  - server
  - observability
dependencies: []
priority: high
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The cottontail-jsonl-server (apps/cottontail-jsonl-server.cc) does not log the requests it serves, so when it crashed during the TASK-5.9 (C3) live gate there was no server-side record of the offending query. It has an exception handler (logs internal errors) and an auth pre-routing handler, but no access logging.

NEED (decided with the user): log ALL requests and at least a summary of each response. CRITICAL placement: the request must be logged AT INTAKE (before handling) so a request that CRASHES the process mid-handling still leaves its query in the log -- httplib's set_logger fires only AFTER handling and would miss exactly the crash case (TASK-7).

This is the server-side half of the end-to-end request/response logging (the isj-side sibling task logs the query going out). It directly enables diagnosing the TASK-7 crash.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Every incoming request is logged at intake (before handling) to stderr: method + path + the request body for POST /tools/* (small JSON carrying the query/params). Because it is logged before the handler runs, a request that then crashes the server still leaves its query in the log.
- [x] #2 Each completed response is logged separately via httplib set_logger: method + path + status code + response size (at least a summary). The existing 4xx error bodies already carry the cause.
- [x] #3 Log writes are thread-safe: with --threads>1 serving concurrently, request and response log lines do not interleave (guard the writes with a mutex / single write per line).
- [x] #4 Logging is on by default to stderr (matching the existing startup/exception logging); document the behavior. (Optional --quiet/--no-access-log toggle if added.)
- [x] #5 Manual verification: start the server, issue a cover_search and a get_document, and confirm stderr shows a [req] line (with the query) before and a [res] line (status+size) after each; bazel build of //apps:cottontail-jsonl-server succeeds and bazel test //test:tests stays green.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
apps/cottontail-jsonl-server.cc:
1. Add a file-scope std::mutex log_mu and a small helper to write a single line under the lock.
2. set_pre_routing_handler: at the TOP (before the auth check, for every path), log '[req] <method> <path> body=<req.body>' (body present at pre-routing; for GET it is empty). This is the intake log that survives a mid-handling crash. Then run the existing auth logic unchanged.
3. After constructing svr, add svr.set_logger([](req,res){ log '[res] <method> <path> -> <status> (<res.body.size()> bytes)'; }).
4. Keep the existing exception handler; optionally also log the request body there for 500s.
5. (Optional) a --quiet flag to suppress access logging; default on.
GATE: bazel build //apps:cottontail-jsonl-server; bazel test //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test; manual [req]/[res] check against the 1M burrow.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Body logging is fine for this API (small JSON bodies); revisit if large payloads are ever posted. Pre-routing handler has req.body available because httplib parses the body before routing.

IMPLEMENTED in apps/cottontail-jsonl-server.cc. Added a file-scope std::mutex log_mu + log_line() that writes one whole line under the lock (no interleaving across the --threads workers). DISCOVERY during verification: set_pre_routing_handler fires BEFORE httplib reads the POST body, so req.body is empty there -- the first build logged '[req] POST /tools/cover_search' with no body. Fix: log at HANDLER ENTRY instead, via a log_req(req) lambda called as the first statement of every route handler (healthz, describe, the search factory covering search_text/search_gcl, cover_search, explain, get_document, count_matches). That is the earliest point req.body is available, and still before json::parse + the crash-prone jsonl_* work -- so the query is on record before a crash. set_logger logs the '[res] method path -> status (bytes)' summary after. The Authorization header (bearer token) is never logged; only req.body (queries/params). Verified live against the 1M burrow: '[req] POST /tools/cover_search body={"query":"bear","top_k":2}' then '[res] ... -> 200 (45789 bytes)', same for get_document, and GET /healthz logged. Did NOT add a --quiet toggle (AC#4 optional); logging is always on to stderr and documented in docs/running-the-search-stack.md. GATE: bazel build //apps:cottontail-jsonl-server clean; bazel test //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test all pass.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
cottontail-jsonl-server now logs every request and a response summary to stderr. Each request is logged at handler entry -- '[req] <method> <path> body=<json>' -- before json parsing and the search work, so a request that crashes the process mid-handling still leaves its query in the log (the original gap that made the TASK-7 crash undiagnosable). Each completed request logs '[res] <method> <path> -> <status> (<bytes> bytes)' via httplib set_logger. Writes are serialized through one mutex so concurrent-worker lines don't interleave; the bearer token is never logged. Note: logging had to move from the pre-routing handler (where httplib hasn't read the body yet) to handler entry. Always on to stderr; documented in the run guide. Build + the full C++ test gate are green; verified live against the 1M burrow. This unblocks TASK-7 (the server-side query record needed to catch the crashing query).
<!-- SECTION:FINAL_SUMMARY:END -->
