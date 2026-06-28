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
    agents/             LLM-role wrappers (Analyst, Searcher, Judger) with prompts
    protocol/           Typed artifacts (Intents; search/engine contract types)
    engine/             The SearchEngine contract (Protocol + EngineError) and
                        the scripted FakeEngine; docno_map / fetch helpers
    config.py           load_class / build_client / build_search_engine /
                        build_docno_map utilities
    controller.py       Per-intent search/judge loop (Searcher + Judger)
    cli.py              CLI entry point (one question -> a run-output dir)
    orchestrator.py     Orchestrator: Analyst -> per-intent Controller
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
(Analyst), runs the per-intent Controller (Searcher + parallel Judger) over the
live `HttpSearchEngine`, and persists the result with `write_run`. A single
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

The controller talks to "an engine" through a small typed contract, defined in
`isj_agent/engine/base.py` and `isj_agent/protocol/search.py`. It is **cp-native**
(decision doc-6): a document's working identity is its integer `cp` (the `:item`
container start address); `docno` never enters the agents.

- **`SearchEngine` (a `runtime_checkable` `typing.Protocol`)** — two methods that
  mirror the C++ server's tools:
  - `search(query, *, top_k=10, exclude=(), window=75) -> SearchResponse`
    (`cover_search`); `exclude` is the per-query *seen* set as **cp integers** (the
    engine is stateless — the controller passes the set each call).
  - `read(cp) -> str | None` (`get_document`) — the controller calls this to fetch
    each candidate's **full document** for the Judger (truncated to `max_doc_chars`).
  - There is **no `judge` method**: the **Judger** judges by reading the full
    document (`read(cp)`); the engine only searches and reads.
- **`EngineError`** — `search()`/`read()` MAY raise it on any engine-side failure
  (an invalid query the engine rejects is one cause). There is **no Python-side
  query validation** — the engine is the source of truth; the controller feeds
  `str(error)` back to the Searcher so it can self-correct.
- **Types** (`protocol/search.py`, pydantic v2, mirroring the enriched
  `cover_search` response): `SearchResponse{total_matches, unjudged_matches,
  atom_counts:[{term,count}], results:[{rank,score,cp,summary}]}` and the Judger's
  output `Verdict{reason, grade}` — **grade on the canonical UMBRELA/TREC 0–3 scale**
  (`Literal[0,1,2,3]`; out-of-range raises `ValidationError`), `reason` declared
  **before** `grade` (guided decoding fills properties in declaration order), and
  **no `cp`** (the controller pairs each verdict with the cp it asked about).
  `SearchResponse` is `ConfigDict(extra="forbid")` so an unexpected server field
  fails loudly (catches contract drift). The models round-trip losslessly and emit
  JSON Schema for the LLM boundary (`Verdict.model_json_schema()`), the same
  single-source-of-truth pattern as `Intents`.
- **`FakeEngine`** (`engine/fake.py`) — a deterministic, scripted `SearchEngine`
  driven by an ordered list of `SearchResponse | EngineError`. **The controller/judger
  tests run against `FakeEngine`** (no network, no LLM, no C++).
