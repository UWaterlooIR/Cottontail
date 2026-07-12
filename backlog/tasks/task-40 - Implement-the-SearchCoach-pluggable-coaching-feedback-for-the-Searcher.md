---
id: TASK-40
title: 'Implement the SearchCoach: pluggable coaching feedback for the Searcher'
status: Done
assignee: []
created_date: '2026-07-11 21:27'
updated_date: '2026-07-12 04:45'
labels: []
dependencies: []
ordinal: 54000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Implement the design in docs/design/search-coach.md. Today the Controller feeds the Searcher a mechanically-sliced view of the judged results (TASK-36); this replaces that with a pluggable SearchCoach that digests each query's judged results into high-value feedback. Two implementations behind one protocol: SearchCoachAgent (an LLM that writes a free-text, self-contained coaching report -- What's working / hurting / pursue next + verbatim Cited passages) and MechanicalSearchCoach (deterministic listing, the always-works fallback). Query-blind, atom-blind, engine-agnostic (serves cover/tiered/multitext/Lucindri). The coach shape (v6 free-text report) and its behavior were settled by the prompt-scouting in isj/scouting/search-coach/ (see captured/FINDINGS.md). Delivered in four phases (subtasks). References: docs/design/search-coach.md; isj/scouting/search-coach/prompt-v6.md; isj/isj_agent/controller.py.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The SearchCoach layer is implemented per docs/design/search-coach.md: SearchCoach protocol + MechanicalSearchCoach (fallback) + SearchCoachAgent (LLM), config-selected in [coach], with the mechanical fallback on any coach failure.
- [ ] #2 Context compaction (shrink-in-place) bounds the Searcher's cumulative context per the design; the coach layer is observable in the trace (purpose=coach, coach_fallback, compact).
- [ ] #3 The coach-on vs coach-off A/B has been run over the RAG25 dev topics and its results recorded.
<!-- AC:END -->
