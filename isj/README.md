# isj — Agentic ISJ Investigation Planner

This is the implementation of the agentic ISJ (Interactive Searching and
Judging) system described in
[`docs/agentic-isj-investigation-planner.md`](../docs/agentic-isj-investigation-planner.md).
Read that document first — it is the authoritative specification.

This is a TREC RAG 2026 primary-system deliverable, not an example or demo.

## Project layout

```
isj/
  config.example.toml   Reference config — copy to config.toml and edit
  config.toml           Your local config (git-ignored)
  isj_agent/            Importable Python package
    agents/             LLM-role wrappers (Analyst, …) with bundled prompts
    protocol/           Typed artifacts (Intents; search/engine contract types)
    engine/             The SearchEngine contract (Protocol + EngineError) and
                        the scripted FakeEngine; docno_map / fetch helpers
    config.py           load_class() and build_client() utilities
    cli.py              Entry point
    orchestrator.py     Orchestrator (stub)
  tests/                pytest suite
```

## Prerequisites

- **uv** — Python package manager. Install from https://docs.astral.sh/uv/
- **A running vLLM instance** — the CLI talks to a vLLM OpenAI-compatible
  endpoint. For local use, the default is `http://127.0.0.1:8000/v1`.

## Setup

**1. Install dependencies** (from the repo root):

```sh
uv sync --project isj
```

**2. Create your config file:**

```sh
cp isj/config.example.toml isj/config.toml
```

Edit `isj/config.toml` to match your vLLM instance:

```toml
[llm.default]
base_url = "http://127.0.0.1:8000/v1"
model = "gpt.oss.120b"        # must match --served-model-name on your vLLM instance
# api_key_env = "MY_API_KEY"  # omit for unauthenticated local endpoints
```

**3. Set your API key** (if your vLLM endpoint requires one):

```sh
export MY_API_KEY="your-key-here"
```

If `api_key_env` is not set in `config.toml`, the key defaults to `"EMPTY"`,
which works for unauthenticated local vLLM instances.

## Running the CLI

The CLI runs the Analyst over a set of questions and pretty-prints, for each,
the question and the Analyst's ordered interpretations of what the user is
asking for. From the repo root:

```sh
# Analyze the built-in sample questions:
uv run --directory isj python -m isj_agent.cli

# Or analyze your own questions:
uv run --directory isj python -m isj_agent.cli "your question" "another question"
```

`config.toml` (the CLI's default config path) selects the LLM endpoint and the
Analyst implementation. Output for each question looks like:

```
Q: <the question>
  1. <most likely interpretation>
  2. <an alternate interpretation>
```

## Running tests

```sh
# From the repo root:
uv run --directory isj pytest tests/ -v

# Or from inside isj/:
uv run pytest tests/ -v
```

## Engine contract (the Searcher's boundary)

The Searcher (B2) talks to "an engine" through a small typed contract, defined in
`isj_agent/engine/base.py` and `isj_agent/protocol/search.py`. It is **cp-native**
(decision doc-6): a document's working identity is its integer `cp` (the `:item`
container start address); `docno` never enters the agent.

- **`SearchEngine` (a `runtime_checkable` `typing.Protocol`)** — two methods that
  mirror the C++ server's tools:
  - `search(query, *, top_k=10, exclude=(), window=75) -> SearchResponse`
    (`cover_search`); `exclude` is the judged set as **cp integers** (the engine
    is stateless — the agent passes its whole judged set each call).
  - `read(cp) -> str | None` (`get_document`). It is **intentionally part of the
    contract for future use** — a possible agent read-tool and the downstream RAG
    grounding / Writer step — even though the B2 MVP does not call it; do not
    remove it as unused.
  - There is **no `judge` method**: judging is the controller's job in B2; the
    engine only searches and reads.
- **`EngineError`** — `search()`/`read()` MAY raise it on any engine-side failure
  (an invalid query the engine rejects is one cause). There is **no Python-side
  query validation** — the engine is the source of truth; B2's controller feeds
  `str(error)` back to the model so it can self-correct.
- **Types** (`protocol/search.py`, pydantic v2, mirroring the enriched
  `cover_search` response): `SearchResponse{total_matches, unjudged_matches,
  atom_counts:[{term,count}], results:[{rank,score,cp,summary}]}` and
  `Judgement{cp, grade, reason}` with **grade on the 0–4 UMBRELA scale**
  (out-of-range raises `ValidationError`). `SearchResponse` is
  `ConfigDict(extra="forbid")` so an unexpected server field fails loudly (catches
  contract drift). The models round-trip losslessly
  (`model_validate(x.model_dump()) == x`) and emit JSON Schema for the LLM
  boundary (`Judgement.model_json_schema()`), the same single-source-of-truth
  pattern as `Intents`.
