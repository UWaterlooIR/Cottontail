---
id: TASK-5.6
title: 'B2 — isj: Searcher agent + guardrailed loop controller (vs FakeEngine)'
status: To Do
assignee: []
created_date: '2026-06-18 03:20'
updated_date: '2026-06-18 14:44'
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
controller) and `isj_agent/agents/searcher.md` (its bundled prompt); the output/trace types
(RankedEntry/RankedList, TraceEvent, SearcherResult) in `isj_agent/protocol/` (B1 deferred
RankedList here); tests in `isj/tests/`. Mirror the Analyst exemplar
(`isj_agent/agents/analyst.py` + `analyst.md`). NO C++. Automated tests use a STUB LLM + the
B1 FakeEngine — no network, no real model. DEPENDS ON B1 (TASK-5.5): the SearchEngine
Protocol, the SearchResponse/Hit/AtomCount/Judgement types, the scripted FakeEngine, AND
B1's EngineError channel.

## Context (for an agent new to this project)

The Searcher plays one human "interactive searcher" (ISJ) as an LLM loop. INPUT: one intent
(a self-contained, search-ready restatement — one of the Analyst's
`Intents.interpretations`). OUTPUT: a `SearcherResult` = a per-intent `RankedList` (judged,
graded passages) PLUS a structured event `trace`. Downstream, C2 (the run-output writer)
persists per-intent results and C3 (the CLI) runs the whole question; there is NO fusion
(RRF dropped). B2 is ONE intent -> one SearcherResult.

The loop (validated by live scouting against gpt-oss-120b, Qwen3.6-27B, gemma-4-31B; see
docs/searcher-agent-lessons-June-16-2026.md — a DATED snapshot: it shows 0-3 grades and
best_passage; THIS task uses 0-4 grades and the cover-biased `summary`; and the working
prototype isj/scouting/scout_searcher.py): write a GCL cover query -> read the returned
passages -> judge them -> reformulate -> stop when results dry up or the budget is spent.

The engine is the `cover_search` tool (A1/A2), reached through B1's `SearchEngine` Protocol.
B2 calls `engine.search(...)` / `engine.read(...)` on an injected SearchEngine (FakeEngine
in tests; HttpSearchEngine live, wired by C3). The cover_search request is { query (a GCL
cover that may use the word* marker), top_k, exclude_docids, window }; the response is
SearchResponse { total_matches, unjudged_matches, atom_counts:[{term,count}],
results:[Hit{rank,score,docid,summary}] }. The agent holds the judged set; the engine is
stateless.

Hard lessons from scouting that SHAPE the controller:
- Models emit ONE tool call per turn, no parallel calls -> `judge` is a BATCH tool; the loop
  takes m.tool_calls[0] and assumes one call per turn.
- Termination is NOT model-portable (gpt-oss stops via no tool call; Qwen spins on empty
  judge[]) -> the CONTROLLER owns termination.
- Models violate soft rules under pressure -> guardrails are ENFORCED by the controller; the
  model self-corrects when bounced with an error message.

Error handling is ENGINE-DELEGATED: there is NO Python GCL validator. `engine.search` may
raise EngineError (invalid GCL is just one cause); the controller bounces by feeding
str(error) back to the model.

## The trace is a research output (structured events)

The trace is NOT a text blob — it is a sequence of TIMESTAMPED EVENTS the controller emits,
so we can later compute statistics about what the agent does (LLM latency, engine latency,
queries issued, judgements/grades, bounces, why it stopped). Each event:
  { type: str, ts: float (epoch seconds), duration_ms: float, ...type-specific fields }
