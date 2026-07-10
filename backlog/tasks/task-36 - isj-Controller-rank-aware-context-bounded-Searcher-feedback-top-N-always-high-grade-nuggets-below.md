---
id: TASK-36
title: >-
  isj Controller: rank-aware, context-bounded Searcher feedback (top-N always +
  high-grade nuggets below)
status: In Progress
assignee:
  - '@claude'
created_date: '2026-07-10 17:16'
updated_date: '2026-07-10 17:29'
labels: []
dependencies: []
ordinal: 50000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Today the controller feeds the Searcher back EVERY newly-judged doc from a query's descent (150-190/query), which balloons the Searcher's accumulating context: a real run (topic 14, multitext) overflowed gpt-oss-120b's 131072 limit at turn 3 with input length 153192 after only ~456 judged docs -- so max_judgments=1000 is unreachable. This reshapes the per-query feedback so the agent (a) ALWAYS sees the top of its query's ranking (including docs already judged in prior queries) to understand what its query is doing, and (b) still sees any high-grade 'nuggets' found deeper down (for vocabulary), while keeping the context bounded. Implements the deferred Searcher context-budget fix. Relevant code: isj/isj_agent/controller.py (_descend builds again/fresh, _summarize builds the tool-result payload); config wiring in cli.py + config.example.toml; Searcher prompt docs (agents/searcher.md, tiered_searcher.md, mt_tiered_searcher.md) that describe the result shape.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Each query's Searcher feedback is built from that query's FULL descended ranking in true rank order (global descent position 1..K, consistent across fetch-refills), INCLUDING docs already judged in prior queries (formerly counted-only revisits).
- [x] #2 The feedback shows the first min(top_results_to_show, K) descended docs regardless of grade, then below that band shows only docs with grade >= min_show_grade; each shown doc reports its TRUE rank (never renumbered for skipped docs), score, summary, reason, and grade -- for both new and already-judged docs.
- [x] #3 top_results_to_show and min_show_grade are Controller parameters, configurable via [loop], with defaults 10 and 3, documented in config.example.toml.
- [x] #4 The feedback retains a compact aggregate (docs descended K, number relevant, number shown vs hidden) so the agent knows depth/coverage though not all docs are shown.
- [x] #5 Worked example holds: grades by rank 0 0 1 0 2 0 3 1 2 0 0 1 2 0 1 2 3 0 0 3 0 0 1 with top_results_to_show=5 and min_show_grade=3 => shown docs have grades 0 0 1 0 2 3 3 3 at ranks 1,2,3,4,5,7,17,20.
- [x] #6 The Searcher prompt docs (searcher.md, tiered_searcher.md, mt_tiered_searcher.md) are updated to describe the new top-N-plus-nuggets feedback and the rank semantics.
- [x] #7 Tests cover the selection rule (the worked example), rank preservation across a fetch-refill boundary, an already-judged doc appearing in the top band, and the config defaults; the existing isj suite passes.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. _descend: accumulate a rank-ordered 'descended' list. In the wave loop, for EVERY doc processed (in rank order), append {rank: depth, id, score, grade, summary, reason, is_new}: new docs take grade/reason from the fresh verdict v; already-judged docs take grade/reason from the stored judged[id] verdict and summary/score from the current Hit. (depth is the global descent position, so it is the true cross-refill rank.)

2. _select_feedback(descended, top_n, min_grade): return the shown subset -- position < top_n (i.e. ranks 1..top_n) shown regardless of grade; deeper docs shown only if grade >= min_grade. Preserve rank order and each doc's true rank.

3. Rework _summarize -> emit the selected 'results' list (field order rank, score, summary, reason, grade -- passage before verdict) plus an aggregate {depth_judged: K, relevant: R, shown: S, hidden: K-S}. Keep queryable.trace_arguments(), atom_counts, total_matches as today. Drop the old new_results/already_judged shape.

4. Controller.__init__: add top_results_to_show=10, min_show_grade=3 params; thread into _descend/_summarize. cli.py: read from [loop] (loop_cfg.get). config.example.toml: document both under [loop].

5. Prompts: update agents/searcher.md, tiered_searcher.md, mt_tiered_searcher.md sections that describe the tool result so the agent understands top-N-always + grade>=min_show_grade nuggets + true ranks + the aggregate.

6. Tests (test_controller.py): the worked example selection (0 0 1 0 2 0 3 1 2 0 0 1 2 0 1 2 3 0 0 3 0 0 1 / top=5 min=3 -> grades 0 0 1 0 2 3 3 3 at ranks 1,2,3,4,5,7,17,20); rank preserved across a fetch-refill boundary (docno in fetch 2 reports rank fetch1_len+pos, not its per-fetch Hit.rank); an already-judged (prior-query) doc appears in the top band with its grade; defaults are 10/3. Full suite green; optional live e2e to confirm the 456-doc overflow is gone.

Decisions: rank = global descent position (fixes the per-fetch Hit.rank the old code reported); keep an aggregate line; show summary+reason for all shown docs (owner-confirmed).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented. controller.py: _descend now accumulates a rank-ordered 'descended' list (rank=global depth, so ranks are true across fetch-refills) capturing every processed doc -- new (verdict) and already-judged (stored judged[id] verdict) -- with rank/id/score/grade/summary/reason/is_new. New _select_feedback() shows positions < top_results_to_show regardless of grade, plus deeper docs with grade >= min_show_grade. _summarize() now emits {descended:{count,relevant,shown,hidden}, results:[{rank,score,summary,reason,grade}]}, replacing new_results/already_judged; queryable fields + atom_counts + total_matches unchanged. Controller gains top_results_to_show=10, min_show_grade=3; wired from [loop] in cli.py; documented in config.example.toml. Prompts updated: searcher.md (result-shape block + task-recap line), tiered_searcher.md (PART 3), mt_tiered_searcher.md (intro). Tests: 4 pre-existing payload-shape tests updated to descended/results; 5 new (worked example 0 0 1 0 2 0 3 1 2 0 0 1 2 0 1 2 3 0 0 3 0 0 1 / top=5 min=3 -> grades 0 0 1 0 2 3 3 3 at ranks 1,2,3,4,5,7,17,20; default 10/3; true rank across a fetch-refill; prior-judged doc shown in top band; defaults). Full suite 181 passed / 1 skipped. Live e2e on topic 14 (the multitext run that previously overflowed 131072 at 456 docs) in progress to confirm the Searcher context stays bounded.
<!-- SECTION:NOTES:END -->