- **`FakeEngine`** (`engine/fake.py`) — a deterministic, scripted `SearchEngine`
  driven by an ordered list of `SearchResponse | EngineError`. **B2's tests run
  against `FakeEngine`** (no network, no LLM, no C++).
- **`HttpSearchEngine`** (`engine/http.py`, C1) — the live engine: an `httpx`
  client that implements the same Protocol against a running
  `cottontail-jsonl-server`, POSTing `/tools/cover_search` and `/tools/get_document`
  and parsing the JSON into `SearchResponse`. Every failure (a non-2xx response —
  carrying the server's error message — or an httpx transport error) maps to
  `EngineError`, so the B2 controller can bounce a bad query back to the model.
  Configured by `[cottontail_http_json_server]` (`base_url`; optional `api_key_env`
  naming the bearer-token env var, read but never logged) and built by
  `config.build_search_engine(cfg)`. C3 wires it into the Searcher for live runs.

  **Live connectivity check.** Automated tests use `httpx.MockTransport` (no
  network). The live check is a pytest case **skipped unless `COTTONTAIL_SERVER_URL`
  is set**. To run it (the server is a **local** loopback service — fine to run;
  external services would need explicit go-ahead), from the repo root:
  ```sh
  bazel-bin/apps/cottontail-jsonl-server --burrow my-stemmed.burrow --port 8080 &
  COTTONTAIL_SERVER_URL=http://127.0.0.1:8080 uv run --project isj pytest \
      tests/test_http_engine.py::test_live_cover_search_round_trip
  ```
  (a `word*` query needs a `--stem porter` burrow; a loopback server runs without
  auth). The full real-LLM Searcher-loop run is C3's CLI, not C1.

## The Searcher (B2)

`isj_agent/agents/searcher.py` plays one human "interactive searcher" as a
guardrailed LLM loop. `Searcher(client, model, engine).run(intent)` returns a
`SearcherResult` = a per-intent `RankedList` (judged, graded passages, best-first)
plus a structured event **trace**. Its prompt is bundled in `searcher.md` (mirroring
the `Analyst`).

- **Two LLM tools, one tool call per turn:** `search` (the model writes only a GCL
  cover `query`; the controller injects `exclude` = the accumulated judged set plus
  `top_k`/`window`) and `judge` (a batch of `{cp, grade 0-4, reason}`; its argument
  schema is derived from the B1 `Judgement` model so grades are guided to 0-4).
  There is **no `read` and no `finish` tool**; `read()` stays on the engine Protocol
  as documented future-proofing (RAG grounding), not exposed to the model.
- **The controller owns the guardrails and termination** (model behavior is not
  portable — see `docs/searcher-agent-lessons-June-16-2026.md`): judge-before-search
  (a search with unjudged passages is refused), engine-delegated errors
  (`EngineError` is bounced back as `str(error)`; there is no Python GCL validator),
  and judge-argument validation through `Judgement` (an out-of-range grade is bounced
  with the pydantic error). Only **surfaced + unjudged** cps are recorded
  (hallucinated cps ignored), each pulling its summary/score from the surfaced hit.
- **Recall-first stopping:** there is **no hard search budget**. The agent keeps
  reformulating until it exhausts new material — the model stops (no tool call), or
  ≥3 consecutive dry searches, or ≥3 consecutive no-progress turns — with a generous
  `max_turns` cap (default 150) as the only runaway backstop (every turn, including
  bounces, counts toward it). All of these are constructor knobs the eval harness /
  C3 can tune.
- **The trace is a research artifact** (`SearcherResult.events`, a `list[TraceEvent]`):
  detailed, timestamped events — `llm_turn` (LLM latency, which tool, emitted
  tool-call count), `search` (the query + the excluded cps + counts + atom_counts +
  every returned hit with its cp/score/summary + engine latency), `judge` (each
  recorded `{cp, grade, reason}`), `bounce` (kind + message), `stop` (reason) — so
  the agent's behavior can be reconstructed and measured. C2 rewrites the cps to
  docnos when persisting it.

Tested with a stub LLM (scripted tool-call turns) + the B1 `FakeEngine` — no network,
no real model. A live real-model run is the C3 integration gate.

## Status

The `Analyst` is implemented: `analyze()` makes a single guided-decoding LLM
call and returns an `Intents` object. The engine contract (B1) is implemented:
the `SearchEngine` Protocol, `EngineError`, the typed `SearchResponse`/`Judgement`,
and the scripted `FakeEngine`. The `Searcher` (B2) above is implemented (loop
controller, guardrails, recall-first termination, structured trace), tested against
the `FakeEngine`. Still to come: `HttpSearchEngine` (C1), the run-output writer
(C2), and the `Orchestrator` / CLI (C3). The richer INP / CM / IP pipeline from the
design spec is shelved in favor of the simpler `Intents` output (see the agent
design decision docs under `backlog/docs/`).
