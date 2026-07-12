---
id: TASK-40.1
title: 'SearchCoach phase 1: extract SearchCoach protocol + MechanicalSearchCoach'
status: Done
assignee:
  - '@claude'
created_date: '2026-07-11 21:30'
updated_date: '2026-07-12 00:02'
labels: []
dependencies: []
parent_task_id: TASK-40
ordinal: 55000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Refactor the Controller's feedback assembly (_summarize / _select_feedback in isj/isj_agent/controller.py) behind a SearchCoach protocol, with MechanicalSearchCoach as the deterministic, always-works implementation (top top_results_to_show by rank + deeper results graded >= min_show_grade, emitted as a plain passage listing: handle, grade, reason, verbatim excerpt). Move top_results_to_show/min_show_grade from [loop] to [coach.mechanical] (keep a deprecated [loop] shim for one release). This is the fallback that later phases fall back to. See docs/design/search-coach.md (Interfaces, Implementations, Configuration).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A SearchCoach Protocol exists; MechanicalSearchCoach implements it and the Controller uses it to build the Searcher feedback.
- [x] #2 MechanicalSearchCoach is a pure function of its context (no LLM, cannot fail) and produces the top-N + high-grade-nuggets passage listing.
- [x] #3 top_results_to_show/min_show_grade are read from [coach.mechanical] (with a deprecated [loop] fallback); config.example.toml documents the [coach] and [coach.mechanical] blocks.
- [x] #4 Tests cover the mechanical coach's selection and the Controller wiring; the isj suite passes.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
GOAL: extract today's Searcher-feedback assembly behind a SearchCoach protocol, with MechanicalSearchCoach as the deterministic fallback, and make searcher.md format-agnostic so the feedback shape is decoupled from the prompt. Design: docs/design/search-coach.md (read "The coach output", "What the Searcher sees", "Interfaces", "Implementations", "Configuration", rollout step 1).

READ FIRST (current code being changed):
- isj/isj_agent/controller.py: run() (the msgs loop; the tool reply is appended at the line `self._tool(msgs, pr.tool_call_id, outcome)`), _descend() (builds the `descended` list, returns self._summarize(...)), _summarize() + _select_feedback() (the assembly to EXTRACT), _relevant(), _tool().
- isj/isj_agent/config.py build_engine() (the load_class + `if cls is X: return build_x()` dispatch to MIRROR for build_coach) and cli.py (Controller(...) construction; _build_agent).
- The agnostic-prompt exemplars: isj/isj_agent/agents/tiered_searcher.md, mt_tiered_searcher.md, lucindri_searcher.md (they describe the returned feedback in prose). Contrast the rigid PART 2 JSON block in searcher.md.

EXACT DATA SHAPES:
- descended item (from controller._descend): {"rank": int (TRUE global rank), "id": str (the docno), "score": float, "grade": int in -2..3, "summary": str (passage excerpt), "reason": str (assessor reason), "is_new": bool}. NOTE keys are `id` and `is_new` (a revisit is is_new=False).
- today's _summarize dict (what the mechanical path must reproduce, composed with the Controller header): {**queryable.trace_arguments() (cover -> {"query": qs}; tiered -> {"tiers":[...]}), "atom_counts":[...] iff present, "total_matches": int iff present, "descended": {count,relevant,shown,hidden}, "results":[{rank,score,summary,reason,grade}...]}.