The controller returns the events in SearcherResult.events (a list[TraceEvent]); C2 writes
them as intent-NN.trace.jsonl (one JSON object per line); C3 --verbose renders them live.
Recommended event taxonomy (the controller emits at least these):
  - "llm_turn":  one LLM create() call. fields: turn:int, tool: str|null (which tool the
                 model asked for), stopped: bool. duration_ms = LLM call latency.
  - "search":    an accepted cover_search. fields: query, top_k, exclude_count, window,
                 total_matches, unjudged_matches, returned:int, atom_counts:[{term,count}].
                 duration_ms = engine latency.
  - "judge":     a batch judge. fields: recorded:int, grades:[int]. (controller-side)
  - "bounce":    a guardrail bounce. fields: kind: "judge_before_search" | "engine_error",
                 message: str.
  - "stop":      termination. fields: reason: "no_tool_call" | "dry" | "no_progress" |
                 "budget" | "turn_cap".

## The loop controller (pseudocode)

```
def run(intent) -> SearcherResult:
    msgs = [system(searcher.md), user(intent)]
    judged: set[str] = set()           # docids already judged
    judgements = []                    # accumulated, each carrying summary/score/surfacing_query
    pending: list[Hit] = []            # surfaced this search, not yet judged
    hits_by_docid = {}                 # docid -> the surfaced Hit (for summary + score)
    surfacing_query = {}               # docid -> the query that surfaced it
    events = []
    searches = dry = no_progress = turns = 0
    while turns < budget.max_turns and searches < budget.max_searches:   # TURN CAP + search budget
        turns += 1
        t = clock(); m = llm(msgs, TOOLS); emit(events, "llm_turn", t, turn=turns,
              tool=(m.tool_calls[0].name if m.tool_calls else None), stopped=not m.tool_calls)
        msgs.append(assistant(m))
        if not m.tool_calls:
            emit(events, "stop", reason="no_tool_call"); break
        call = m.tool_calls[0]                                  # one per turn (no parallel)
        if call.name == "search":
            if pending:                                          # GUARDRAIL: judge first
                emit(events, "bounce", kind="judge_before_search", message=...)
                msgs.append(tool_error(call, f"Judge these first: {[h.docid for h in pending]}")); continue
            try:
                t = clock(); resp = engine.search(call.query, top_k=cfg.top_k,
                        exclude_docids=sorted(judged), window=cfg.window)
                emit(events, "search", t, query=call.query, top_k=cfg.top_k,
                     exclude_count=len(judged), window=cfg.window, total_matches=resp.total_matches,
                     unjudged_matches=resp.unjudged_matches, returned=len(resp.results),
                     atom_counts=resp.atom_counts)
            except EngineError as e:                             # ENGINE-DELEGATED error
                emit(events, "bounce", kind="engine_error", message=str(e))
                msgs.append(tool_error(call, str(e))); continue
            pending = list(resp.results)
            for h in resp.results: hits_by_docid[h.docid] = h; surfacing_query[h.docid] = call.query
            searches += 1; dry = dry + 1 if not resp.results else 0; no_progress = 0
            msgs.append(tool_result(call, resp))
        elif call.name == "judge":
            surfaced = {h.docid for h in pending}
            new = [j for j in call.judgements if j.docid in surfaced and j.docid not in judged]  # only surfaced+unjudged; ignore hallucinated docids
            for j in new:
                judged.add(j.docid)
                judgements.append(record(j, hits_by_docid[j.docid], surfacing_query[j.docid]))  # pulls summary + score from the Hit
            pending = [h for h in pending if h.docid not in judged]
            no_progress = no_progress + 1 if not new else 0
            emit(events, "judge", recorded=len(new), grades=[j.grade for j in new])
            msgs.append(tool_result(call, {"ok": True, "recorded": len(new)}))
        if dry >= 2 or no_progress >= 2:
            emit(events, "stop", reason="dry" if dry >= 2 else "no_progress"); break
    else:
        emit(events, "stop", reason="turn_cap" if turns >= budget.max_turns else "budget")
    return SearcherResult(ranked_list=compile_ranked_list(intent, judgements), events=events)
```
Every event carries ts + duration_ms; bounces COUNT as turns (so repeated invalid-GCL /
premature-search bounces terminate via the turn cap, not just the search budget).

## The searcher.md prompt — embed this validated prompt, then adapt it

