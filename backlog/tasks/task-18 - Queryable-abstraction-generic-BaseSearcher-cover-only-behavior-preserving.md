---
id: TASK-18
title: 'Queryable abstraction + generic BaseSearcher (cover-only, behavior-preserving)'
status: Done
assignee:
  - '@claude'
created_date: '2026-06-30 21:45'
updated_date: '2026-07-01 01:51'
labels: []
dependencies: []
references:
  - docs/design/agent-architecture.txt
priority: high
ordinal: 32000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Realize the `Queryable` seam from `docs/design/agent-architecture.txt`. Today the Searcher↔Controller seam is a bare query string (`ProposeResult.query`, executed as `engine.search(...)` in `Controller._descend`, controller.py:164). Replace it with a `Queryable` object so the Controller can execute ANY query type without knowing which it is — the prerequisite for a TieredSearcher.

Behavior-preserving for the LIVE pipeline: cover-only, no new query type, no new agent. Live ranked output is identical. The seam's own unit tests ARE updated (see below) — the public/live behavior is what is preserved, not the unit tests of the seam.

## Design (agreed in conversation)

**`Queryable` interface** (new module, e.g. `isj_agent/protocol/queryable.py`). Each query type fully owns:
- `tool_schema() -> dict` (classmethod): the OpenAI function-tool definition handed to the LLM.
- `from_tool_arguments(args: dict) -> Queryable` (classmethod): build the object from the LLM tool call's parsed `arguments`.
- `execute(engine, *, top_k, exclude, window) -> SearchResponse`: run against the engine and return the existing `SearchResponse` shape. The engine is PASSED IN, never held — only the Controller (which owns the engine) can execute, structurally enforcing "agents never touch Cottontail."
- `tool_name: str` and `trace_arguments() -> dict`: the TRACE DESCRIPTOR (see the linchpin section below).
- `query_string() -> str`: a plain-STRING form of the query, for the persisted `RankedEntry.surfacing_query` (a typed `str`). Distinct from the dict `trace_arguments()`.

**`CoverQuery{gcl: str}`** implements `Queryable`:
- `tool_name = "cover_search"`; schema `{properties: {query: string}, required: [query]}`.
- `from_tool_arguments({"query": gcl}) -> CoverQuery(gcl)`.
- `execute(...) == engine.search(self.gcl, top_k=top_k, exclude=exclude, window=window)` — identical to today.
- `trace_arguments() == {"query": self.gcl}`; `query_string() == self.gcl` (so the persisted surfacing_query stays the bare GCL).

**`BaseSearcher`** (generic round-trip). Holds `system_prompt` and `query_types: list[type[Queryable]]`.
- `propose()`: `tools = [qt.tool_schema() for qt in query_types]`, `tool_choice="required"`; on the returned tool call, route by name via `by_name = {qt.tool_name: qt}` then `by_name[call.function.name].from_tool_arguments(json.loads(call.function.arguments)) -> queryable`.
- PRESERVE THE DEFENSIVE BOUNCE: malformed/empty `arguments` (today caught as `JSONDecodeError` at searcher.py:119-122), an unknown tool name, OR an inline-JSON emission (gpt-oss occasionally emits the tool call as JSON in `message.content` instead of a proper `tool_calls` entry, leaving `tool_calls` empty) all yield `queryable = None` so the Controller bounces it back and the model retries (test_searcher.py:84 covers the malformed case). The inline-JSON case is rare; do NOT build a content-recovery fallback (it would parse a possibly-truncated emission) -- just bounce. Do not let the parse-move-into-routing drop this path.
- The current `Searcher` becomes a thin `Searcher(BaseSearcher)` -- CLASS NAME UNCHANGED -- with `query_types=[CoverQuery]` and the existing `searcher.md` prompt. `[agents.searcher].class` (`isj_agent.agents.searcher.Searcher`) and all imports are UNCHANGED; only the class body moves onto `BaseSearcher`.

**`ProposeResult`**: replace `query: str` with `queryable: Queryable | None` (keep `assistant_message`, `tool_call_id`, `usage`, `content`, `finish_reason`, `n_tool_calls`).

## The trace descriptor — the LINCHPIN that keeps TASK-19/20 controller-free

