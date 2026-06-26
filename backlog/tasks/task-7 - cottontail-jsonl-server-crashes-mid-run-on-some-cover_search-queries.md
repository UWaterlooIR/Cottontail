---
id: TASK-7
title: cottontail-jsonl-server crashes mid-run on some cover_search queries
status: To Do
assignee: []
created_date: '2026-06-26 13:56'
updated_date: '2026-06-26 14:29'
labels:
  - bug
  - server
dependencies:
  - TASK-8
  - TASK-9
priority: high
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The cottontail-jsonl-server (apps/cottontail-jsonl-server) crashes / drops the connection mid-session while serving cover_search, observed during the TASK-5.9 (C3) live gate against Scrapheap/climbmix-1M-porter.burrow with the real gpt-oss-120b Searcher.

OBSERVED (runs/bear, intent 00): the server served two nested cover queries fine, then on the next cover_search the client saw 'Server disconnected without sending a response.' followed by 'Connection refused' for every subsequent request — i.e. the server process died and did not restart, so the rest of the run (intents 01-02) got connection-refused and degraded to zero results. The isj Searcher/Orchestrator (C3) handled this gracefully (each EngineError bounced, agents stopped cleanly, run exited 0 with valid output), so this is NOT an isj bug; it is a C++ server robustness bug that limits live runs.

KNOWN-GOOD queries (returned hits, no crash):
  (^ black bear* (+ prevent* avoid* reduce* attack* ) (+ food* store* campsite* etiquette* ))
  (^ black bear* (+ hiker* backpack* camp* ) (+ food* store* canister* hang* ) (+ etiquette* practice* ))

The exact crashing query at intent-00 turn 6 was NOT captured: the engine_error trace event records only the transport message, not the GCL query that triggered it. (A separate, earlier hand-probe in the same session — '(>> (^ bear) (^ attack))' — returned an empty body and coincided with a server death; another, '(^ bear*)', was REJECTED cleanly with 'Could not construct hopper from valid gcl: (^ porter:bear)' and did NOT crash. So some malformed/edge GCL is handled gracefully and some kills the process.)

LIKELY AREAS: the cover_search request handler in apps/cottontail-jsonl-server, jsonl_cover_search / the CoverResponse path (TASK-5.1/5.2/5.11), and src/ranking.cc — an uncaught C++ exception or a segfault (e.g. on a particular GCL shape or an empty/large cover) that takes down the whole server rather than returning a JSON error.

WHY IT MATTERS: the live Searcher pipeline cannot complete a multi-intent run if a single query can kill the server; recall-first runs issue many varied cover queries, so this will recur.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Root cause identified: a concrete, minimal cover_search request (GCL query + params) is shown to reliably crash or disconnect cottontail-jsonl-server against a porter-stemmed burrow (the 1M dev burrow, or a smaller reproducer), with the server's stderr/crash signal (segfault vs uncaught exception) captured.
- [ ] #2 Fix applied so that no client request can take down the server: a request that previously crashed it now either returns a well-formed JSON error (like the existing graceful 'could not construct hopper' rejection) or a valid result, and the server keeps serving subsequent requests.
- [ ] #3 A regression test exercises the crashing query (C++ server/handler level, or jsonl_cover_search) and asserts the server returns an error/result instead of dying; bazel test //test:tests stays green.
- [ ] #4 A live re-run of the C3 CLI on the black-bear question over the 1M burrow completes all interpretations without a mid-run server death (no 'Server disconnected' / 'Connection refused' cascade).
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Discovered during TASK-5.9 (C3) live gate; flagged in that task's notes. Repro context: bazel-bin/apps/cottontail-jsonl-server --burrow Scrapheap/climbmix-1M-porter.burrow --port 8080, then the isj CLI (isj/isj_agent/cli.py) on a multi-intent question. Start by replaying the known-good queries then bisecting toward the failing turn-6 shape; consider enabling a core dump / running the server under a debugger to catch the signal.

Observability AC (was #3) removed and split out: isj-side trace logging -> TASK-8; server-side request/response logging -> TASK-9. Per the user, implement TASK-8 and TASK-9 FIRST; this crash fix builds on them (the server [req] intake log from TASK-9 is how the crashing query gets captured for AC#1). Depends on TASK-8, TASK-9.
<!-- SECTION:NOTES:END -->
