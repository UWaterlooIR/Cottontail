---
id: TASK-5.6
title: 'B2 — isj: Searcher agent + guardrailed loop controller (vs FakeEngine)'
status: To Do
assignee: []
created_date: '2026-06-18 03:20'
labels:
  - python
  - isj
  - searcher
dependencies:
  - TASK-5.5
references:
  - docs/searcher-agent-lessons-June-16-2026.md
  - isj/scouting/scout_searcher.py
  - isj/isj_agent/agents/analyst.py
  - isj/isj_agent/agents/analyst.md
  - isj/isj_agent/protocol/search.py
  - isj/isj_agent/engine
  - isj/README.md
parent_task_id: TASK-5
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

Python, in the `isj/` uv project (package `isj_agent`; `uv sync --project isj` after
changes). New files: `isj_agent/agents/searcher.py` (the Searcher class + the loop
controller) and `isj_agent/agents/searcher.md` (its bundled prompt); the RankedList output
type in `isj_agent/protocol/` (B1 deferred it to here); tests in `isj/tests/`. Mirror the
Analyst exemplar: `isj_agent/agents/analyst.py` (injected client + model, prompt loaded
from a bundled .md via importlib.resources) and `analyst.md`. NO C++. Automated tests use a
STUB LLM + the B1 FakeEngine — no network, no real model; a real-LLM run is a manual step.
DEPENDS ON B1 (TASK-5.5): the SearchEngine Protocol, the SearchResponse/Hit/AtomCount/
Judgement types, the scripted FakeEngine, AND B1's engine error channel (see "B1 amendment"
at the end).

## Context (for an agent new to this project)