The `"search"` / `{"query": …}` coupling in the controller is broader than two lines; it is:
- controller.py:111-114 — the searcher_turn `llm_call` trace: `name:"search"`, `arguments={"query":…}`, `tool=("search"…)`.
- controller.py:118-124 — the `pr.query is None` defensive branch and its bounce text.
- controller.py:127, 161, 167, 174 — every `_descend` emit carrying `query=query`.
- controller.py:225, 232 — `_summarize` emits `{"query": query, …}` as the FIRST key of the judged-results payload the Searcher reads. (You cannot `json.dumps` a Queryable, so this must change.)
- controller.py:206-208 — `RankedEntry(…, surfacing_query=query)`: the THIRD query sink. `surfacing_query` is a typed `str` (results.py:24) PERSISTED in the final ranked list. It needs a STRING, not the descriptor dict.

There is also a downstream CONSUMER of the trace, not just the controller: the `--verbose` CLI renderer at cli.py:47, 49, 52 hard-indexes `d['query']` for the propose / search_request / search events. If those events stopped carrying a `query` key, a live tiered `--verbose` run (TASK-20's validation path) would KeyError.

Resolve each sink with the right representation -- descriptor (`tool_name` + `trace_arguments()` dict) for the LLM-facing sinks, `query_string()` for the display/persisted-string sinks -- NOT via `isinstance`:
- the `llm_call` tool fields (111-114): `name = queryable.tool_name`, `arguments = json.dumps(queryable.trace_arguments())` (the actual tool call the LLM made). cli.py already renders `calls[].name(arguments)` generically.
- the `propose` / `search_request` / `search` event display field (127, 161, 167, 174): keep the existing `query` key, set to `queryable.query_string()`. This keeps the `--verbose` renderer working for ANY queryable with NO cli.py change and byte-identical cover output (`query_string()==gcl`); a tiered run shows the joined-tier string.
- `_summarize`'s leading payload field (225, 232): spread `**queryable.trace_arguments()` instead of a hardcoded `{"query": query}` (cover -> `{"query":…}`, tiered -> `{"tiers":…}`).
- `RankedEntry.surfacing_query` (206-208): `queryable.query_string()` -- a STRING. Do NOT `json.dumps(trace_arguments())` here: that would change the saved cover value from `(^ …)` to `{"query": "(^ …)"}`, a visible non-behavior-preserving change.

Because the events keep a `query` key (= `query_string()`), the `--verbose` renderer needs no change, and neither TASK-19 nor TASK-20 touches cli.py -- consistent with TASK-19's "diff touches only TieredQuery plus tests".

For a `CoverQuery` this is BYTE-IDENTICAL: `trace_arguments() == {"query": gcl}`, so the judged-results payload keys stay `query, atom_counts, total_matches, depth_judged, already_judged, new_results` (preserving `test_controller.py`'s `list(payload) == ["query", …]` assertion at ~line 209), and `query_string() == gcl` keeps `RankedEntry.surfacing_query` byte-identical (the bare GCL). `_compile` is unchanged. After this, TASK-19's `TieredQuery` (`trace_arguments() == {"tiers": […]}`) and TASK-20 add NO controller code — the controller reads everything through the descriptor.

## Controller change
`_descend(intent, queryable, …)`; the refill `engine.search(query, …)` (line 164) becomes `queryable.execute(self.engine, top_k=self.fetch_k, exclude=sorted(seen), window=self.window)`. Trace/`_summarize` read the descriptor (above). Waves, judging, streak, budget, dedup, and `_compile` are unchanged.

## Naming nuance (avoid an over-eager rename)
The rename `search -> cover_search` is the LLM-FACING OpenAI function name only. The Python `engine.search()` method and the server endpoint `/tools/cover_search` (http.py:72) are already correctly named and do NOT change.

## Unit tests to update (not "unchanged")
`test_searcher.py` asserts `r.query == …` (lines 46/80/89) and tool `names == ["search"]` (line 60); `test_controller.py`'s `StubSearcher` builds `ProposeResult(query=q, …)` with a `"search"` tool call (lines 51-58). Rewrite these to the new seam (`queryable`, `cover_search`). Live ranked output is unchanged.

## Doc tweak
In `docs/design/agent-architecture.txt` QUERY TYPES, change "converted into an actual Cottontail query by the Controller" to "executed by the queryable when the Controller invokes it (passing the engine, top-k, exclude, window)."

## Out of scope
Tiered queries (TASK-19), the TieredSearcher agent (TASK-20), any engine/server change.

Key files: `isj/isj_agent/agents/searcher.py`, `isj/isj_agent/controller.py`, `isj/isj_agent/cli.py` (the --verbose renderer), `isj/isj_agent/protocol/search.py`, `isj/isj_agent/protocol/results.py`, `isj/isj_agent/engine/base.py`, `isj/tests/*`, `docs/design/agent-architecture.txt`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A Queryable interface provides tool_schema(), from_tool_arguments(args), and execute(engine, *, top_k, exclude, window) -> SearchResponse
- [x] #2 Each Queryable exposes a trace descriptor (tool_name plus trace_arguments() -> dict); the Controller derives the trace tool fields and the leading key(s) of the searcher-facing judged-results payload from it via spreading trace_arguments(), so _summarize is generic with no isinstance branch
- [x] #3 CoverQuery.trace_arguments() returns {"query": gcl}, so for a cover query the judged-results payload key order stays query, atom_counts, total_matches, depth_judged, already_judged, new_results (the existing payload-shape assertion still holds)
- [x] #4 CoverQuery implements Queryable and its execute() delegates to engine.search, returning the same SearchResponse as before the refactor
- [x] #5 BaseSearcher builds the LLM tool list from its query_types and routes a returned tool call to a Queryable by tool name; the cover searcher is a BaseSearcher with query_types=[CoverQuery]
- [x] #6 Malformed or empty tool arguments, or an unknown tool name, yield queryable=None and the Controller bounces it back to the searcher (the existing defensive path is preserved)
- [x] #7 ProposeResult carries a Queryable; the Controller calls queryable.execute(self.engine, ...) and never calls engine.search directly; the Queryable receives the engine as a parameter and stores no engine reference
- [x] #8 Live single-cover ranked output is identical to before the refactor; the seam unit tests (test_searcher.py and the test_controller.py StubSearcher) are updated to the queryable / cover_search seam
- [x] #9 Only the LLM-facing function is renamed search -> cover_search (engine.search() and the /tools/cover_search server endpoint are unchanged); agent-architecture.txt QUERY TYPES wording is updated to say the queryable executes itself when invoked by the Controller
- [x] #10 Queryable provides query_string() -> str (a plain string, distinct from trace_arguments() dict); the Controller sets RankedEntry.surfacing_query from queryable.query_string() at controller.py:208
- [x] #11 CoverQuery.query_string() == its gcl, so the persisted RankedEntry.surfacing_query for a cover query stays the bare GCL (e.g. (^ ...)) and is never a dict or JSON
- [x] #12 The --verbose CLI renderer (cli.py propose/search_request/search) does not KeyError on any queryable: the trace events keep a query key set to queryable.query_string() (cover renders byte-identically), so neither TASK-19 nor TASK-20 needs a cli.py change
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Build bottom-up: new types -> searcher -> controller -> tests -> verify. "Behavior-preserving"
means the per-intent ranked list (intent-NN.json) and the judged-results payload SHAPE are
identical; the trace's llm_call tool NAME intentionally changes `search` -> `cover_search`
(AC#9), which is not a regression.

0. BASELINE. `uv run --directory isj pytest` green first (the AC#8 regression baseline). Capture a
   live single-cover run's `intent-00.json` (a cover_search burrow + vLLM) to diff against later.

1. NEW `Queryable` + `CoverQuery`  (isj_agent/protocol/queryable.py, new)
   - `Queryable` (ABC): classmethod `tool_schema() -> dict`; classmethod
     `from_tool_arguments(args: dict) -> Queryable`; class attr `tool_name: str`;
     `trace_arguments() -> dict`; `query_string() -> str`;
     `execute(engine, *, top_k, exclude, window) -> SearchResponse`.
     Type `engine` as `SearchEngine` under `TYPE_CHECKING` (keep protocol/ from importing engine/
     at runtime).
   - `CoverQuery(gcl: str)` (frozen dataclass): tool_name="cover_search";
     tool_schema() = the current `_TOOLS[0]` renamed to "cover_search" (params {query:string});
     from_tool_arguments({"query": g}) -> CoverQuery(g);
     trace_arguments() == {"query": self.gcl}; query_string() == self.gcl;
     execute() == engine.search(self.gcl, top_k=top_k, exclude=exclude, window=window) -- lets
     EngineError propagate.
   - NEW tests test_queryable.py: schema name; from_tool_arguments round-trip; trace_arguments /
     query_string values; execute() forwards (gcl, top_k, exclude, window) to a FakeEngine.

2. `ProposeResult` + `BaseSearcher` + `Searcher` (class name UNCHANGED)  (isj_agent/agents/searcher.py)
   - ProposeResult: `query: str | None` -> `queryable: Queryable | None` (keep content,
     tool_call_id, assistant_message, usage, finish_reason, n_tool_calls).
   - BaseSearcher: attrs `system_prompt`, `query_types: list[type[Queryable]]`;
     __init__(client, model, *, reasoning_effort="high", temperature=0.0).
     propose(messages): `tools=[qt.tool_schema() for qt in query_types]`,
     `by_name={qt.tool_name: qt}`, `tool_choice="required"`; take message.tool_calls[0];
     `qt = by_name.get(call.function.name)`; `args = json.loads(call.function.arguments)` in a
     try/except JSONDecodeError; `queryable = qt.from_tool_arguments(args) if qt else None`.
     Empty tool_calls / unknown tool name / malformed args -> queryable=None (DEFENSIVE BOUNCE;
     NO inline-JSON recovery -- just bounce). Build assistant_message exactly as today.
   - `Searcher(BaseSearcher)` -- CLASS NAME UNCHANGED: `query_types=[CoverQuery]`,
     `system_prompt=_PROMPT` (searcher.md), keep the `prompt`/`system_prompt` class attrs the
     tests/controller read. Config path `isj_agent.agents.searcher.Searcher` and all imports are
     UNCHANGED -- only the class body moves onto BaseSearcher (NO config.toml / config.example.toml edit).
   - Grep searcher.md for a literal "search" tool reference; if the prompt names the tool, update
     to cover_search (it mostly refers generically).

3. CONTROLLER WIRING  (isj_agent/controller.py) -- read everything via the descriptor/query_string, no isinstance
   - run(): use `pr.queryable`. llm_call emit (111-114):
     `calls=[{"name": pr.queryable.tool_name, "arguments": json.dumps(pr.queryable.trace_arguments())}]`
     `tool=pr.queryable.tool_name` (both guarded by `pr.queryable is not None`).
     The `pr.query is None` branch (118-124) -> `pr.queryable is None`.
     propose emit (127): `query=pr.queryable.query_string()`. Call `_descend(intent, pr.queryable, ...)`.
   - _descend(intent, queryable, ...): the refill `self.engine.search(query, top_k=self.fetch_k,
     exclude=exclude, window=self.window)` (164) -> `queryable.execute(self.engine, top_k=self.fetch_k,
     exclude=exclude, window=self.window)` inside the SAME `try/except EngineError` (bounce on raise).
     search_request/search emits (161,174): `query=queryable.query_string()`.
     RankedEntry (206-208): `surfacing_query=queryable.query_string()`.
     Pass `queryable` to `_summarize`.
   - _summarize(queryable, atom_counts, total_matches, depth, again, fresh):
     `return {**queryable.trace_arguments(), "atom_counts":…, "total_matches":…, "depth_judged":…,
     "already_judged":…, "new_results":…}`. For CoverQuery the leading key is "query" -> preserves
     the `list(payload)==["query", …]` order asserted at test_controller.py:208.

4. CLI RENDERER  (isj_agent/cli.py) -- verify, no change expected
   - propose/search_request/search renderers (47,49,52) read `d['query']`; that key is still present
     (= query_string()), so cover renders identically and a future tiered run shows the joined-tier
     string -- NO KeyError, NO code change. Confirm during the live --verbose run in step 6.

5. UPDATE SEAM TESTS
   - test_searcher.py: import `Searcher` (name unchanged); `_tool_call` name
     "search"->"cover_search"; assert on `r.queryable` (e.g. `r.queryable.query_string() == "(^ …)"`)
     not `r.query`; line 60 `names == ["cover_search"]`; malformed-args and no-tool-call tests assert
     `r.queryable is None`.
   - test_controller.py: StubSearcher.propose returns `ProposeResult(queryable=CoverQuery(q), …)` and a
     cover_search tool call; keep the line-208 payload key-order assertion (must still pass); ADD:
     RankedEntry.surfacing_query == the bare gcl (AC#11), and the payload leading key == "query" (AC#3).
     Grep the file for any other `"search"` name assertion and update.

6. DOC + VERIFY
   - docs/design/agent-architecture.txt QUERY TYPES: "converted into an actual Cottontail query by the
     Controller" -> "executed by the queryable when the Controller invokes it (passing the engine,
     top-k, exclude, window)".
   - `uv run --directory isj pytest` green. Live single-cover run: diff `intent-00.json` vs the step-0
     capture for byte-identity (AC#8); confirm `--verbose` renders with no KeyError.
   - Check ACs #1-#12.

AC MAP: #1->step1; #2,#3->steps1,3,5; #4->step1; #5->step2; #6->step2; #7->steps2,3; #8->steps5,6;
#9->steps2,6; #10,#11->steps1,3,5; #12->step4.

FROZEN SEAMS -- TASK-19/20 plug into these; implement EXACTLY so they need no base/controller change:
- Queryable.execute(engine, *, top_k, exclude, window) -> SearchResponse. Signature is fixed;
  TieredQuery implements it identically. The controller calls it generically each REFILL with
  exclude=sorted(seen), so paging works for any queryable (TieredQuery re-runs its cascade per call).
- Descriptor: tool_name:str, trace_arguments()->dict, query_string()->str. The controller reads EVERY
  query sink through these (never isinstance): llm_call name/args <- tool_name + trace_arguments();
  _summarize leading field <- **trace_arguments(); propose/search event `query` key + surfacing_query
  <- query_string(). TieredQuery supplies {"tiers":[...]} / joined string with zero controller change.
- BaseSearcher is generic over `query_types: list[type[Queryable]]` (build tools + route by tool_name);
  NO CoverQuery hardcoding. __init__(client, model, *, reasoning_effort, temperature) unchanged so
  config selection (cli _build_agent) constructs TieredSearcher identically; system_prompt/query_types
  are subclass CLASS attrs.
- Dry detection stays on `resp.results` empty (controller.py:179), NOT total_matches -- so TASK-19's
  total_matches=sum aggregation never affects control flow.
CONSEQUENCE (consistent, already deferred): a tiered query is traced at the queryable boundary -- one
search_request/search event per execute() with MERGED results + UNION atom_counts; the internal
per-tier engine.search calls are not individually traced (matches the deferred per-tier surfacing_query).

DECISIONS:
A. RESOLVED (per user): keep the class named `Searcher` -- a thin `Searcher(BaseSearcher)`. Config
   path (`isj_agent.agents.searcher.Searcher`) and imports are UNCHANGED. Only the LLM tool STRING
   renames `search` -> `cover_search`; the class name does not.
B. BaseSearcher + Searcher live in agents/searcher.py; Queryable + CoverQuery in protocol/queryable.py.
C. Queryable.execute types `engine` as SearchEngine via TYPE_CHECKING (protocol/ does not import
   engine/ at runtime).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
IMPLEMENTED (all steps). New isj_agent/protocol/queryable.py (Queryable ABC + CoverQuery with tool_schema/from_tool_arguments/execute/tool_name/trace_arguments/query_string) + tests/test_queryable.py (6). searcher.py: ProposeResult.query->queryable; generic BaseSearcher (tools from query_types, route by tool_name, defensive bounce incl. unknown-tool/malformed-args, no inline-JSON recovery); Searcher(BaseSearcher) name unchanged, query_types=[CoverQuery]. controller.py: reads all four query sinks via the descriptor/query_string (llm_call<-tool_name+trace_arguments; propose/search/list_exhausted/bounce event 'query'<-query_string; _summarize leading field<-**trace_arguments; surfacing_query<-query_string; refill calls queryable.execute). LLM tool renamed search->cover_search (CoverQuery schema + searcher.md refs). doc: agent-architecture.txt QUERY TYPES wording. cli.py unchanged (events keep 'query' key). Tests updated: test_searcher (cover_search, r.queryable, +unknown-tool test), test_controller (StubSearcher->CoverQuery/cover_search, +surfacing_query + llm_call-trace-name tests). Suite: 96 passed, 1 skipped. LIVE smoke (gpt-oss + climbmix-1M-porter): one intent, clean; model called cover_search; surfacing_query='(^ "Yellowstone" bear* safety*)' (bare GCL); --verbose rendered 35 events with NO KeyError.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Queryable seam landed, cover-only and behavior-preserving. Queryable ABC + CoverQuery own tool_schema/from_tool_arguments/execute/tool_name/trace_arguments/query_string; BaseSearcher is generic over query_types (routes by tool_name, defensive bounce, no inline-JSON recovery); the Controller reads all four query sinks via the descriptor (trace_arguments for the LLM-facing sinks, query_string for the display/persisted sinks), calls queryable.execute(), and never touches engine.search directly. LLM tool renamed search->cover_search; class name Searcher and cli.py unchanged. Verified: 96 pytest passed (incl. new test_queryable + updated seam tests + surfacing_query/trace-name tests); live smoke (gpt-oss + climbmix-1M-porter) ran clean, model called cover_search, surfacing_query is a bare GCL, --verbose rendered all events with no KeyError. AC#8 taken as shape-identity (unit tests) + clean live run; a strict pre/post byte-diff was not run and is unreliable anyway since the intended tool rename changes the model's input.
<!-- SECTION:FINAL_SUMMARY:END -->
