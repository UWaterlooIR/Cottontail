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
    config.py           load_class / build_client / build_search_engine /
                        build_docno_map utilities
    cli.py              CLI entry point (one question -> a run-output dir)
    orchestrator.py     Orchestrator: Analyst -> per-intent Searcher
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

## Running the CLI (C3)

The CLI (`isj_agent/cli.py`) runs the whole pipeline on **one question** and
writes a run-output directory: it analyzes the question into interpretations
(Analyst), runs the Searcher per interpretation over the live
`HttpSearchEngine`, and persists the result with `write_run` (C2). A single
flag-based entry, no subcommands:

```sh
uv run --directory isj python -m isj_agent.cli \
    --question "What should I know about black bear attacks while hiking?" \
    --out runs/bear --verbose
```

| Flag | Meaning |
|---|---|
| `--question` (required) | the question to investigate |
| `--out` (required) | run-output directory to write |
| `--overwrite` | overwrite a non-empty `--out` |
| `--verbose` | render each interpretation's events live as they happen |
| `--burrow` | override the served burrow (locates the cp↔docno map) |
| `--config` | path to `config.toml` (default `isj/config.toml`) |

It needs **both** a running vLLM (the `[llm.*]` endpoint) and a running
`cottontail-jsonl-server` over a `--stem porter` burrow (the
`[cottontail_http_json_server]` endpoint) — see
[`docs/running-the-search-stack.md`](../docs/running-the-search-stack.md) for
starting the server. The server is a **local** loopback service (fine to run); an
off-loopback or external endpoint needs explicit go-ahead.

The output directory is exactly the C2 layout below. On disk the persisted ids
are **docnos**, rewritten from cps via the read-only map at
`<burrow>/docno-cp.sqlite` — `burrow` comes from `[cottontail_http_json_server]`
(or `--burrow`); a corpus with no map persists raw cps. The CLI prints a one-line
summary (`interpretations` / `succeeded` / `failed`) and **exits non-zero iff
`errors.log` was written** (the same success signal as its absence in the output
dir).

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
  tool-call count), `search_request` (**the query logged going out**, emitted
  *before* the engine call: query + top_k + window + excluded cps — so a request is
  on record even if the engine/server dies mid-call), `search` (**the response**:
  counts + atom_counts + every returned hit with its cp/score/summary + engine
  latency), `judge` (each recorded `{cp, grade, reason}`), `bounce` (kind + message;
  an `engine_error` bounce also carries the failing `query`), `stop` (reason) — so
  the agent's behavior can be reconstructed and measured. C2 rewrites the cps to
  docnos when persisting it.

Tested with a stub LLM (scripted tool-call turns) + the B1 `FakeEngine` — no network,
no real model. A live real-model run is the C3 integration gate.

## Run output (C2)

`isj_agent/run_output.py` persists one question's run to a directory (`write_run`).
C3 produces the data and catches errors; C2 only writes:

```
<out_dir>/
  intents.json            the Intents (question + ordered interpretations)
  intent-00.json          interpretations[0]'s RankedList (only if it succeeded)
  intent-00.trace.jsonl   interpretations[0]'s event trace, one TraceEvent per line
  intent-01.json
  intent-01.trace.jsonl
  ...
  errors.log              present ONLY if something failed
```

- `intent-NN` is the zero-based, zero-padded interpretation index; `intent-NN.trace.jsonl`
  is a **JSON-Lines** event log (one `TraceEvent` per line) — a research artifact.
- **The absence of `errors.log` means the whole run succeeded.** Its presence lists each
  failure, tagged with the failing intent's index/interpretation; a failed intent gets no
  `.json`/`.trace.jsonl`.
- **docno on disk.** Results are `cp` in memory but the writer rewrites every persisted `cp`
  to its `docno` via the read-only `DocnoMap` (TASK-6.3) — in the `RankedList` *and* the
  trace events — so the saved files are portable (the field is renamed `cp` → `docno`). A
  docno-less corpus (no map) persists cps. Pure filesystem: no network, no LLM.

## The Orchestrator (C3)

`isj_agent/orchestrator.py` drives one question end to end.
`Orchestrator(analyst=…, searcher=…).run_question(question, *, on_intent=None)`
calls `Analyst.analyze`, then runs the `Searcher` per interpretation in order,
and returns `(intents, outcomes, run_error)` — one `outcome` per interpretation
(a `SearcherResult` on success, a `RunError` on a per-intent failure; the run
continues past a failed intent). An analysis-level failure returns
`(None, [], <message>)`. It writes no files (the CLI calls `write_run`) and does
no fusion; `on_intent(i, interp, outcome)` is the hook the CLI's `--verbose` uses
to render each interpretation as it completes. The CLI (above) is the thin wiring
layer that builds the agents from config and feeds the 3-tuple straight into
`write_run`.

## Status

The full Searcher pipeline is implemented and tested. The `Analyst` makes a
single guided-decoding LLM call returning an `Intents`. The engine contract (B1)
— the `SearchEngine` Protocol, `EngineError`, the typed
`SearchResponse`/`Judgement`, and the scripted `FakeEngine` — backs the `Searcher`
(B2). The live `HttpSearchEngine` (C1, validated against a real server), the
run-output writer (C2), and the `Orchestrator` + CLI (C3) that wire Analyst →
per-intent Searcher (over `HttpSearchEngine`) → `write_run` are all in place; the
CLI is the full real-LLM live gate. The richer INP / CM / IP pipeline from the
design spec is shelved in favor of the simpler `Intents` output (see the agent
design decision docs under `backlog/docs/`). Still to come: retiring the old
`examples/agent/` demo (TASK-5.4) and the user-facing docs pass (TASK-5.10).
