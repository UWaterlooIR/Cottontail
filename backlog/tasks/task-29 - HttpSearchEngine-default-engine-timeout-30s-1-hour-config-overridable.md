---
id: TASK-29
title: 'HttpSearchEngine: default engine timeout 30s -> 1 hour, config-overridable'
status: To Do
assignee: []
created_date: '2026-07-03 13:25'
updated_date: '2026-07-03 13:29'
labels: []
dependencies: []
priority: medium
ordinal: 43000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The isj engine's HTTP client timeout (isj/isj_agent/engine/http.py, HttpSearchEngine.__init__ timeout=30.0) is far too short for real tiered/multitext cascades on large burrows: in the TASK-22 A/B, ~6s-per-tier x 6-tier requests blew the 30s limit, every timeout became an EngineError bounce, and the ABANDONED requests kept computing server-side, piling up until the server was wedged for hours. A short client timeout converts slow-but-finite work into wasted work plus a snowball.

Change (Mark, 2026-07-04): default timeout = 3600s (1 hour). Rationale: the engine should practically never abandon a request it asked for; slow queries surface as slow turns (visible in traces), not as bounces that mislead the model into rewriting a fine query (observed in the A/B: models needlessly simplified good programs in response to timeout bounces). TASK-28 (materialize-wrapping) attacks the slowness itself; this task stops the abandonment damage.

Scope:
1. HttpSearchEngine default timeout 30.0 -> 3600.0.
2. Make it configurable: [cottontail_http_json_server] timeout_s in config.toml, plumbed through config.build_search_engine (absent -> the 3600 default). Document in config.example.toml.
3. Note in the engine docstring WHY it is long (abandoned requests keep running server-side; a client timeout is not a cancel).
4. Check other client timeouts for consistency: the healthz/connection timeout can stay short (connection establishment is different from long queries) if separately configurable via httpx.Timeout(connect=...) — implementer's choice, document it.

Tests: default is 3600 when config omits it; config value is honored; existing engine tests unaffected (they inject client/transport). Branch: claude/ssr-parallel-etc (standing decision).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 HttpSearchEngine's default timeout is 3600s, with the docstring explaining that abandoned requests keep computing server-side
- [ ] #2 [cottontail_http_json_server] timeout_s overrides it via build_search_engine; documented in config.example.toml
- [ ] #3 Tests cover the default and the config override; the full isj suite passes
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Setup: Mark TASK-29 In Progress. Current branch claude/ssr-parallel-etc.
2. Engine (isj/isj_agent/engine/http.py)
   2.1 HttpSearchEngine.__init__: timeout default 30.0 -> 3600.0; construct the client with httpx.Timeout(timeout, connect=10.0) so CONNECTION establishment still fails fast (a down server should not hang an hour) while reads/queries get the full hour.
   2.2 Docstring: explain WHY it is long — an httpx timeout is not a cancel; the server keeps computing an abandoned request, so short timeouts waste server work, snowball under retries (observed wedging the 1M server in the TASK-22 A/B), and mislead the model into rewriting fine queries.
3. Config plumbing (isj/isj_agent/config.py, isj/config.example.toml)
   3.1 build_search_engine: pass timeout=float(cfg["timeout_s"]) when present; absent -> engine default.
   3.2 config.example.toml [cottontail_http_json_server]: document timeout_s with the default and the rationale one-liner.
4. Tests (isj/tests)
   4.1 Default: HttpSearchEngine(base_url=...) with no timeout -> client timeout read == 3600 (and connect == 10).
   4.2 Override: build_search_engine({..., "timeout_s": 45}) -> 45. Existing engine tests (which inject client/transport) unaffected.
   4.3 Full isj suite.
5. Finalize: notes, ACs, commit, push (rides PR #9).
<!-- SECTION:PLAN:END -->
