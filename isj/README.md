# isj — Agentic ISJ Investigation Planner

This is the implementation of the agentic ISJ (Interactive Searching and
Judging) system described in
[`docs/design/archive/agentic-isj-investigation-planner.md`](../docs/design/archive/agentic-isj-investigation-planner.md).
Read that document first — it is the authoritative specification.

This is a TREC RAG 2026 primary-system deliverable, not an example or demo.

## Project layout

```
isj/
  config.example.toml   Reference config — copy to config.toml and edit
  config.toml           Your local config (git-ignored)
  isj_agent/            Importable Python package
    agents/             LLM-role wrappers + prompts: analyst, searcher (cover),
                        tiered_searcher, mt_tiered_searcher, lucindri_searcher,
                        judger, search_coach (TASK-40)
    protocol/           Typed artifacts: intents, results, search, queryable
    engine/             SearchEngine contract (base) + implementations: http,
                        lucindri, multishard, and the scripted fake
    config.py           load_class / build_client / build_analyst / build_engine /
                        build_coach / resolve_context_limit
    analysis.py         Analysis artifact: write_report / load_report (TASK-41)
    analyze.py          `python -m isj_agent.analyze`: Analyst over a topics TSV
                        -> reusable per-topic analysis artifacts (TASK-41)
    controller.py       Per-intent search/judge/coach loop + context compaction
    orchestrator.py     Orchestrator: Analyst -> per-intent Controller
    run_output.py       StreamingRunWriter (live activity.log) + write_run
    cli.py              CLI entry point (one question/analysis -> a run-output dir)
    docno_map.py, fetch.py, index.py   cp<->docno map, doc fetch, index helpers
  scripts/traceview.py  human-readable *.trace.jsonl viewer (TASK-39)
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

The CLI (`isj_agent/cli.py`) runs the whole pipeline on **one question** (or a
precomputed `--analysis-file`) and writes a run-output directory: it analyzes the
question into interpretations (Analyst), runs the per-intent Controller (Searcher +
parallel Judger + SearchCoach) over the configured engine, and **streams** results to
the directory as the run proceeds (`StreamingRunWriter` — `tail -f activity.log` to
watch it live). A single flag-based entry, no subcommands:

```sh
uv run --directory isj python -m isj_agent.cli \
    --question "What should I know about black bear attacks while hiking?" \
    --out runs/bear --verbose
```

| Flag | Meaning |
|---|---|
| `--question` \| `--analysis-file` (one required) | the question to investigate (runs the Analyst), **or** a precomputed analysis artifact JSON that supplies the question + interpretations and **skips the Analyst** (see below) |
| `--out` (required) | run-output directory to write |
| `--overwrite` | overwrite a non-empty `--out` |
| `--verbose` | render each interpretation's events live as they happen |
| `--burrow` | override the served burrow (locates the cp↔docno map) |
| `--config` | path to `config.toml` (default `isj/config.toml`) |

### Reusable analysis artifacts (`isj analyze` → `--analysis-file`, TASK-41)

The Analyst output is a first-class, reusable artifact so **one analysis per topic drives every
searcher-agent run**, factoring analyst variation out of cross-searcher comparisons. Run the
configured Analyst (`[agents.analyst]`) over a topics TSV once — vLLM only, no server needed:

```sh
uv run --directory isj python -m isj_agent.analyze \
    --topics topics.dev.tsv --out analysis/dev      # writes <out>/<topic_id>.json + analysis.meta.json
