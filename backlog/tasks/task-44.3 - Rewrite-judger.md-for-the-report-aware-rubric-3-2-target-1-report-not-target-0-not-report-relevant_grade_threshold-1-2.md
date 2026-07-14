---
id: TASK-44.3
title: >-
  Rewrite judger.md for the report-aware rubric (3/2 target, 1
  report-not-target, 0 not-report) + relevant_grade_threshold 1->2
status: Done
assignee: []
created_date: '2026-07-14 04:45'
updated_date: '2026-07-14 05:26'
labels:
  - isj
  - judger
dependencies:
  - TASK-44.1
parent_task_id: TASK-44
ordinal: 64000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Reframe the Judger around the report-writing goal and give it the report-aware rubric, and reconcile the non-relevant-streak threshold so only target-relevant docs keep a query descending.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 judger.md is reframed around the report goal and the 3-part context (request / analysis / Search Target) the Judger now receives via {intent}
- [ ] #2 The rubric is: 3 = highly relevant to the Search Target; 2 = relevant to the target; 1 = relevant to the report (request/analysis) but NOT the target; 0 = not relevant to the report
- [ ] #3 The Verdict schema stays 0-3 (no code change); the -2 failure sentinel stays controller-side
- [ ] #4 relevant_grade_threshold default changes 1 -> 2 so only target-relevant docs (>=2) keep the non-relevant streak descending; grade-1 (report-relevant, off-target) does not reset it
- [ ] #5 config.example.toml [loop] documents the new default; isj suite green (judger + controller tests updated)
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
GOAL: Report-aware judging. The Judger now receives the composed need (USER REQUEST / ANALYSIS / SEARCH
TARGET) in {intent} (from 44.1) and grades a document's usefulness for writing the report on the target.
Depends on 44.1. Consumes the parent CANONICAL need FORMAT + RUBRIC/THRESHOLD COHERENCE.

FILE: isj_agent/agents/judger.md. Placeholders {intent}, {summary}, {document} (filled by _fill via
str.replace). Verdict schema UNCHANGED (Literal[0,1,2,3]).

A) REWRITE THE GRADE LEGEND (currently: 0 Irrelevant / 1 Related / 2 Partial / 3 Highly relevant) TO:
   3 = highly relevant to the SEARCH TARGET (directly, substantially answers the target component).
   2 = relevant to the SEARCH TARGET (helps cover the target, partially or with useful detail).
   1 = relevant to the REPORT (the USER REQUEST / ANALYSIS) but NOT to the SEARCH TARGET (useful for some
       OTHER component, off this target).
   0 = not relevant to the report at all.
B) REFRAME the reasoning steps + the {intent} section header. The {intent} block now carries the request,
   the analysis, and the SEARCH TARGET (relabel 'QUESTION / INTENT:' -> e.g. 'REPORT CONTEXT AND SEARCH
   TARGET:'). Step 1 (Intent): 'what would satisfy the SEARCH TARGET, within the report.' Keep the trust +
   full-document-scope steps (steps 3-4) intact. Make explicit: the report goal is a generative AI writing
   a <=1000-word report; grade usefulness for that, with the SEARCH TARGET as the specific component now.
C) Keep the cover-biased-passage caveat and 'judge the FULL document' rule.

THRESHOLD CHANGE (relevant_grade_threshold 1 -> 2) in ALL of:
  - controller.py __init__: relevant_grade_threshold: int = 1  -> 2   (line ~99)
  - cli.py: loop_cfg.get(\"relevant_grade_threshold\", 1) -> 2          (line ~114)
  - config.example.toml [loop]: '# relevant_grade_threshold = 1 ...' -> '= 2' + note the new rubric meaning
    (non-relevant-for-the-streak = grade < 2, i.e. only target-relevant docs keep a query descending).  (line ~116)
Rationale: _relevant(grade)=grade>=threshold drives (a) the non-relevant streak and (b) stats['relevant']
shown to the coach. Under the new rubric grade 1 = off-target-report-relevant; with a STRICTLY-on-target
searcher, letting grade-1 reset the streak would hold an unproductive query. threshold=2 => only target-
relevant (2/3) counts. NOTE: the coach SHOW knobs min_show_grade / input_min_grade (default 3) are SEPARATE
and NOT changed.

RETAIN-ALL NOTE (see parent OPEN DESIGN ITEM): grade-1 docs are still RECORDED in the target's RankedList
(ranked below 2/3 by grade). We do NOT change retain-all here; downstream (submission builder) can filter
grade>=2 for a target-only list. Flag if the user wants per-target lists to exclude grade-1.

TESTS:
  - judger.md contains the new legend markers (3/2 = target, 1 = report-not-target, 0 = not-report).
  - controller streak test with relevant_grade_threshold=2: a grade-1 doc does NOT reset the non-relevant
    streak; a grade-2 does. (Add/adjust; no existing test pins the old default of 1 -- verified.)
  - Verdict still validates 0-3; the -2 sentinel path is unchanged.
  Run `uv run pytest` -> green.

FORWARD/BACKWARD-COMPAT: consistent with 44.2 (searcher maximizes 2/3, not 1) and 44.4 (coach legend +
'off-target is another searcher's job'). The 44.4 coach legend MUST be updated to the SAME rubric wording;
both prompts share the meaning of grade 1. GOTCHA: Verdict stays Literal[0,1,2,3] -- prompt + threshold only.
<!-- SECTION:PLAN:END -->
