---
id: TASK-40.4
title: 'SearchCoach phase 4: coach-on vs coach-off A/B on the dev topics'
status: To Do
assignee: []
created_date: '2026-07-11 21:30'
updated_date: '2026-07-11 23:43'
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
GOAL: measure the coach -- coach-on (SearchCoachAgent) vs coach-off (MechanicalSearchCoach) over the 22 RAG25 dev topics. Design: docs/design/search-coach.md (rollout step 4). DEPENDS ON 40.2.

READ FIRST:
- The trec-rag-2026 repo (sibling): data/trec-rag-2026/development-data/topics/rag25-topics-dev.tsv (22 topics: id \t narrative) and rag25-dev-umbrela-qrels/*.qrels (ClimbMix dev qrels, 4-col TREC, grades 0-4; prefer the qwen3.5-9b-v2 or codex variant). See that repo's memory reference_dev_data.
- isj cli: uv run --directory isj python -m isj_agent.cli --question "<narrative>" --out <dir> --config <cfg> (one topic per run; writes intent-NN.json ranked lists + intent-NN.trace.jsonl).
- The docno-on-the-wire runs already emit ClimbMix shard_NNNNN_RRRR docnos that resolve against the qrels.

STEPS:
1. Two configs, identical except [coach].class: coach-on ([coach].class = SearchCoachAgent) vs coach-off ([coach].class = MechanicalSearchCoach; == the 40.1 baseline). Otherwise identical (same engine, same [agents.*], same [loop]).
2. Eval pipeline -- DOES NOT EXIST YET; this is the bulk of the work. It likely belongs in trec-rag-2026 and MAY WARRANT ITS OWN TASK there. Components:
   a. batch runner (script): for each (id, narrative) in rag25-topics-dev.tsv, run isj_agent.cli --question <narrative> --out runs/<arm>/<id> --config <arm-config>, both arms. Serial (the judger already fans concurrent LLM calls; parallel topics would thrash the single vLLM).
   b. FUSION (script): each run dir has intent-NN.json = per-intent judged ranked lists ({docno,grade,score,rank}); fuse the per-intent lists into ONE TREC run per topic (topic Q0 docno rank score run_id; ranks from 1 ascending; scores non-increasing within a topic; docnos = ClimbMix ids). *** FUSION POLICY IS AN UNDECIDED DESIGN CHOICE *** -- RRF (robust, parameter-light; recommended) vs grade-then-score. DECIDE WITH THE OWNER before implementing.
   c. scoring (script): score the fused runs vs the dev qrels with ir_measures (uv add ir_measures; pure-python, no trec_eval build) -- recall@100/1000, nDCG@10/20.
   d. behavioral metrics from the intent-NN.trace.jsonl: turns-per-intent, no_query bounce count (bounce kind=no_query); and, for the coach arm, whether the coach reports' "Vocabulary worth pursuing" terms appear in gold-relevant docs.
3. Run both arms over the 22 topics; record results in a findings doc + the task notes; compare coach-on vs coach-off on recall/nDCG + turns + no_query.

CAVEATS: pooled qrels -> unjudged docs count as non-relevant -> this is a RELATIVE A/B (coach vs no-coach), not an absolute score. Analyst temperature is already 0 (TASK-38) so intent decompositions are stable across arms -- keep everything except [coach].class identical.

FLAG FOR OWNER (must resolve before starting): (1) the eval pipeline (2b/2c/2d) does not exist -- recommend a dedicated task in trec-rag-2026 to build it; (2) decide the intent-fusion policy (RRF recommended). Confirm both before executing this phase.
<!-- SECTION:PLAN:END -->
