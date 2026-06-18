---
id: TASK-5.7
title: >-
  C1 — isj: HttpSearchEngine (httpx client for cover_search) + full real-LLM
  live e2e
status: To Do
assignee: []
created_date: '2026-06-18 03:52'
updated_date: '2026-06-18 03:53'
labels:
  - python
  - isj
  - searcher
  - integration
dependencies:
  - TASK-5.3
  - TASK-5.1
  - TASK-5.2
  - TASK-5.5
  - TASK-5.6
references:
  - docs/cottontail-search-server-spec.md
  - apps/cottontail-jsonl-server.cc
  - isj/isj_agent/engine
  - isj/isj_agent/protocol/search.py
  - isj/isj_agent/config.py
  - isj/config.example.toml
  - isj/README.md
  - Scrapheap/climbmix-1000-utf8-porter.burrow
parent_task_id: TASK-5
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

Python, in the `isj/` uv project (package `isj_agent`; `uv sync --project isj` after
changes). New files: `isj_agent/engine/http.py` (HttpSearchEngine); a builder in
`isj_agent/config.py` + a `[cottontail_http_json_server]` section in `isj/config.toml` and
`isj/config.example.toml`; a minimal live-run entry (a subcommand in `isj_agent/cli.py` or
a small script); tests in `isj/tests/`. Add `httpx` as a direct dependency in
`isj/pyproject.toml`. DEPENDS ON B1 (TASK-5.5: SearchEngine Protocol, SearchResponse types,
EngineError), B2 (TASK-5.6: the Searcher), and A0/A1/A2 (TASK-5.3/5.1/5.2: the server's
`cover_search` endpoint in the `isj` profile). The automated tests need only the B1
contract; the LIVE e2e needs the whole stack built and running.

## Context (for an agent new to this project)