The block below is the EXACT §3 prompt that produced clean behavior in scouting (Probe 6 on
gpt-oss-120b, re-confirmed on Qwen3.6-27B in Probe 7). The prompt TEXT IS LOAD-BEARING:
Probe 3 showed that compressing it or dropping the worked example collapses GCL quality.
Build searcher.md FROM THIS TEXT — do not paraphrase it. The rationale for every line (why
prefix-only, why word* and never porter:, why the worked example, why each loop rule) is in
docs/searcher-agent-lessons-June-16-2026.md §3 (per-line annotations) and §8 (the probes
that justify them); read the lessons doc for the STORY — this task carries the ARTIFACT.

VERBATIM STARTING POINT (a dated 0-3 snapshot — apply the adaptations that follow it):

```
You are a search analyst exploring a large text collection to answer ONE question.
You find the passages relevant to it and grade each 0-3.

Write queries in GCL, a Boolean cover language. Use PREFIX form ONLY — never infix,
never the words AND/OR/NOT.
  (^ A B C)  all of A,B,C appear together
  (+ A B C)  any of A,B,C
  "a b c"    the exact phrase
  (!> A B)   an A that does NOT contain B  (carve out a false sense you have READ)

Three ways to write a term:
  black      a bare word matches EXACTLY — use for proper nouns and the question's
             defining words.
  bear*      a word followed by * matches that word AND its whole family (bear/bears,
             attack/attacked/attacking). Write the FULL ordinary word then * — e.g.
             statistics*, injury* — NEVER a shortened stem. The system expands it.
             Use it for ordinary content words (not proper nouns/defining terms).
  (+ X Y Z)  is for SYNONYMS — distinct words for one concept — NOT inflections of one word.

Build each query as a COVER: one facet per concept, AND-ed with ^. Example for
'Do I need to worry about black bear attacks while hiking in the woods?':
  (^ black bear* attack*)
Broaden a facet by SYNONYM, e.g. (+ attack* maul* encounter*) — never by adding plurals.

Loop, ONE tool call per turn:
1. `search` a GCL query.
2. JUDGE every returned passage (one `judge` call) before searching again.
3. Reformulate using words learned from passages.
4. `search` reports total_matches; if it returns 0 or only grade-0 passages the query
   is DRY. After at most 2 dry searches in a row, STOP.
5. At most 8 searches. When done, STOP: no tool call, output nothing.
```

How to adapt it for B2 (these are the ONLY changes — keep everything else word-for-word):
1. Grades 0-3 -> 0-4: change line 2 "grade each 0-3" to "grade each 0-4". (The dryness rule's
   "grade-0" stays: 0 is still the bottom of the scale.)
2. ADD a 0-4 relevance rubric (the snapshot has none). RECOMMENDED DEFAULT — reconcile with
   the project's UMBRELA mapping when the eval harness lands:
     0 — Irrelevant: does not address the intent.
     1 — Marginal: on-topic mention but no information that helps answer the intent.
     2 — Related: some useful information, but partial or tangential.
     3 — Relevant: directly answers the intent with useful, on-topic information.
     4 — Highly relevant: a focused, complete answer to the intent.
3. The "At most 8 searches" line is ADVISORY to the model only — the CONTROLLER owns and
   ENFORCES the real search budget + turn cap (see the controller section). Keep a number in
   the prompt but let it track the cfg defaults; never rely on the model to honor it.
4. What the model READS is each Hit's cover-biased `summary` (A1), not a full document — the
   prompt's "passages" ARE those summaries. No wording change needed; just do not promise
   full documents.
5. Do NOT introduce `porter:` or any index-stream / feature syntax. The word* marker is the
   ONLY stemming the model ever sees — this is the single most important wording choice in
   the prompt (lessons doc §3 / Probes 5-6: `porter:` cues the model to guess wrong truncated
   stems that silently miss). The tool translates word* -> Porter; the model must never.
6. The loop names exactly the tools `search` and `judge` (no read, no finish) — matching the
   two LLM tools this task defines.

