---
id: TASK-40.4
title: 'SearchCoach phase 4: coach-on vs coach-off A/B on the dev topics'
status: To Do
assignee: []
created_date: '2026-07-11 21:30'
updated_date: '2026-07-11 22:10'
labels: []
dependencies:
  - TASK-40.2
parent_task_id: TASK-40
ordinal: 58000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Evaluate the coach: run coach-on (SearchCoachAgent) vs coach-off (MechanicalSearchCoach) over the 22 RAG25 dev topics and compare recall@k against the ClimbMix dev qrels, turns-per-intent, no_query rate, and whether the coach's recommended vocabulary appears in gold-relevant documents. Record results. Dev data + qrels live in the trec-rag-2026 repo. See docs/design/search-coach.md (Rollout step 4).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 coach-on vs coach-off has been run over the RAG25 dev topics with results recorded (recall@k, turns-per-intent, no_query rate, coach-vocabulary-in-gold).
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Coach-on vs coach-off A/B on the 22 RAG25 dev topics.

1. Two configs, identical except [coach].class: coach-on = SearchCoachAgent, coach-off = MechanicalSearchCoach (== the phase-1 baseline).

2. Eval pipeline (DOES NOT EXIST YET -- the main effort/risk; likely belongs in the trec-rag-2026 repo and may warrant its own task there):
   a. batch runner: run isj_agent.cli over each dev-topic narrative (rag25-topics-dev.tsv) with each config -> per-topic run-output dirs;
   b. fusion: combine each run's per-intent judged ranked lists into ONE TREC run per topic -- fusion policy is a real design choice (RRF vs grade-then-score); decide before implementing;
   c. scoring: score the fused runs vs the ClimbMix dev qrels (prefer qwen3.5-9b-v2 / codex) with ir_measures/trec_eval -- recall@k, nDCG@10/20;
   d. behavioral metrics from the traces: turns-per-intent, no_query bounce rate; plus whether the coach's recommended vocabulary appears in gold-relevant docs.

3. Run both arms, record results (findings doc + task notes), compare. Caveats: pooled qrels (unjudged treated non-relevant -> RELATIVE A/B, not absolute); analyst temp already 0 (TASK-38) so decompositions are stable across arms.

FLAG for the owner: this phase is an experiment that needs the eval pipeline (2b/2c/2d) built first. Recommend splitting the pipeline into its own task (in trec-rag-2026) before running the A/B, and deciding the intent-fusion policy. Confirm before starting.
<!-- SECTION:PLAN:END -->