This is the CLIENT end of the cover_search HTTP/JSON contract. The A tasks built the SERVER
(`cottontail-jsonl-server`'s `cover_search` endpoint, C++); C1 builds the Python CLIENT,
`HttpSearchEngine`, which implements B1's `SearchEngine` Protocol by making HTTP calls to
that server and parsing the JSON into B1's pydantic types. The Searcher (B2) is
transport-agnostic: it calls `engine.search(...)` / `engine.read(...)`; in tests that engine
is B1's FakeEngine, in live use it is this HttpSearchEngine.

Server contract (verified in apps/cottontail-jsonl-server.cc):
- Endpoints: `GET /healthz` (public), `GET /describe`, `POST /tools/<name>`.
- Auth: bearer token — header `Authorization: Bearer <token>`; env `COTTONTAIL_API_TOKEN`
  (or `--token`); OPTIONAL on a loopback (127.0.0.1) bind, required off-loopback.
- `cover_search` (A1/A2): `POST /tools/cover_search` with body
  { query, top_k, exclude_docids, window } -> { total_matches, unjudged_matches,
  atom_counts:[{term,count}], results:[{rank,score,docid,summary}] }.
- `get_document`: `POST /tools/get_document` with { docid } -> { docid, found, text }.
- A bad request returns HTTP 400 with an error JSON (the server's fail() helper).

B1's error channel: search()/read() may raise EngineError on ANY engine failure; the B2
controller bounces on it (feeds the message back to the model). HttpSearchEngine maps
non-2xx responses and httpx transport errors to EngineError — a 400 (e.g. invalid GCL the
C++ engine rejected) carries the server's message so the model can self-correct.

## Required behavior (the contract)

1. HttpSearchEngine (isj_agent/engine/http.py) via httpx, implementing the B1 SearchEngine
   Protocol (so isinstance(HttpSearchEngine(...), SearchEngine) is True). Sketch:

   import httpx
   from isj_agent.engine.base import EngineError          # SearchEngine is the Protocol
   from isj_agent.protocol.search import SearchResponse

   class HttpSearchEngine:
       def __init__(self, base_url, token=None, timeout=30.0, client=None):
           headers = {"Authorization": f"Bearer {token}"} if token else {}
           self._client = client or httpx.Client(base_url=base_url.rstrip("/"),
                                                 headers=headers, timeout=timeout)

       def search(self, query, *, top_k=10, exclude_docids=(), window=75) -> SearchResponse:
           body = {"query": query, "top_k": top_k,
                   "exclude_docids": list(exclude_docids), "window": window}
           try:
               r = self._client.post("/tools/cover_search", json=body)
           except httpx.HTTPError as e:
               raise EngineError(f"cover_search transport error: {e}") from e
           if r.status_code != 200:
               raise EngineError(_server_error(r))   # carries the server message (e.g. 400 invalid GCL)
           return SearchResponse.model_validate(r.json())

       def read(self, docid) -> str | None:
           try:
               r = self._client.post("/tools/get_document", json={"docid": docid})
           except httpx.HTTPError as e:
               raise EngineError(f"get_document transport error: {e}") from e
           if r.status_code != 200:
               raise EngineError(_server_error(r))
           d = r.json()
           return d["text"] if d.get("found") else None

   `_server_error(r)` returns the server's error message — the JSON error field if present,
   else f"HTTP {r.status_code}: {r.text}". Allow an injected `client` so tests can pass an
   httpx.Client built on httpx.MockTransport (no network).

2. Config (Option A, section named `cottontail_http_json_server`). Add to config.toml and
   config.example.toml:

   [cottontail_http_json_server]
   base_url = "http://127.0.0.1:8081"
   # api_key_env = "COTTONTAIL_API_TOKEN"   # bearer-token env var; omit on a loopback server with no token

   and in config.py a builder mirroring build_client:

   def build_search_engine(cfg) -> HttpSearchEngine:
       token = None
       if "api_key_env" in cfg:
           token = os.environ.get(cfg["api_key_env"])
           if token is None:
               raise RuntimeError(f"env var '{cfg['api_key_env']}' (api_key_env) is not set")
       return HttpSearchEngine(base_url=cfg["base_url"], token=token)

   The bearer token comes ONLY from the env var named by api_key_env — never a flag, never
   logged (repo secrets rule). On a loopback server with no token, omit api_key_env.

3. Live-run entry: a minimal way to run the Searcher against the live stack — e.g. a
   subcommand `python -m isj_agent.cli search "<intent text>"` (or a small documented
   script) that: reads config.toml; builds the LLM client via build_client([llm.default])
   and the engine via build_search_engine([cottontail_http_json_server]); constructs the B2
   Searcher with both; runs Searcher.run(intent) on the supplied intent; and pretty-prints
   the returned RankedList. (The full multi-intent orchestrator is C3; this is just enough
   to exercise one intent end-to-end live.)

4. Error mapping: every failure path raises EngineError — non-2xx responses (carrying the
   server's message) and httpx transport errors (connect refused, timeout, etc.). The
   message must be informative enough that B2's controller can feed it back to the model.

## The LIVE end-to-end run (full real-LLM loop) — the point of this task

We want to catch integration problems NOW, with a real model and a real burrow (like the
protocol scout did), not later. The live e2e:
- Prereqs (operator-provided; external services -> obtain explicit go-ahead before running):
  * vLLM: gpt-oss-120b served at http://127.0.0.1:8000 as `gpt.oss.120b`
    (--enable-auto-tool-choice --tool-call-parser openai).
  * The C++ stack BUILT with A0/A1/A2 (cover_search in the isj profile), and
    `cottontail-jsonl-server` run over `Scrapheap/climbmix-1000-utf8-porter.burrow`
    (in-repo; --stem porter, so word* works) on a loopback port (e.g. 8081).
  * config.toml: [llm.default] -> the vLLM endpoint/model; [cottontail_http_json_server]
    base_url -> the running server.
- Run the live-run entry (step 3) on a sample intent and CONFIRM: a cover_search with a
  word* query returns parsed results; the Searcher loop runs (search -> judge -> reformulate
  -> stop); exclude_docids accumulates across turns; an invalid query surfaces as an
  EngineError the controller bounces on; run() returns a non-empty RankedList. Capture the
  transcript in the task notes.

## Non-goals

- No RRF, no multi-intent orchestrator (C2/C3): one intent end-to-end.
- No server-side or C++ changes (A owns the server); no new tools.
- Automated tests do NOT touch the network — they use httpx.MockTransport. The live e2e is
  a manual, go-ahead-gated run.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 isj_agent/engine/http.py defines HttpSearchEngine using httpx and implementing the B1 SearchEngine Protocol (search + read); isinstance(HttpSearchEngine(...), SearchEngine) is True; the constructor accepts an injectable client for tests.
- [ ] #2 search() POSTs to base_url + /tools/cover_search with JSON {query, top_k, exclude_docids, window}, sends an Authorization: Bearer header iff a token is configured, and parses a 200 response via SearchResponse.model_validate.
- [ ] #3 read() POSTs to /tools/get_document with {docid} and returns the body text when found is true, or None when found is false.
- [ ] #4 Every failure raises EngineError: a non-2xx response raises EngineError carrying the server's error message (a 400 invalid-GCL response yields a message the B2 controller can bounce on); an httpx transport error (connect refused / timeout) raises EngineError.
- [ ] #5 config.toml and config.example.toml gain a [cottontail_http_json_server] section (base_url; optional api_key_env); config.py gains build_search_engine(cfg) -> HttpSearchEngine reading the bearer token from the env var named by api_key_env (raising if set-but-missing) and never logging it.
- [ ] #6 A live-run entry (a python -m isj_agent.cli search subcommand or documented script) builds the LLM client (build_client) and HttpSearchEngine (build_search_engine) from config.toml, constructs the B2 Searcher, runs run(intent) on a supplied intent, and prints the RankedList.
- [ ] #7 httpx is added as a direct dependency in isj/pyproject.toml and uv sync --project isj succeeds.
- [ ] #8 Automated tests use httpx.MockTransport (no network) and cover: request path/body and the Authorization header for search; SearchResponse parsing; read found vs None; non-2xx -> EngineError(message); transport error -> EngineError; Protocol conformance.
- [ ] #9 uv run --directory isj pytest tests/ exits 0 and no automated test contacts a network or a real model.
- [ ] #10 The full real-LLM live-loop e2e is documented (build the stack; run cottontail-jsonl-server over Scrapheap/climbmix-1000-utf8-porter.burrow on loopback; point config.toml at vLLM gpt-oss-120b and the server) and, run with operator go-ahead, the Searcher completes a real loop (cover_search with word*, exclude_docids accumulation, an EngineError bounce) and returns a RankedList; the transcript is captured in the task notes.
- [ ] #11 isj/README.md documents HttpSearchEngine, the [cottontail_http_json_server] config, the live search command, and that external services (server + vLLM) require explicit go-ahead to run.
- [ ] #12 The JSON server is being MODIFIED by A0/A1/A2 (they add cover_search + the isj profile). B1's SearchResponse is the Python MIRROR of the cover_search JSON the A-built server actually emits (advertised by GET /describe); if the server's real shape differs from B1's types or the MockTransport fixtures, reconcile B1/C1 to match the server rather than inventing a shape.
- [ ] #13 C1's live e2e can only run once A0/A1/A2 (and B2) are built and the server is running; it is the integration gate that catches any mismatch between the Python mirror (B1 types, C1 fixtures) and the server's real cover_search request/response.
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Python in isj/. Depends on B1, B2, A0/A1/A2. Adapt as needed.

1. uv add httpx to isj/pyproject.toml (direct dep); uv sync --project isj. Read
   isj_agent/config.py (build_client pattern), isj_agent/engine/base.py (SearchEngine +
   EngineError), isj_agent/protocol/search.py (SearchResponse), isj_agent/agents/searcher.py
   (B2), and apps/cottontail-jsonl-server.cc (endpoints/auth) for the contract.
2. isj_agent/engine/http.py: HttpSearchEngine as sketched (httpx.Client, base_url, optional
   Bearer header, injectable client; search -> /tools/cover_search -> SearchResponse;
   read -> /tools/get_document -> str|None; _server_error helper; all failures -> EngineError).
3. config: add the [cottontail_http_json_server] section to config.toml and
   config.example.toml; add build_search_engine(cfg) to config.py (token from api_key_env
   env var, never logged).
4. Live-run entry in isj_agent/cli.py: a `search "<intent>"` subcommand that wires
   build_client + build_search_engine + the Searcher and prints run(intent)'s RankedList.
5. isj/tests/test_http_engine.py (NO network): build httpx.Client(transport=httpx.MockTransport(handler))
   and inject it. Assert: search posts to /tools/cover_search with body {query,top_k,
   exclude_docids,window} and an Authorization: Bearer header iff a token is set; a canned
   cover_search JSON parses into SearchResponse; read posts {docid} and returns text when
   found else None; a 400 response -> EngineError carrying the server message; a transport
   error (handler raises httpx.ConnectError) -> EngineError; isinstance(engine, SearchEngine).
6. uv run --directory isj pytest tests/ -v (green; no network). Update isj/README.md:
   HttpSearchEngine, the [cottontail_http_json_server] config, the live `search` command,
   and the external-services go-ahead note.
7. LIVE e2e (after the C++ stack + B2 exist, and with operator go-ahead): build the stack,
   run the server over Scrapheap/climbmix-1000-utf8-porter.burrow on loopback, point
   config.toml at the vLLM + the server, run `python -m isj_agent.cli search "<intent>"`,
   and capture the transcript + RankedList in the task notes; debug any contract mismatches
   surfaced (this is the integration gate).
<!-- SECTION:PLAN:END -->