```

Each `<topic_id>.json` is
`{topic_id, question, interpretations[], analyst{class,model,reasoning_effort,temperature}}`.
Feed one to a run via `--analysis-file <topic_id>.json` (instead of `--question`) and the
Orchestrator uses its interpretations directly — the Analyst is never built or called. `analyze`
is resumable (skips a topic whose `<id>.json` exists unless `--overwrite`) and takes `--only <id>`
(repeatable), `--limit N`, and `--config`. The artifact shape is **analyst-agnostic**: point
`[agents.analyst].class` at a different analyst and only the contents change. Two ship today —
the default `Analyst` (disambiguated interpretations) and `ReportAnalyst`
(`agents.report_analyst.ReportAnalyst`, TASK-42) which decomposes the need into the information
**components** a RAG report must synthesize. Helpers live in `isj_agent/analysis.py`
(`write_report`/`load_report`); the run guide has the end-to-end flow.

It needs **both** a running vLLM (the `[llm.*]` endpoint) and the configured search
engine (the `[engine]` section) — for the default Cottontail engine, a running
`cottontail-jsonl-server` over a `--stem porter` burrow — see
[`docs/design/reference-specs/running-the-search-stack.md`](../docs/design/reference-specs/running-the-search-stack.md) for
starting the server. The server is a **local** loopback service (fine to run); an
off-loopback or external endpoint needs explicit go-ahead.

The output directory is the C2 layout below. On disk the persisted ids are
**docnos** — the engine translates `cp`→`docno` at its boundary via the read-only map
at `<burrow>/docno-cp.sqlite` (`burrow` from the engine config or `--burrow`); a corpus
with no map persists raw cps. The CLI prints a one-line summary (`interpretations` /
`succeeded` / `failed`) and **exits non-zero iff `errors.log` was written** (the same
success signal as its absence in the output dir).

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
  Configured by the `[engine]` section (`base_url`; optional `api_key_env`
  naming the bearer-token env var, read but never logged) and built by
  `config.build_search_engine(cfg)`. C3 wires it into the Searcher for live runs.
- **The engine is config-selected** — the CLI calls `config.build_engine(config)` and
  constructs exactly the one class named by `[engine]`. Besides `HttpSearchEngine`, the same
  Protocol is met by **`LucindriSearchEngine`** (`engine/lucindri.py`, TASK-33 — an
  Indri-variant HTTP service, docno-native) and **`MultiShardSearchEngine`**
  (`engine/multishard.py`, TASK-34 — parallel fan-out over N single-burrow Cottontail
  servers, merged by score into the true global top-k). Each is health-checked on startup
  (fail fast). Swapping engines is a config change, not a code change.

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

### The four interchangeable Searchers

`BaseSearcher` (in `agents/searcher.py`) is generic over a list of `Queryable`
query types (TASK-18); a concrete searcher just picks its prompt + query type
and is selected via `[agents.searcher].class` in `config.toml` — no controller
or base changes:

| class | tool | emits per turn |
|---|---|---|
| `agents.searcher.Searcher` (default) | `cover_search` | one GCL cover query |
| `agents.tiered_searcher.TieredSearcher` (TASK-20) | `tiered_query_search` | a JSON list of GCL tiers, precise→broad |
| `agents.mt_tiered_searcher.MultiTextTieredSearcher` (TASK-22) | `submit_tiered_query` | a **MultiText DSL program** (macros + `@rank`), compiled server-side; compile diagnostics bounce back for self-correction |
| `agents.lucindri_searcher.LucindriSearcher` (TASK-33) | `submit_query` | one **Indri-style** query; runs over the Lucindri engine (`[engine]` → `LucindriSearchEngine`), not Cottontail |

The two tiered searchers run the same server-side cascade; they differ only in
how the model authors the tiers. The four searchers are engine-aware only through
config: the three GCL/MultiText searchers pair with a Cottontail engine (`HttpSearchEngine`
or `MultiShardSearchEngine`), the Lucindri searcher with `LucindriSearchEngine`.
**Keep `reasoning_effort = "medium"` for the tiered/MultiText searchers** — at `"high"`,
gpt-oss-120b falls into pathological reasoning loops (validated in
`scouting/multitext-dsl*/captured/FINDINGS.md`).

### Searcher — `agents/searcher.py` + `searcher.md`
A thin query author (like the `Analyst`). `Searcher(client, model).propose(messages)`
makes one LLM round-trip offering a **single `search` tool** with
`tool_choice="required"`, and returns the chosen GCL `query` plus the assistant
message to append. There is **no judge tool and no relevance scale** — the Searcher
only writes queries. `reasoning_effort` defaults to `"medium"` (forwarded via
`extra_body`; every agent takes it and it is config-overridable). It sees each
query's judged outcome as the `search` tool result, so
its conversation *is* its history.

### Judger — `agents/judger.py` + `judger.md`
Pointwise full-document judging. `Judger(client, model, *, concurrency=15,
reasoning_effort="medium").judge(intent, docs)` grades each `(summary, full document)`
in its own LLM call — guided-decoded to `Verdict{reason, grade 0-3}` — running a wave
of up to `concurrency` calls in parallel over a `ThreadPoolExecutor`. The **cp is
never sent to the model**; the controller pairs each verdict (returned in input
order) with the cp it asked about. `judger.md` is a decomposed, trust-aware UMBRELA
prompt (intent → topical match → trust → scope → grade) for open-web ClimbMix text.
A failed call (LLM error or an
unvalidatable completion) is retried up to 2 more times inside the Judger; if it
still fails it surfaces as data (`JudgeCall.error` aggregating every attempt,
`verdict=None`, `retries`), and the controller records the doc with the **grade
`-2` error sentinel** ("Judger agent failed to assess the relevance.") rather
than aborting — the doc consumes budget, is never re-judged, and the Searcher
sees the outcome. `-2` neither advances nor resets the non-relevant streak. Only
a wave where EVERY call failed aborts the intent (an outage, not a hiccup). The
`-2` is constructed controller-side; the model-facing Verdict schema stays 0–3.

### SearchCoach — `agents/search_coach.py` + `search_coach.md` (TASK-40)

Between judging one query and the Searcher's next reformulation sits a pluggable
**coach**: given the query, the judged results, and coverage stats, it produces the
feedback string the Searcher sees. `SearchCoach` is a `Protocol` with two implementations,
selected by `[coach].class`:

| class | kind | behavior |
|---|---|---|
| `MechanicalSearchCoach` (default) | no LLM (`is_llm=False`) | deterministic digest: top results by grade, aggregate counts — the historical feedback |
| `SearchCoachAgent` (TASK-40.2) | LLM (`is_llm=True`) | a free-text coaching report from a distinct `[coach].llm` profile + prompt |

`config.build_coach` returns a **`(coach, mechanical_fallback)`** pair: the mechanical
coach is always built, both as the default and as the fallback the Controller drops to if
an LLM coach raises. Config lives in `[coach]` / `[coach.mechanical]` (`config.example.toml`).

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
- **Coaching (TASK-40).** After each judged query the Controller asks the configured
  `SearchCoach` for the feedback the Searcher sees next (query echo + the coach's report +
  coverage/atom stats). If an LLM coach raises, it silently drops to the mechanical fallback
  (a `coach_fallback` event). A **0-result query skips the coach** and returns fixed
  over-constrained guidance.
- **Context compaction (TASK-40.3).** When the Searcher conversation nears its model's
  `context_limit` (at `compact_trigger`, default 0.80), the Controller shrinks older
  messages in place (truncating to `shrink_truncate_tokens`) so a long loop can't overflow
  the context. Disabled (no-op) when the limit is unknown.
- **Error routing.** A malformed query (`EngineError`) or a zero-result query bounces
  straight back to the Searcher as the tool result. A single judge failure is **recorded as
  a grade `-2`** (above) and the loop continues; only a **wave where *every* judge call
  fails** aborts the intent with a partial `SearcherResult` (`.error` set; docs judged
  before the abort are retained). A caught mid-loop Searcher LLM failure also aborts.
- **Heavy trace** (`list[TraceEvent]`): `llm_call` (per Searcher turn, per judge call, AND
  per LLM-coach call with `purpose="coach"` — verbatim `request`, incl. the full document
  for judges, plus usage), `propose` (the chosen query), `search_request` / `search` (the
  page + counts + atom_counts + hits), `judge` (`{cp, grade, reason}`), `judge_failed`,
  `revisit` (`{cp, grade}`, counted not re-judged), `coach_fallback`, `list_exhausted`
  (`{query, depth, streak}`), `bounce` (`engine_error` / `no_query`), `stop`
  (`intent_budget` / `max_queries`), and `error`. The CLI's streaming writer also renders
  live `LiveMarker`s (`await_searcher_turn` / `await_judge` / `await_coach`) so a hung call
  is visible in `activity.log`.

All three are tested with stub LLMs + the `FakeEngine` (no network, no real model);
the CLI is the live real-model gate.

## Run output (C2)

`isj_agent/run_output.py` persists one question's run to a directory. The CLI uses the
**`StreamingRunWriter`** (TASK-35), which writes **incrementally as the run proceeds** so a
run is observable live and a killed/hung run still leaves a partial, inspectable directory.
(A batch `write_run(out, intents, outcomes, run_error)` also exists — same layout, written
all-at-once at the end — and is what the unit tests use.)

```
<out_dir>/
  activity.log            human-readable stream of EVERY event + live marker (tail -f this)
  intents.json            the Intents (question + ordered interpretations), at start
  intent-00.json          interpretations[0]'s RankedList (only if it succeeded)
  intent-00.trace.jsonl   interpretations[0]'s event trace, one TraceEvent per line
  intent-01.json
  intent-01.trace.jsonl
  ...
  errors.log              present ONLY if something failed, at finish
