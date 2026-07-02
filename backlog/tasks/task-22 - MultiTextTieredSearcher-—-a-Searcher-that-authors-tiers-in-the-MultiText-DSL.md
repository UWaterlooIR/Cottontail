---
id: TASK-22
title: MultiTextTieredSearcher — a Searcher that authors tiers in the MultiText DSL
status: To Do
assignee: []
created_date: '2026-07-02 16:10'
labels:
  - enhancement
dependencies:
  - TASK-18
  - TASK-19
references:
  - isj/scouting/multitext-dsl/captured/FINDINGS.md
  - src/mt.cc
  - apps/mt-compile.cc
priority: medium
ordinal: 36000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A THIRD, interchangeable Searcher implementation (alongside the plain Searcher and the JSON TieredSearcher/TASK-20). Instead of emitting a JSON `tiers: [string]` list, the librarian writes a MultiText DSL PROGRAM — `name = expr` macros over `+` (OR), `^` (AND), `<>` (followed-by), `( ) < [N]` (proximity), quoted literals — ending in `@rank t0 t1 ...` (tiers, most precise first). Cottontail ALREADY compiles this DSL: src/mt.cc (Mt::infix_expression) parses it and emits GCL with bool+error validity; apps/mt.cc drives macros+@rank into tiered_ranking (the TASK-19 cascade). Motivation: the multitext-dsl scouting found this path beats the JSON-tool tiered designs — 100%% compile, 0 timeouts, ~16x faster, cleaner query craft (isj/scouting/multitext-dsl/captured/FINDINGS.md). Scope: build on a SEPARATE branch, later; it is a pluggable BaseSearcher variant to be A/B-tested against the JSON TieredSearcher and the plain Searcher. Do on top of the medium-effort default already set project-wide.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 New class (e.g. isj_agent.agents.mt_tiered_searcher.MultiTextTieredSearcher) subclasses BaseSearcher, is config-selectable via [agents.searcher].class, and needs NO base/controller changes
- [ ] #2 It exposes a single tool that accepts a MultiText DSL program (macros + an @rank tier line), NOT a JSON tiers list
- [ ] #3 The program is compiled+validated server-side via Cottontail's Mt (src/mt.cc); a compile error is bounced back to the model as the tool result for self-correction (//apps:mt-compile is the warren-free oracle usable in tests)
- [ ] #4 The compiled tiers feed the SAME tiered_query_search cascade (TASK-19) so ranking, summaries, and atom_counts behave identically to the JSON TieredSearcher
- [ ] #5 Prompt is the validated librarian prompt (isj/scouting/multitext-dsl/librarian-prompt.md) adapted to a single-statement Analyst intent; reasoning_effort defaults to medium
- [ ] #6 An A/B procedure compares MultiTextTieredSearcher vs the JSON TieredSearcher vs the plain Searcher on the same scoped needs (query validity, retrieval quality, latency) and reports results
- [ ] #7 Unit tests (emits a valid program; compile-error bounce path) plus the full isj pytest suite pass
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Do on a dedicated branch, later. 1) mt_tiered_searcher.py: BaseSearcher subclass with a program-carrying query type (a new Queryable whose tool takes {program: string}); prompt from librarian-prompt.md. 2) Server/handler: compile the program via Mt; on error return the diagnostic as the tool result (bounce); on success run the tiers through the existing tiered_query_search cascade. 3) Reuse //apps:mt-compile semantics for a unit-level validity oracle. 4) A/B harness in isj/scouting or isj/tests comparing the three searchers. Refs: FINDINGS.md, src/mt.{h,cc}, apps/mt.cc, apps/mt-compile.cc, docs/trec4/.
<!-- SECTION:PLAN:END -->