- **`HttpSearchEngine`** (`engine/http.py`, C1) — the live engine: an `httpx`
  client that implements the same Protocol against a running
  `cottontail-jsonl-server`, POSTing `/tools/cover_search` and `/tools/get_document`
  and parsing the JSON into `SearchResponse`. Every failure (a non-2xx response —
  carrying the server's error message — or an httpx transport error) maps to
  `EngineError`, so the controller can bounce a bad query back to the Searcher.
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

## The Searcher / Judger split (TASK-16)

Searching and judging are **two agents** driven by a **controller**. The Searcher
authors queries; the Judger reads full documents and grades them, in parallel; the
controller (not the model) owns paging, the stop rules, the budget, de-duplication,
and the trace. The motivation and full spec are in TASK-16 (`backlog/tasks/`).

### Searcher — `agents/searcher.py` + `searcher.md`
A thin query author (like the `Analyst`). `Searcher(client, model).propose(messages)`
makes one LLM round-trip offering a **single `search` tool** with
`tool_choice="required"`, and returns the chosen GCL `query` plus the assistant
message to append. There is **no judge tool and no relevance scale** — the Searcher
only writes queries. `reasoning_effort` defaults to `"high"` (forwarded via
`extra_body`). It sees each query's judged outcome as the `search` tool result, so
its conversation *is* its history.

### Judger — `agents/judger.py` + `judger.md`
Pointwise full-document judging. `Judger(client, model, *, concurrency=15,
reasoning_effort="high").judge(intent, docs)` grades each `(summary, full document)`
in its own LLM call — guided-decoded to `Verdict{reason, grade 0-3}` — running a wave
of up to `concurrency` calls in parallel over a `ThreadPoolExecutor`. The **cp is
never sent to the model**; the controller pairs each verdict (returned in input
order) with the cp it asked about. `judger.md` is a decomposed, trust-aware UMBRELA
prompt (intent → topical match → trust → scope → grade) for open-web ClimbMix text.
A failed call surfaces as data (`JudgeCall.error`, `verdict=None`).

### Controller — `controller.py`
`Controller(searcher, judger, engine, …).run(intent, intent_budget)` returns the
existing `SearcherResult` = per-intent `RankedList` + a `TraceEvent` trace. Per query:

- **Descend the true ranked list in waves** of `judger.concurrency`. Fetch a large
  batch (`fetch_k`, default 200) with `exclude=seen` (this query's consumed cps, so
  prior-judged docs still appear); judge the **new** docs in each wave in parallel.
- **De-duplication.** A doc judged in any prior query is **counted, not re-judged**
  (no re-read, no Judger call, no new record); its stored grade still drives the
  streak and it rolls into a J/X/Y aggregate. The Searcher sees the **new** docs'
  summaries+grades+reasons plus that aggregate — never the already-judged docs again.
- **Streak + retain-all.** Stop descending after `nonrelevant_streak` (default 5)
  non-relevant docs in rank order — **non-relevant = grade 0** by default
  (`relevant_grade_threshold=1`). The streak only stops *descent*; every judged doc is
  **recorded and reported**, even those past the streak trip within the tripping wave.
- **Budget & backstops.** The intent stops at `intent_budget` (the Orchestrator's even
  split of the run-total `max_judgments`) or the `max_queries` backstop (default 100).
- **Error routing.** A malformed query (`EngineError`) or a zero-result query bounces
  straight back to the Searcher as the tool result. A **judge failure aborts the
  intent** with a partial `SearcherResult` (`.error` set; docs judged before the
  failure are retained). A caught mid-loop Searcher LLM failure does the same.
- **Heavy trace** (`list[TraceEvent]`): `llm_call` (per Searcher turn AND per judge
  call — verbatim `request`, incl. the full document for judges, plus usage), `propose`
  (the chosen query), `search_request` / `search` (the page + counts + atom_counts +
  hits), `judge` (`{cp, grade, reason}`), `revisit` (`{cp, grade}`, counted not
  re-judged), `list_exhausted` (`{query, depth, streak}`), `bounce`
  (`engine_error` / `no_query`), `stop` (`intent_budget` / `max_queries`), and `error`.

All three are tested with stub LLMs + the `FakeEngine` (no network, no real model);
the CLI is the live real-model gate.

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
  failure, tagged with the failing intent's index/interpretation. A *run-level* failure
  (no `SearcherResult` at all — e.g. the Analyst raised) gets no `.json`/`.trace.jsonl`; a
  *partial* result (the controller caught a mid-loop Searcher/Judge failure) keeps its
  `.json`/`.trace.jsonl` **and** is listed in `errors.log`.
- **docno on disk.** Results are `cp` in memory but the writer rewrites every persisted `cp`
  to its `docno` via the read-only `DocnoMap` (TASK-6.3) — in the `RankedList` *and* the
  trace events — so the saved files are portable (the field is renamed `cp` → `docno`). A
  docno-less corpus (no map) persists cps. Pure filesystem: no network, no LLM.

## The Orchestrator (C3)

`isj_agent/orchestrator.py` drives one question end to end.
`Orchestrator(analyst, controller, *, max_judgments=1000).run_question(question, *,
on_intent=None)` calls `Analyst.analyze`, splits the **run-total** judgment budget
evenly across interpretations (`intent_budget = max_judgments // num_intents`, ≥1),
then runs the `Controller` per interpretation in order, and returns
`(intents, outcomes, run_error)` — one `outcome` per interpretation (a
`SearcherResult` on success, a `RunError` on a per-intent failure; the run continues
past a failed intent). An analysis-level failure returns `(None, [], <message>)`. It
writes no files (the CLI calls `write_run`) and does no fusion; `on_intent(i, interp,
outcome)` is the hook the CLI's `--verbose` uses to render each interpretation as it
completes. The CLI builds the Searcher, Judger, Controller, and Orchestrator from
config (`[agents.searcher]`, `[agents.judger]`, `[loop]`) and feeds the 3-tuple
straight into `write_run`.

## Status

The full pipeline is implemented and tested. The `Analyst` makes a single
guided-decoding LLM call returning an `Intents`. The **Searcher/Judger split**
(TASK-16) replaces the old combined search+judge loop: a query-only `Searcher`, a
parallel full-document `Judger` (pointwise 0-3 + trust), and a `Controller` that owns
wave-judging, the grade-0 non-relevant streak, retain-all recording, de-duplication,
and the run-total judgment budget split across intents. The engine contract — the
`SearchEngine` Protocol, `EngineError`, the typed `SearchResponse`/`Verdict`, and the
scripted `FakeEngine` — backs them. The live `HttpSearchEngine` (validated against a
real server), the run-output writer, and the `Orchestrator` + CLI that wire Analyst →
per-intent Controller (over `HttpSearchEngine`) → `write_run` are all in place; the
CLI is the full real-LLM live gate. The judge-serving defaults (`concurrency=15`,
`reasoning_effort="high"`, `max_doc_chars=50000`) come from the `scout_judger.py`
serving scout (decode-bound; KV is not the constraint). The earlier proof-of-concept
agent is archived under `archive/example-agent/`, and the full run/usage flow lives in
[`docs/running-the-search-stack.md`](../docs/running-the-search-stack.md).