The Searcher plays one human "interactive searcher" (ISJ — Interactive Searching and
Judging) as an LLM loop. INPUT: one intent (a self-contained, search-ready restatement of
what the user wants — one of the Analyst's `Intents.interpretations`). OUTPUT: a per-intent
ranked, graded list of passages (RankedList). Later tasks fuse per-intent lists with RRF
(C2) and wire the orchestrator (C3); B2 is ONE intent -> one RankedList.

The loop (validated by live scouting against gpt-oss-120b, Qwen3.6-27B, gemma-4-31B; see
docs/searcher-agent-lessons-June-16-2026.md and the working prototype
isj/scouting/scout_searcher.py): write a GCL cover query -> read the returned passages ->
judge them -> reformulate using what was read -> stop when results dry up or the budget is
spent.

The engine it talks to is the `cover_search` tool (A1/A2 = TASK-5.1/5.2), reached through
B1's `SearchEngine` Protocol. B2 does NOT call HTTP or C++ — it calls `engine.search(...)`
and `engine.read(...)` on an injected SearchEngine; in tests that is the FakeEngine, in live
use (C1) it is HttpSearchEngine. The cover_search request is { query (a GCL cover that may
use the word* family marker), top_k, exclude_docids (the judged set to skip), window } and
the response is { total_matches, unjudged_matches, atom_counts:[{term,count}],
results:[{rank, score, docid, summary}] } where summary is a cover-biased extractive
summary. The agent holds the judged set; the engine is stateless.

Hard lessons from scouting that SHAPE this controller:
- Models emit ONE tool call per turn and do NOT support parallel tool calls -> `judge` is a
  BATCH tool (one call carries all of a search's verdicts), and the loop assumes one call
  per turn.
- Termination is NOT model-portable: gpt-oss stops by emitting no tool call (and otherwise
  writes a prose summary), while Qwen spins on empty `judge []` forever. So the CONTROLLER
  owns termination; "no tool call" is just one accepted stop.
- Models violate soft rules under pressure (skip judging, write invalid GCL) -> guardrails
  are ENFORCED by the controller, not trusted to the prompt; the model self-corrects when
  bounced with an error.

Error handling is ENGINE-DELEGATED (decision): the truth about GCL validity lives in
cover_search (it converts our word*-marked GCL using the burrow's own Porter; Python cannot
know the stems). So there is NO Python GCL validator. Instead, `engine.search` may raise an
EngineError (invalid GCL is just one possible cause); the controller catches ANY EngineError
and feeds its message back to the model as the tool result so it can self-correct. Repeated
errors are bounded by the same budget/no-progress backstop.

## The loop controller (pseudocode)

```
def run(intent) -> RankedList:
    msgs = [system(searcher.md), user(intent)]
    judged: set[str] = set()         # docids already judged (the judged set)
    judgements = []                  # accumulated Judgement + the surfacing query + score
    pending: list[Hit] = []          # surfaced this search, not yet judged
    surfacing_query: dict[docid,str] # which query surfaced each docid
    searches = dry = no_progress = 0
    while searches < budget.max_searches:
        m = llm(msgs, TOOLS)         # one create() call; TOOLS = [search, judge]
        msgs.append(assistant(m))
        if not m.tool_calls:                       # accepted stop (gpt-oss style)
            break
        call = m.tool_calls[0]                      # exactly one per turn
        if call.name == "search":
            if pending:                             # GUARDRAIL: judge before searching
                msgs.append(tool_error(call, f"Judge these first: {[h.docid for h in pending]}"))
                continue
            try:
                resp = engine.search(call.query, top_k=cfg.top_k,
                                     exclude_docids=sorted(judged), window=cfg.window)
            except EngineError as e:                # ENGINE-DELEGATED error handling (any error)
                msgs.append(tool_error(call, str(e)))   # bounce; model self-corrects
                continue
            pending = list(resp.results)
            for h in resp.results: surfacing_query[h.docid] = call.query
            searches += 1
            dry = dry + 1 if not resp.results else 0
            no_progress = 0
            msgs.append(tool_result(call, resp))
        elif call.name == "judge":
            new = [j for j in call.judgements if j.docid not in judged]
            for j in new: judged.add(j.docid); judgements.append(record(j, surfacing_query, pending))
            pending = [h for h in pending if h.docid not in judged]
            no_progress = no_progress + 1 if not new else 0
            msgs.append(tool_result(call, {"ok": True, "recorded": len(new)}))
        if dry >= 2 or no_progress >= 2:            # controller-owned stops (Qwen-proof)
            break
    return compile_ranked_list(intent, judgements)  # all judged, grade desc then score desc
```

## Required behavior (the contract)

1. Searcher (agents/searcher.py): run(self, intent: str) -> RankedList. Constructed with an
   injected OpenAI-compatible client + model AND an injected SearchEngine (B1). Prompt loaded
   from the bundled searcher.md (importlib.resources), like Analyst.
2. Exactly TWO LLM tools: `search` (argument: query: str) and `judge` (argument:
   judgements: list of {docid: str, grade: int 0-4, reason: str}). One tool call per turn;
   no parallel calls assumed; no `read` and no `finish` tool in the MVP.
3. The model writes ONLY the query; the CONTROLLER injects exclude_docids = the accumulated
   judged set on every engine.search call, and supplies top_k and window from config
   defaults. The model never sets exclude_docids/top_k/window.
4. Guardrail - judge before search: if the model calls `search` while there are
   surfaced-but-unjudged passages (pending), refuse (no engine call) and return a tool
   message naming the docids to judge first; the model recovers by judging them.
5. Engine-delegated errors: if engine.search raises EngineError (invalid GCL, or any other
   engine error), append str(error) as the tool result so the model can self-correct; never
   crash. Repeated errors are bounded by the budget / no-progress backstop.
6. Judge handling: record every judgement INCLUDING grade 0; add their docids to the judged
   set; clear them from pending; track which query surfaced each judged docid (for the
   output). An empty or all-duplicate `judge []` counts as no progress.
7. Termination is controller-owned: stop when the model emits no tool call (discard any
   trailing prose), OR on >=2 consecutive dry searches (a search whose results are empty),
   OR on >=2 consecutive no-progress turns, OR when the max-search budget is hit. Do NOT
   rely on the model to stop.
8. Output: run() returns a RankedList of ALL judged passages (grade 0 included), ordered by
   grade desc then engine score desc, ranks assigned 1..N.
9. The RankedList type is defined here (B1 deferred it), in isj_agent/protocol/ (pydantic v2,
   per B1's pydantic conventions):

   class RankedEntry(BaseModel):
       rank: int
       docid: str
       grade: int = Field(ge=0, le=4)
       score: float                 # the engine (ssr) score of the surfacing search
       summary: str                 # the cover-biased summary the agent judged
       reason: str                  # the judge's one-line justification
       surfacing_query: str         # the GCL query that surfaced this docid

   class RankedList(BaseModel):
       intent: str
       entries: list[RankedEntry]

10. searcher.md prompt (self-contained; base on docs/searcher-agent-lessons section 3,
    adapted to grade 0-4 and the search+judge tools): the ISJ loop; a GCL cheatsheet using
    the word* family marker (write the FULL word + *), facet covers ((^ ...) of (+ ...)
    groups), and (!> ...) to carve a false sense you have READ; the three-way term model
    (bare = exact, word* = family, (+ ...) = synonyms); a 0-4 relevance rubric; loop rules
    (judge every returned passage before searching again; reformulate using words you read;
    stop when results dry up; when done, stop and write nothing). It MUST NOT mention
    `porter:` or index streams.

## Non-goals

- No RRF (C2), no orchestrator/multi-intent (C3): one intent -> one RankedList.
- No `read` tool, no `finish` tool (search + judge only; termination via no-tool-call +
  controller stops).
- No Python GCL validator (engine-delegated errors; the engine is authoritative).
- No C++; no live network or real LLM in automated tests.

## B1 amendment this task needs

Engine-delegated error handling requires a small addition to B1 (TASK-5.5), which should be
made there: (a) an `EngineError(Exception)` type in the engine contract that search()/read()
may raise; (b) FakeEngine support for scripted errors — a script entry may be an EngineError
to raise on that call — so B2 can test the bounce. B2 depends on B1 having these.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 isj_agent/agents/searcher.py defines a Searcher with run(intent: str) -> RankedList, constructed with an injected OpenAI-compatible client + model and an injected SearchEngine (B1), loading its prompt from a bundled searcher.md (like Analyst).
- [ ] #2 The LLM is given exactly two tools: search (argument query: str) and judge (argument judgements: list of {docid, grade 0-4, reason}); the loop makes one tool call per turn and assumes no parallel calls; there is no read and no finish tool.
- [ ] #3 The model writes only the query; the controller injects exclude_docids = the accumulated judged set on every engine.search call and supplies top_k and window from config defaults (asserted via FakeEngine.calls).
- [ ] #4 Judge-before-search guardrail: calling search while surfaced passages are unjudged is refused with a tool message naming the docids to judge first (no engine call), and the model recovers by judging them.
- [ ] #5 Engine-delegated errors: when engine.search raises EngineError, the controller appends the error message as the tool result so the model can self-correct, and never crashes; repeated errors are bounded by the budget/no-progress backstop.
- [ ] #6 Judge handling records every judgement including grade 0, adds docids to the judged set, clears them from pending, and tracks which query surfaced each judged docid; an empty or all-duplicate judge counts as no progress.
- [ ] #7 Termination is controller-owned: the loop stops on a no-tool-call turn (trailing prose discarded), or >=2 consecutive dry searches (empty results), or >=2 consecutive no-progress turns, or the max-search budget; it does not rely on the model to stop.
- [ ] #8 Every passage a search returns is judged before the next search (guardrail-enforced), so at termination the judged set covers all surfaced docids (nothing dropped).
- [ ] #9 run(intent) returns a RankedList of ALL judged passages (grade 0 included), ordered by grade desc then engine score desc, ranks assigned 1..N.
- [ ] #10 isj_agent/protocol defines pydantic RankedEntry{rank,docid,grade(0-4),score,summary,reason,surfacing_query} and RankedList{intent,entries} (B1 deferred this type to B2).
- [ ] #11 isj_agent/agents/searcher.md is self-contained: the ISJ loop; a GCL cheatsheet using the word* family marker (full word + *), facet covers, and !> carve; the three-way term model (bare exact / word* family / (+ ) synonyms); a 0-4 relevance rubric; loop rules (judge before re-search, reformulate from what was read, stop when dry, stop = no tool call and write nothing); and it never mentions porter: or index streams.
- [ ] #12 Tests use a stub LLM (scripted tool-call sequences) + the B1 FakeEngine and cover the happy path (correctly ordered RankedList incl. grade 0), judge-before-search bounce+recovery, EngineError bounce+recovery, stop-on-2-dry, no-progress stop, budget cap, and exclude_docids accumulation; no test contacts a network or a real model.
- [ ] #13 uv sync --project isj succeeds and uv run --directory isj pytest tests/ exits 0; isj/README.md documents the Searcher (run->RankedList, the two tools, controller guardrails + termination, 0-4 grades) and notes a real-LLM run is a manual step.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Python in isj/. Depends on B1 (TASK-5.5) incl. the EngineError addition. Adapt as needed.

1. uv sync --project isj. Read isj_agent/agents/analyst.py + analyst.md (the injected
   client/model + bundled-prompt pattern), B1's isj_agent/engine/ (Protocol + FakeEngine +
   EngineError) and isj_agent/protocol/search.py (types), docs/searcher-agent-lessons
   section 3 (the prompt), and isj/scouting/scout_searcher.py (the working loop prototype).
2. isj_agent/protocol/: add RankedEntry + RankedList (pydantic, as in the description).
3. isj_agent/agents/searcher.py: the Searcher class (client, model, engine, prompt) and the
   loop controller (pseudocode in the description). Define the two LLM tool schemas (search:
   {query}; judge: {judgements:[{docid,grade,reason}]}); one tool call per turn; inject
   exclude_docids=judged set + config top_k/window on each engine.search; guardrail bounce
   for search-while-pending; catch EngineError and bounce; record judgements (incl. grade 0)
   + surfacing query; controller stops (no-tool-call / 2 dry / 2 no-progress / budget);
   compile_ranked_list(intent, judgements) sorted (grade desc, score desc), ranks 1..N.
4. isj_agent/agents/searcher.md: author the prompt per the contract (ISJ loop; word* GCL
   cheatsheet; three-way terms; 0-4 rubric; loop rules; no porter:/streams). Ensure it is
   bundled (hatchling artifacts already include isj_agent/**/*.md).
5. isj/tests/test_searcher.py with a STUB LLM (a fake client whose chat.completions.create
   returns a SCRIPTED sequence of responses: assistant turns with tool_calls, ending in a
   no-tool-call turn) + the B1 FakeEngine. Cover: happy path -> a correctly ordered
   RankedList (grade desc, score desc; grade-0 retained); judge-before-search bounce +
   recovery; EngineError bounce + recovery (FakeEngine scripted to raise, then a real
   batch); stop-on-2-dry; no-progress stop; budget cap; exclude_docids accumulates and is
   passed to engine.search (assert via FakeEngine.calls); nothing surfaced is left unjudged.
   No test contacts a network or a real model.
6. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: the Searcher
   (run(intent) -> RankedList), its two tools, the controller guardrails + termination, the
   0-4 grade scale, and that a real-LLM run is a manual step (point at isj/scouting for a
   live probe).
<!-- SECTION:PLAN:END -->
