---
id: TASK-40.1
title: 'SearchCoach phase 1: extract SearchCoach protocol + MechanicalSearchCoach'
status: To Do
assignee: []
created_date: '2026-07-11 21:30'
updated_date: '2026-07-11 21:50'
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
- [ ] #1 A SearchCoach Protocol exists; MechanicalSearchCoach implements it and the Controller uses it to build the Searcher feedback.
- [ ] #2 MechanicalSearchCoach is a pure function of its context (no LLM, cannot fail) and produces the top-N + high-grade-nuggets passage listing.
- [ ] #3 top_results_to_show/min_show_grade are read from [coach.mechanical] (with a deprecated [loop] fallback); config.example.toml documents the [coach] and [coach.mechanical] blocks.
- [ ] #4 Tests cover the mechanical coach's selection and the Controller wiring; the isj suite passes.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Enabled by the owner decision: make searcher.md FORMAT-AGNOSTIC (like tiered_searcher.md / mt_tiered_searcher.md / lucindri_searcher.md), so the Searcher stops over-specifying the JSON feedback and any coach output shape works. Then this refactor is safe.

1. New module isj_agent/agents/search_coach.py:
   - CoachContext (query-blind, atom-blind): intent:str; stats:dict {count, relevant, total_matches}; results:list[dict] = the query's descent in rank order ({docno, rank, score, grade, summary, reason, revisit}). NO query, NO atom_counts.
   - CoachOutput: report:str (the coach's contribution to the tool message) + referenced:list[str] (docnos, for logging).
   - SearchCoach Protocol: coach(ctx)->CoachOutput.
   - MechanicalSearchCoach(top_results_to_show=10, min_show_grade=3, relevant_grade_threshold=1): coach(ctx) applies today's select rule (pos<top_results_to_show OR grade>=min_show_grade over ctx.results, rank order preserved) and formats the shown docs as a plain markdown listing (per doc: true rank, grade, score, summary, reason). report=listing; referenced=shown docnos. Pure code, cannot fail.

2. Controller (controller.py): __init__ gains coach:SearchCoach; drop top_results_to_show/min_show_grade (they move onto MechanicalSearchCoach); keep relevant_grade_threshold (streak logic). After _descend yields `descended` (+ atom_counts, total_matches), build ctx=CoachContext(intent, stats, results=descended), out=coach.coach(ctx), and compose the tool-message content = a short markdown header (Your query; coverage: descended K, R relevant; atom matches term=count... ONLY if the engine returned them) + out.report; _tool(msgs, tool_call_id, content). Keep the malformed-query bounce/error path (an error string). Delete _summarize/_select_feedback (moved to the mechanical coach); keep _relevant.

3. searcher.md: rewrite Part 2 to be agnostic prose (drop the field-by-field JSON block); keep the read-summary-first / mine-vocabulary / broaden-narrow guidance.

4. Config + cli: build_coach(config) in config.py dispatching on [coach].class (MechanicalSearchCoach here); [coach.mechanical] gets top_results_to_show/min_show_grade migrated out of [loop] (keep a deprecated [loop] fallback one release); cli builds the coach and passes it to Controller; document [coach]/[coach.mechanical] in config.example.toml.

5. Tests: update the test_controller payload-shape tests (asserted the exact JSON dict) to the new text feedback (assert query echo + coverage + shown docs appear, not exact fields); add MechanicalSearchCoach selection tests (the TASK-36 worked example still holds); full isj suite green.

FORWARD-COMPAT (phase 2): the Controller composes header + coach.report and appends via _tool -> phase 2 just swaps MechanicalSearchCoach for SearchCoachAgent (report=markdown report); searcher.md already agnostic so no further prompt change. CoachOutput{report,referenced} + the coach-injection seam are set here. The `mechanical` fallback slot is added in phase 2 (here coach IS the mechanical).
<!-- SECTION:PLAN:END -->
