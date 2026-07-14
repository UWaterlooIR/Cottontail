---
id: TASK-44.4
title: >-
  Rewrite search_coach.md for the report-writing goal + 3-part context (coach
  toward the target)
status: Done
assignee: []
created_date: '2026-07-14 04:45'
updated_date: '2026-07-14 05:26'
labels:
  - isj
  - coach
dependencies:
  - TASK-44.1
parent_task_id: TASK-44
ordinal: 65000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Reframe the LLM SearchCoach so its feedback is anchored to the report-writing goal and the 3-part context, coaching the searcher toward its Search Target.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 search_coach.md is reframed around the report goal and the 3-part context (request / analysis / Search Target) the coach now receives via {intent}
- [ ] #2 The coach advises progress toward the Search Target specifically (consistent with strictly-on-target searching), within the big-picture report goal
- [ ] #3 The CoachOutput contract (free-text report) and the MechanicalSearchCoach (format-only fallback) are unchanged
- [ ] #4 isj suite green (coach tests use stubs; add a light assertion that the new framing markers are present)
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
GOAL: Reframe the LLM SearchCoach so its between-query feedback is anchored to the report goal and coaches
the searcher toward its SEARCH TARGET. Depends on 44.1 ({intent} now carries the composed need). MUST use
the SAME grade rubric as 44.3 (shared meaning of grades). Consumes the parent CANONICAL need FORMAT.

FILE: isj_agent/agents/search_coach.md. Placeholders {intent} (=composed need), {novelty}, {passages}.
The MechanicalSearchCoach (search_coach.py, format-only, no LLM) needs NO change; CoachOutput/CoachContext
contracts UNCHANGED.

WHAT TO CHANGE (framing only; keep the four-section report shape + the 'stuck in a rut / plateau' coaching):
A) OPENING FRAME: currently 'find EVERY document relevant to an information need' -> 'find documents
   relevant to the SEARCH TARGET, which is one component of a report (up to ~1000 words) a generative AI
   will write for the user's request.' State the 3-part context it now sees via {intent}: USER REQUEST /
   ANALYSIS / SEARCH TARGET.
B) UPDATE THE GRADE LEGEND inside the prompt. Current text: '(0 = not relevant, 1 = marginal, 2 = relevant,
   3 = highly relevant)'. Replace with the 44.3 rubric: 0 = not relevant to the report; 1 = relevant to the
   report but NOT the SEARCH TARGET; 2 = relevant to the target; 3 = highly relevant to the target.
C) COACH TOWARD THE TARGET: 'what is working / hurting / pursue next' should push the searcher toward
   target-relevant (grade 2-3) material. Add an explicit rule: grade-1 passages are report-relevant but
   OFF THIS TARGET -- treat them as a signal the searcher is drifting to a sibling component (another
   searcher's job); advise steering BACK to the target, not chasing them. Keep 'relevant' in the coach's
   own language meaning target-relevant (>=2), consistent with stats['relevant'] (threshold=2 from 44.3).
D) Keep everything else: the resurfaced/novelty plateau logic, 'Vocabulary worth pursuing', the 'Cited
   passages' verbatim-excerpt rule, the ~200-400 word budget, no-source-preference rule.

TESTS: assert search_coach.md contains the report-goal + SEARCH TARGET framing and the updated legend.
Coach unit tests use stubs -> stay green. CoachOutput/CoachContext unchanged.

FORWARD/BACKWARD-COMPAT: the legend here MUST match 44.3 exactly (both define grade 1 = report-not-target).
Consistent with 44.2 (strictly-on-target). GOTCHA: only the SearchCoachAgent PROMPT changes -- no code, no
contract change; the mechanical coach is untouched.
<!-- SECTION:PLAN:END -->
