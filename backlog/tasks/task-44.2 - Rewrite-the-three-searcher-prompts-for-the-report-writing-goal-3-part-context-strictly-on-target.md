---
id: TASK-44.2
title: >-
  Rewrite the three searcher prompts for the report-writing goal + 3-part
  context (strictly on target)
status: Done
assignee: []
created_date: '2026-07-14 04:44'
updated_date: '2026-07-14 05:26'
labels:
  - isj
  - searcher
dependencies:
  - TASK-44.1
parent_task_id: TASK-44
ordinal: 63000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Reframe the cover/GCL, MultiText, and Lucindri searcher prompts so the searcher understands it is collecting source documents for a generative AI to write the <=1000-word report, sees the request + analysis + Search Target, and searches STRICTLY for its target.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 searcher.md (cover/GCL), mt_tiered_searcher.md, and lucindri_searcher.md are reframed around the report-writing goal and the 3-part context (request / analysis / Search Target)
- [ ] #2 Each prompt instructs the searcher to stay STRICTLY on the Search Target -- the request+analysis are context to interpret the target, not license to drift to sibling components (those are other searchers' jobs); do NOT broaden to the whole report
- [ ] #3 The query-language mechanics for each searcher (GCL cover / MultiText DSL / Lucindri/Indri) are preserved unchanged; only the goal/context framing changes
- [ ] #4 tiered_searcher.md is intentionally left out of scope (not one of the arms we run)
- [ ] #5 isj suite green (existing searcher tests use stubs; add a light assertion that the new framing markers are present)
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
GOAL: Reframe the three searcher prompts we run so the searcher (1) knows it is collecting source
documents for a generative AI to write a <=1000-word report, (2) understands the 3-part context it now
receives, and (3) searches STRICTLY for its SEARCH TARGET. Depends on 44.1 (the need format + that the
need is delivered as the searcher's first user message). Consumes the parent CANONICAL need FORMAT.

FILES: isj_agent/agents/searcher.md (cover/GCL), mt_tiered_searcher.md, lucindri_searcher.md.
OUT OF SCOPE: tiered_searcher.md (not one of the arms we run).

HOW THE SEARCHER SEES CONTEXT (from 44.1): the FIRST user message is the composed need, with labeled
sections USER REQUEST / ANALYSIS (all components, target marked) / SEARCH TARGET. Subsequent turns are the
tool results (coach feedback). So the SYSTEM prompt explains the ROLE + rules; the need supplies specifics.

WHAT TO ADD/CHANGE IN EACH system prompt (framing only; keep the query-language teaching intact):
- Overall goal: 'You are collecting source documents that a generative AI will use to write a report (up
  to ~1000 words) answering the user's request. You do NOT write the report; you find the information.'
- Describe the input: 'You are given the USER REQUEST (big picture), the ANALYSIS (all components the
  report was broken into), and your SEARCH TARGET (the one component to find information for now).'
- STRICTLY ON TARGET: 'Search only for your SEARCH TARGET. The USER REQUEST and ANALYSIS are context so
  you interpret the target correctly within the big picture -- NOT license to search for other components
  or the whole report. A document useful to the report but off your target is another searcher's job.'
  (This pairs with 44.3's rubric: your job is to maximize grade-2/3 target-relevant docs, not grade-1.)
- Relevance framing: 'a hit is valuable if it helps the report cover YOUR target.'

PRESERVE per searcher (do NOT rewrite the query languages):
- searcher.md: GCL cover-query operators + examples.
- mt_tiered_searcher.md: MultiText DSL (macros, @rank, compile-diagnostics self-correction loop) + KEEP the
  reasoning_effort=medium caution.
- lucindri_searcher.md: the self-contained Indri/Lucindri query language.

TESTS: a light test asserting each of the three prompts contains the report-goal + SEARCH TARGET framing
(a distinctive phrase). Existing searcher tests use stub LLMs -> stay green.

FORWARD/BACKWARD-COMPAT: uses the parent's stable section labels (USER REQUEST / ANALYSIS / SEARCH TARGET)
so the prompt wording matches 44.1's need. Consistent with 44.4 (coach also pushes strictly-on-target) and
44.3 (threshold=2 rewards only target-relevant). GOTCHA: framing only; if a query language changes, that is
a different task.
<!-- SECTION:PLAN:END -->