Everything else — PREFIX-ONLY GCL with the full operator list, the three-way term model
(bare / word* / (+ )), the worked black-bear cover example, "synonyms not inflections", and
the loop rules — is copied VERBATIM because each line maps to a probed failure it prevents
(lessons doc §3 annotations). When in doubt, change nothing.

## Required behavior (the contract)

1. Searcher (agents/searcher.py): run(self, intent: str) -> SearcherResult. Constructed with
   an injected OpenAI-compatible client + model AND an injected SearchEngine (B1). Prompt
   bundled in searcher.md (importlib.resources), like Analyst.
2. Exactly TWO LLM tools: `search` (arg: query: str) and `judge` (arg: judgements: list of
   {docid:str, grade:int 0-4, reason:str}). One tool call per turn; no parallel; no `read`,
   no `finish`. (The LLM-facing tool is named `search`; it maps to the engine's cover_search
   via the Protocol.)
3. The model writes ONLY the query; the CONTROLLER injects exclude_docids = the accumulated
   judged set and supplies top_k + window from config defaults.
4. Guardrail - judge before search: a `search` while pending passages are unjudged is
   refused (no engine call) with a tool message naming the docids; recorded as a `bounce`
   event; the model recovers by judging.
5. Engine-delegated errors: engine.search raising EngineError -> a `bounce` event +
   str(error) fed back as the tool result; never crash.
6. Judge handling: only docids that were SURFACED (in pending) and not yet judged are
   recorded (a hallucinated/un-surfaced docid is ignored, not added); each recorded
   judgement (grade 0 included) pulls its summary + score from the surfaced Hit and its
   surfacing query; docids enter the judged set; an empty/all-duplicate/all-ignored judge is
   no progress.
7. Termination is CONTROLLER-OWNED: stop on a no-tool-call turn (discard trailing prose), OR
   >=2 consecutive dry searches (empty results), OR >=2 consecutive no-progress turns, OR the
   search budget, OR a hard MAX-TURNS cap. Every turn (including bounces) counts toward the
   turn cap, so repeated bounces cannot loop forever. Emit a `stop` event with the reason.
8. Trace: the controller emits a `trace` = list[TraceEvent] (the taxonomy above; each event
   has type, ts, duration_ms, and type-specific fields), returned in SearcherResult.events.
   This is a research artifact for later statistics.
9. Output: compile a RankedList of ALL judged passages (grade 0 included), ordered by grade
   desc then engine score desc, ranks assigned 1..N. RankedEntry.rank is the COMPILED
   per-intent rank (distinct from the engine Hit.rank, which is a per-search position).
