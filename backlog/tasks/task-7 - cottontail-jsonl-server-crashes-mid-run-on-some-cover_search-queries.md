---
id: TASK-7
title: cottontail-jsonl-server crashes mid-run on some cover_search queries
status: Done
assignee:
  - '@claude'
created_date: '2026-06-26 13:56'
updated_date: '2026-06-26 15:03'
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
- [x] #1 Root cause identified: a concrete, minimal cover_search request (GCL query + params) is shown to reliably crash or disconnect cottontail-jsonl-server against a porter-stemmed burrow (the 1M dev burrow, or a smaller reproducer), with the server's stderr/crash signal (segfault vs uncaught exception) captured.
- [x] #2 Fix applied so that no client request can take down the server: a request that previously crashed it now either returns a well-formed JSON error (like the existing graceful 'could not construct hopper' rejection) or a valid result, and the server keeps serving subsequent requests.
- [x] #3 A regression test exercises the crashing query (C++ server/handler level, or jsonl_cover_search) and asserts the server returns an error/result instead of dying; bazel test //test:tests stays green.
- [x] #4 A live re-run of the C3 CLI on the black-bear question over the 1M burrow completes all interpretations without a mid-run server death (no 'Server disconnected' / 'Connection refused' cascade).
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Discovered during TASK-5.9 (C3) live gate; flagged in that task's notes. Repro context: bazel-bin/apps/cottontail-jsonl-server --burrow Scrapheap/climbmix-1M-porter.burrow --port 8080, then the isj CLI (isj/isj_agent/cli.py) on a multi-intent question. Start by replaying the known-good queries then bisecting toward the failing turn-6 shape; consider enabling a core dump / running the server under a debugger to catch the signal.

Observability AC (was #3) removed and split out: isj-side trace logging -> TASK-8; server-side request/response logging -> TASK-9. Per the user, implement TASK-8 and TASK-9 FIRST; this crash fix builds on them (the server [req] intake log from TASK-9 is how the crashing query gets captured for AC#1). Depends on TASK-8, TASK-9.

ROOT CAUSE (via AddressSanitizer; no gdb on this host): SEGV null-deref (read addr 0x8) in cottontail::gcl::Containing::tau_ (src/gcl.cc:132, left_->tau on a null child), reached from cover_ranking (jsonl_core.cc:442) -> jsonl_cover_search:803. The crashing query is '(>> (^ bear) (^ attack))' (>> = CONTAINING; (^ x) = ALL_OF of one element). Standalone repro: bazel-bin/apps/cottontail-jsonl-query --cover '(>> (^ bear) (^ attack))' -> Segmentation fault, exit 139.

The bug is in SExpression::to_hopper (src/parse.cc): it builds left/right child hoppers, then constructs the binary operator WITHOUT null-checking them. An invalid sub-expression returns nullptr (e.g. '(^ x)' hits 'subx_.size() < 2 -> return nullptr'), so the parent operator (Containing/And/Or/FollowedBy/...) was built with a null child; hopper_from_gcl returned non-null, validation passed, and the walk dereferenced the null child -> SIGSEGV. The LINK unary case had the same latent hole.

FIX (src/parse.cc): propagate the null instead of building a node with a null child -- binary branch: 'if (left == nullptr || right == nullptr) return nullptr;'; LINK branch: 'if (expr == nullptr) return nullptr;'. Fixes all binary operators + Link at once; turns the crash into the existing graceful 'Could not construct hopper from valid gcl' path. No semantic change ('(^ x)' stays invalid, exactly as it 400s today).

REGRESSION TEST: test/gcl.cc TEST(GCLTest, NullSubexpressionDoesNotCrash) -- builds a tiny warren and asserts hopper_from_gcl returns nullptr (not a crash) for '(>> (^ alpha) (^ beta))', '(>> alpha (^ beta))', '(>> (^ alpha) beta)', '(@ (^ alpha))', and that a valid '(>> alpha beta)' still builds.

VERIFICATION: bazel test //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test all green. Standalone: the crashing query now returns a clean error JSON, exit 2 (not 139). Server: POST cover_search '(>> (^ bear) (^ attack))' -> HTTP 400 + the server keeps serving (a follow-up 'bear*' -> 200, 97310 bytes; /healthz ok). Live C3 re-run on the black-bear question over the 1M burrow: NO mid-run server death, server served 12 cover_search requests all 2xx and stayed alive the whole run.

NEW FINDING (separate, NOT this bug; flagged for its own task): in the live re-run, intents 01 and 02 failed with the vLLM 'Input length (163198/167708) exceeds model's maximum context length (131072)' -- the Searcher accumulates large cover_search responses until it blows the LLM context window. C3 isolated these as per-intent RunErrors (run still exited cleanly). This is an isj Searcher context-management issue, unrelated to the server crash.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Fixed the cottontail-jsonl-server cover_search segfault. Root cause (found with AddressSanitizer): SExpression::to_hopper (src/parse.cc) built a binary/Link GCL operator without null-checking its child hoppers, so an invalid sub-expression like '(^ x)' (which returns null) produced an operator with a null child; the walk then dereferenced it -> SIGSEGV on queries such as '(>> (^ bear) (^ attack))'. The fix propagates the null (returns nullptr instead of building a node with a null child) for every binary operator and Link, converting the crash into the existing graceful 'could not construct hopper' error -- so the server returns a clean 400 and keeps serving. Added a gcl regression test; the full C++ test gate is green; verified the formerly-crashing query is now a 400 with the server surviving, and a live C3 re-run completed with no server death. (The live run surfaced a separate isj Searcher context-window-overflow issue, flagged for its own task.)
<!-- SECTION:FINAL_SUMMARY:END -->