```

- `activity.log` is the tail-able live rendering of every event and pre-call `LiveMarker`
  (`--verbose` also mirrors it to stdout). `intent-NN` is the zero-based, zero-padded
  interpretation index; `intent-NN.trace.jsonl` is a **JSON-Lines** event log (one
  `TraceEvent` per line) — a research artifact, viewable with `scripts/traceview.py`.
- **The absence of `errors.log` means the whole run succeeded.** Its presence lists each
  failure, tagged with the failing intent's index/interpretation. A *run-level* failure
  (no `SearcherResult` at all — e.g. the Analyst raised) gets no `.json`/`.trace.jsonl`; a
  *partial* result (the controller caught a mid-loop Searcher/Judge failure) keeps its
  `.json`/`.trace.jsonl` **and** is listed in `errors.log`.
- **docno on disk.** The **engine** translates `cp`→`docno` at its boundary (Option B, doc-8),
  so results already carry docnos by the time they reach the writer; the writer only renames
  the JSON field `id` → `docno`. A docno-less corpus (no map) surfaces raw cps. Pure
  filesystem: no network, no LLM.

## The Orchestrator (C3)

`isj_agent/orchestrator.py` drives one question end to end.
`Orchestrator(analyst, controller, *, max_judgments=1000).run_question(question, *,
intents=None, on_analyzed=None, observer=None, on_intent=None)` calls `Analyst.analyze` —
**unless** a precomputed `intents` is supplied (from an `--analysis-file` artifact, TASK-41),
in which case the Analyst is skipped and may be `None`. It splits the **run-total** judgment
budget evenly across interpretations (`intent_budget = max_judgments // num_intents`, ≥1),
then runs the `Controller` per interpretation in order, and returns
`(intents, outcomes, run_error)` — one `outcome` per interpretation (a
`SearcherResult` on success, a `RunError` on a per-intent failure; the run continues
past a failed intent). An analysis-level failure returns `(None, [], <message>)`. It
writes no files and does no fusion; the three callbacks feed the CLI's
`StreamingRunWriter` live — `on_analyzed(intents)` opens the run (writes `intents.json`),
`observer(i, event)` streams each event to `activity.log` (mirrored to stdout under
`--verbose`), and `on_intent(i, interp, outcome)` finalizes each interpretation's files.
The CLI builds the Analyst (from `[agents.analyst]`, unless `--analysis-file` supplies a
precomputed one), Searcher, Judger, **SearchCoach**, **engine**, Controller, and Orchestrator
from config (`[agents.analyst]`, `[agents.searcher]`, `[agents.judger]`, `[coach]`,
`[engine]`, `[loop]`) and streams the run to disk as it goes.