10. Types (pydantic v2, isj_agent/protocol/, per B1's pydantic conventions):
      class RankedEntry(BaseModel):
          rank: int; docid: str; grade: int = Field(ge=0, le=4); score: float
          summary: str; reason: str; surfacing_query: str
      class RankedList(BaseModel):
          intent: str; entries: list[RankedEntry]
      class TraceEvent(BaseModel):
          model_config = ConfigDict(extra="allow")   # type-specific fields live alongside
          type: str; ts: float; duration_ms: float
      class SearcherResult(BaseModel):
          ranked_list: RankedList; events: list[TraceEvent]
11. searcher.md prompt (self-contained): START from the validated §3 prompt EMBEDDED above
    ("The searcher.md prompt — embed this validated prompt, then adapt it") and apply the
    adaptations listed there (0-3 -> 0-4 + the rubric; the search count is advisory while the
    controller enforces the budget/turn cap; keep everything else VERBATIM — it is
    load-bearing). The finished prompt MUST contain: the ISJ loop; a GCL cheatsheet using the
    word* family marker (full word + *), facet covers ((^ ...) of (+ ...) groups), and (!> ...)
    to carve a false sense you have READ; the three-way term model (bare = exact, word* =
    family, (+ ...) = synonyms); a 0-4 relevance rubric; loop rules (judge every returned
    passage before searching again; reformulate using words you read; stop when results dry
    up; when done, stop and write nothing). It MUST NOT mention `porter:` or index streams.

## Non-goals

- No fusion (RRF is dropped); no run-output writing (C2); no orchestration / multi-question
  (C3). B2 is one intent -> one SearcherResult.
- No `read` tool, no `finish` tool (search + judge only; termination via no-tool-call +
  controller stops). [read() stays on the engine Protocol as documented future-proofing.]
- No Python GCL validator (engine-delegated errors); no C++; no live network or real LLM in
  automated tests.

## B1 amendment this task needs

Engine-delegated error handling requires B1 (TASK-5.5) to provide an `EngineError` the
engine may raise + FakeEngine scripted-error support (already specced in B1).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 isj_agent/agents/searcher.py defines a Searcher with run(intent: str) -> SearcherResult (ranked_list + events), constructed with an injected OpenAI-compatible client + model and an injected SearchEngine (B1), loading its prompt from a bundled searcher.md.
- [ ] #2 The LLM is given exactly two tools: search (arg query: str) and judge (arg judgements: list of {docid, grade 0-4, reason}); one tool call per turn, no parallel calls; no read and no finish tool. The LLM-facing search tool maps to the engine's cover_search via the Protocol.
- [ ] #3 The model writes only the query; the controller injects exclude_docids = the accumulated judged set and supplies top_k and window from config defaults (asserted via FakeEngine.calls).
- [ ] #4 Judge-before-search guardrail: a search while surfaced passages are unjudged is refused (no engine call) with a tool message naming the docids, recorded as a bounce event, and the model recovers by judging.
- [ ] #5 Engine-delegated errors: engine.search raising EngineError produces a bounce event and feeds str(error) back as the tool result; the controller never crashes.
- [ ] #6 Judge handling records only docids that were SURFACED (in pending) and not yet judged; a hallucinated/un-surfaced docid is ignored (not added); each recorded judgement (grade 0 included) takes its summary and score from the surfaced Hit plus its surfacing query; an empty/all-duplicate/all-ignored judge counts as no progress.
- [ ] #7 Termination is controller-owned: stop on a no-tool-call turn (trailing prose discarded), or >=2 consecutive dry searches, or >=2 consecutive no-progress turns, or the search budget, or a hard max-turns cap; EVERY turn (including bounces) counts toward the turn cap, so repeated invalid-GCL or premature-search bounces cannot loop forever; a stop event records the reason.
- [ ] #8 The controller emits a structured trace = list[TraceEvent], each with type, ts (epoch seconds), duration_ms, and type-specific fields, returned in SearcherResult.events; this is a research artifact for later statistics. The taxonomy covers at least llm_turn (LLM latency, which tool), search (query/top_k/exclude_count/window + total_matches/unjudged_matches/returned/atom_counts + engine latency), judge (recorded count + grades), bounce (kind = judge_before_search | engine_error, message), and stop (reason).
- [ ] #9 run(intent) returns a RankedList of ALL judged passages (grade 0 included), ordered by grade desc then engine score desc, ranks assigned 1..N; RankedEntry.rank is the compiled per-intent rank, distinct from the engine Hit.rank (a per-search position).
- [ ] #10 isj_agent/protocol defines pydantic RankedEntry{rank,docid,grade(0-4),score,summary,reason,surfacing_query}, RankedList{intent,entries}, TraceEvent{type,ts,duration_ms,(+ type-specific fields via extra=allow)}, and SearcherResult{ranked_list,events}.
- [ ] #11 isj_agent/agents/searcher.md is built from the §3 prompt EMBEDDED in this task (the verbatim starting point), with ONLY the adaptations listed there applied: 0-3 -> 0-4 grades plus a 0-4 relevance rubric, the search-count line left advisory while the controller enforces the budget/turn cap, and everything else kept verbatim. The finished prompt is self-contained and contains the ISJ loop; a GCL cheatsheet using the word* family marker (full word + *), facet covers, and !> carve; the three-way term model (bare exact / word* family / (+ ) synonyms); a 0-4 relevance rubric; and the loop rules (judge before re-search, reformulate from what was read, stop when dry, stop = no tool call and write nothing). It never mentions porter: or index streams.
- [ ] #12 Tests use a stub LLM (scripted tool-call sequences) + the B1 FakeEngine and cover: the happy path (correctly ordered RankedList incl. grade 0, plus a SearcherResult.events list with the expected event types and recorded durations); judge-before-search bounce+recovery; EngineError bounce+recovery; stop-on-2-dry; no-progress stop; the max-turns cap terminating a repeated-bounce loop; search-budget cap; exclude_docids accumulation; a hallucinated un-surfaced docid not recorded; nothing surfaced left unjudged. No test contacts a network or a real model.
- [ ] #13 uv sync --project isj succeeds and uv run --directory isj pytest tests/ exits 0; isj/README.md documents the Searcher (run -> SearcherResult, the two tools, controller guardrails + termination incl. the turn cap, 0-4 grades, the structured event trace) and that read() stays on the engine Protocol as future-proofing, not exposed as an LLM tool yet.
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Python in isj/. Depends on B1 (incl. EngineError + FakeEngine scripted errors). Adapt.

1. uv sync --project isj. Read analyst.py + analyst.md (injected client/model + bundled
   prompt), B1's engine/ (Protocol + FakeEngine + EngineError) and protocol/search.py
   (types), docs/searcher-agent-lessons section 3 (the prompt, a dated 0-3 snapshot to adapt
   to 0-4), and isj/scouting/scout_searcher.py (the working loop prototype).
2. isj_agent/protocol/: add RankedEntry, RankedList, TraceEvent (extra="allow"; type, ts,
   duration_ms + type-specific fields), SearcherResult (ranked_list + events).
3. isj_agent/agents/searcher.py: the Searcher class + the loop controller (pseudocode in the
   description). Two tool schemas (search{query}; judge{judgements:[{docid,grade,reason}]});
   one tool call per turn; inject exclude_docids + config top_k/window; judge-before-search
   bounce; EngineError bounce; judge only surfaced+unjudged docids (resolve summary/score
   from the surfaced Hit); controller stops (no-tool-call / 2 dry / 2 no-progress / search
   budget / MAX-TURNS cap with bounces counting as turns); emit TraceEvents (ts +
   duration_ms; time the llm call and engine.search); compile_ranked_list sorted (grade desc,
   score desc), ranks 1..N. Validate judge args via the Judgement model (grade 0-4).
4. isj_agent/agents/searcher.md: author the prompt per the contract (word* GCL cheatsheet;
   three-way terms; 0-4 rubric; loop rules; no porter:/streams).
5. isj/tests/test_searcher.py: STUB LLM (a fake client whose chat.completions.create returns
   a SCRIPTED sequence of assistant turns with tool_calls, ending in a no-tool-call turn) +
   the B1 FakeEngine. Cover: happy path -> ordered RankedList (grade desc, score desc; grade
   0 retained) AND a SearcherResult.events list with the expected event types and recorded
   durations; judge-before-search bounce + recovery (bounce event); EngineError bounce +
   recovery (FakeEngine scripted error -> bounce event, then a real batch); stop-on-2-dry;
   no-progress stop; TURN-CAP stop (script repeated invalid-GCL/engine-error or premature
   searches and assert it terminates via turn_cap, not an infinite loop); search-budget cap;
   exclude_docids accumulates and is passed to engine.search (assert via FakeEngine.calls);
   a hallucinated (un-surfaced) docid in a judge call is NOT recorded; nothing surfaced left
   unjudged. No network/real model.
6. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: the Searcher
   (run -> SearcherResult), its two tools, the controller guardrails + termination (incl. the
   turn cap), the 0-4 grade scale, the structured event trace, and that read() stays on the
   engine Protocol as future-proofing (not exposed as an LLM tool yet). A real-LLM run is a
   manual step (the live integration gate is C3).
<!-- SECTION:PLAN:END -->