STEPS:
1. NEW isj/isj_agent/agents/search_coach.py:
   - @dataclass CoachContext: intent:str; stats:dict {count:int, relevant:int, total_matches:int|None}; results:list[dict] (the full descended list). NO query, NO atom_counts (query-blind, atom-blind).
   - @dataclass CoachOutput: report:str; referenced:list[str] (docnos). (Phase 2 will add optional usage/reasoning fields for the trace.)
   - class SearchCoach(Protocol): coach(self, ctx:CoachContext)->CoachOutput.
   - module fn select(results, top_k, min_grade)->list[dict]: return [d for pos,d in enumerate(results) if pos<top_k or d["grade"]>=min_grade]  (this IS today's _select_feedback; both coaches use it).
   - class MechanicalSearchCoach: __init__(self,*,top_results_to_show=10,min_show_grade=3). coach(ctx): shown=select(ctx.results,self.top_results_to_show,self.min_show_grade); report = a markdown listing, one block/doc: f"[rank {d['rank']}] grade={d['grade']} score={d['score']:.3f}\n  {d['summary']}\n  (assessor: {d['reason']})"; referenced=[d['id'] for d in shown]. Pure code, cannot raise.

2. Controller (controller.py):
   - __init__: ADD param coach:SearchCoach (built by cli). REMOVE top_results_to_show, min_show_grade (moved to MechanicalSearchCoach). KEEP relevant_grade_threshold (used by _relevant / streak).
   - _descend: change its success return from self._summarize(...) to a plain dict {"descended":descended, "atom_counts":atom_counts, "total_matches":total_matches}. KEEP the malformed-query bounce return {"error":msg} unchanged.
   - run(): at the current `self._tool(msgs, pr.tool_call_id, outcome)` site: if "error" in outcome -> pass through (bounce, unchanged). Else: ctx = CoachContext(intent=intent, stats={"count":len(outcome["descended"]), "relevant":sum(1 for d in outcome["descended"] if self._relevant(d["grade"])), "total_matches":outcome["total_matches"]}, results=outcome["descended"]); out=self.coach.coach(ctx); content=self._compose_feedback(pr.queryable, outcome["atom_counts"], ctx.stats, out); self._tool(msgs, pr.tool_call_id, content).
   - NEW Controller._compose_feedback(queryable, atom_counts, stats, out)->str: a markdown string = header (f"Your query: {queryable.query_string()}"; coverage f"judged {stats['count']} docs, {stats['relevant']} relevant; total corpus matches {stats['total_matches']}"; atom matches ONLY if atom_counts is not None -> f"atom matches: " + ", ".join(f"{a['term']}={a['count']}" ...)) + "\n\n" + out.report. Because searcher.md is agnostic this text is read directly.
   - _tool: change to send a STRING content directly (today it json.dumps a dict). Make it: content is str -> use as-is; dict -> json.dumps (keep for the {"error":...} bounce path which stays a dict/json). msgs.append({"role":"tool","tool_call_id":tid,"content": content if isinstance(content,str) else json.dumps(content)}).
   - DELETE _summarize + _select_feedback (logic now in MechanicalSearchCoach + select()). KEEP _relevant, _compile.

3. searcher.md: rewrite PART 2 ("WHAT THE cover_search TOOL RETURNS") to prose, matching tiered_searcher.md style: drop the JSON block; say "after each query you get a summary of what it found -- the top-ranked results with their relevance grades (0=irrelevant..3=highly relevant) and the assessor's one-line reason for each, plus coverage stats (how many judged, how many relevant) and (Cottontail only) per-term atom counts; a term with 0 atom matches is dead -- fix it. Read the summaries first to mine vocabulary; broaden a dry query, narrow a noisy one." Leave PART 1/3/4 intact.

4. Config + cli:
   - config.py: build_coach(config)->SearchCoach dispatching on config.get("coach",{}).get("class","...MechanicalSearchCoach"): here build MechanicalSearchCoach(top_results_to_show=[coach.mechanical].top_results_to_show or 10, min_show_grade=... or 3). (SearchCoachAgent branch added in phase 2.) Mirror build_engine's load_class + `if cls is X` dispatch.
   - Move top_results_to_show/min_show_grade to [coach.mechanical]; keep a deprecated fallback reading them from [loop] for one release.
   - cli.py: coach = build_coach(config); pass coach=coach to Controller(...); remove the top_results_to_show/min_show_grade args from the Controller(...) call.
   - config.example.toml: add [coach] (class = ...MechanicalSearchCoach default) + [coach.mechanical] (top_results_to_show=10, min_show_grade=3) with comments; note the [loop] migration.

5. Tests:
   - test_controller.py: the payload-shape tests assert the OLD JSON dict (keys query/descended/results) captured by StubSearcher from the tool message. The tool content is now a STRING (markdown), so update: StubSearcher.propose reads the last tool message content as a string (json.loads will fail -> stop json-decoding it); assert the string contains the query echo, the coverage counts, and the shown docs. Preserve the TASK-36 mechanical-selection worked example (top=5,min=3 over grades 0 0 1 0 2 0 3 1 2 0 0 1 2 0 1 2 3 0 0 3 0 0 1 -> shown grades 0 0 1 0 2 3 3 3 at ranks 1,2,3,4,5,7,17,20) as a MechanicalSearchCoach/select() unit test.
   - NEW tests/test_search_coach.py: select() worked example; MechanicalSearchCoach.coach report + referenced.
   - full isj suite green: uv run --directory isj pytest.

GOTCHAS/DECISIONS: descended keys are `id`+`is_new` (not docno/revisit). searcher.md agnostic is owner-approved -- do NOT preserve the JSON contract. Feedback becomes a markdown STRING (forward-compatible with the coach's markdown report); _tool sends str content directly. relevant_grade_threshold (default 1) stays on the Controller.

FORWARD-COMPAT (phase 2): the run() flow is now `out=self.coach.coach(ctx); content=self._compose_feedback(...); self._tool(...)`. Phase 2 swaps MechanicalSearchCoach->SearchCoachAgent (out.report becomes the coaching report); _compose_feedback + _tool + agnostic searcher.md unchanged. Phase 2 adds a `mechanical` fallback slot to the Controller. CoachContext/CoachOutput/select() are established here.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented. New isj_agent/agents/search_coach.py: SearchCoach Protocol + CoachContext/CoachOutput + select() + MechanicalSearchCoach (pure, cannot fail; forwards top-N + high-grade nuggets as a markdown listing). Controller: _descend now returns the raw {descended,atom_counts,total_matches}; run() builds CoachContext and calls self.coach.coach(ctx); new _compose_feedback wraps the coach report with the query echo + coverage + (Cottontail-only) atom counts as a STRING; _tool sends a str as-is (dict json.dumps for the {error} bounce); _summarize/_select_feedback deleted. searcher.md PART 2 rewritten to agnostic prose (no JSON spec). config.py build_coach (MechanicalSearchCoach; [coach.mechanical] with deprecated [loop] fallback); cli.py wires coach=build_coach(config); config.example [coach]/[coach.mechanical] documented. Tests: new tests/test_search_coach.py (select worked example, defaults, prior-judged-in-top-band, mechanical report/referenced/empty); test_controller.py payload-shape tests rewritten to string assertions; TASK-36 selection tests moved to test_search_coach. Full suite 191 passed / 1 skipped. build_coach smoke: [coach.mechanical]/[loop]-fallback/default/explicit-class all resolve; sample report renders.

DEVIATION from the plan (noted): kept top_results_to_show/min_show_grade as Controller __init__ params that AUTO-BUILD a default MechanicalSearchCoach when no explicit coach is passed -- avoids breaking the many Controller(...)/ _ctl(...) test constructions on signature. The feedback LOGIC still moved to the coach; the CLI injects an explicit coach via build_coach. Feedback is now a markdown STRING (forward-compatible with the coach's report), per the searcher.md-agnostic decision.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Extracted the Searcher-feedback assembly behind a SearchCoach protocol with MechanicalSearchCoach as the deterministic fallback, and made searcher.md format-agnostic so the feedback shape is decoupled from the prompt. Feedback is now a markdown string (query echo + coverage + atom counts + the coach report). Config: [coach]/[coach.mechanical] with a deprecated [loop] fallback; cli injects the coach. 191 tests pass. Sets the seam for phase 2 (SearchCoachAgent) to swap in.
<!-- SECTION:FINAL_SUMMARY:END -->