## Status

The full pipeline is implemented and tested. The `Analyst` makes a single
guided-decoding LLM call returning an `Intents` — now also a **reusable per-topic
artifact** (`isj analyze` → `--analysis-file`, TASK-41). The **Searcher/Judger split**
(TASK-16) replaces the old combined search+judge loop: one of **four** query-only
Searchers (cover / tiered / MultiText / Lucindri), a parallel full-document `Judger`
(pointwise 0-3 + trust, with the `-2` failure sentinel — TASK-27), a pluggable
**`SearchCoach`** (mechanical default or LLM — TASK-40) shaping the between-query feedback,
and a `Controller` that owns wave-judging, the grade-0 non-relevant streak, retain-all
recording, de-duplication, context compaction (TASK-40.3), and the run-total judgment
budget split across intents. The engine contract — the `SearchEngine` Protocol,
`EngineError`, the typed `SearchResponse`/`Verdict`, and the scripted `FakeEngine` — backs
them, with **config-selected** live engines: `HttpSearchEngine`, `LucindriSearchEngine`
(TASK-33), and `MultiShardSearchEngine` (TASK-34). The `Orchestrator` + CLI wire Analyst →
per-intent Controller (over the configured engine) → the streaming `StreamingRunWriter`
(TASK-35, live `activity.log`); the CLI is the full real-LLM live gate. Every agent bounds
its generation (`max_tokens` + `timeout_s`, TASK-37) and defaults to `reasoning_effort =
"medium"` and `temperature = 0.0` (TASK-38). The earlier proof-of-concept agent is archived
under `archive/example-agent/`, and the full run/usage flow lives in
[`docs/design/reference-specs/running-the-search-stack.md`](../docs/design/reference-specs/running-the-search-stack.md).
