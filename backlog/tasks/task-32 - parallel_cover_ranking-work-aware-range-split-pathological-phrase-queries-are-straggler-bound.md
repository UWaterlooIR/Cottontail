---
id: TASK-32
title: >-
  parallel_cover_ranking: work-aware range split (pathological-phrase queries
  are straggler-bound)
status: To Do
assignee: []
created_date: '2026-07-07 15:31'
labels: []
dependencies: []
priority: medium
ordinal: 46000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
After the upstream memoization/optimization sync (04b711a, PR #11), phrase-heavy cover queries get a big SINGLE-THREADED win but do NOT benefit from rank threads. Measured on 100M: tier2 (three deadly phrases) 152s at rank-threads=1 vs 151s at rank-threads=16 -- zero parallel speedup, with userCPU RISING 1.67x and RSS flat (workers share postings correctly, so not a memory issue). An ordinary balanced query DOES scale (~2.5x by 4 threads). Diagnosis: parallel_cover_ranking (apps/jsonl_core.cc, TASK-25) splits the :item container span into ranges UNIFORM IN TOKENS, not in work. A pathological phrase's residual grind is concentrated in whichever range holds it, so one worker's slice dominates wall-clock (a straggler) while the other 15 finish fast (the extra CPU). This is our splitting, not upstream's engine.

Idea: make the split work-aware. Options to weigh: (a) weight range boundaries by estimated posting cost using idx()->count() of the query's leaves (the counts are already cheap, header-only reads, and used for atom_counts); (b) more, finer ranges than worker count + a work-stealing / dynamic queue so no single worker owns a whole grind; (c) a hybrid. Keep results identical (the container-ownership-by-cp invariant that makes scores/counts exact must hold regardless of boundary placement).

Validation: tier2 on 100M shows real speedup 1->16 threads while staying result-identical; ordinary queries do not regress; parity unit tests (the TASK-25 suite) stay green; bazel //test:all + isj green.

Separate observation to investigate first (may or may not be part of this task): tier2 at top_k=20 is ~20s but top_k=200 is ~152s on 100M -- the depth/summary cost scales steeply and the agent runs at top_k=200. Understand whether that is ranking depth or the per-doc summary re-walk before deciding scope.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 parallel_cover_ranking uses a work-aware range split; tier2 on the 100M burrow shows real wall-clock speedup from 1 to 16 rank threads (not the current ~flat 152s), with byte-identical results and match counts
- [ ] #2 Ordinary balanced queries do not regress; the TASK-25 parity tests (result multiset + exact match counts across thread counts) stay green; bazel //test:all + isj suite green
- [ ] #3 The top_k=20 vs top_k=200 latency gap on tier2 is characterized (ranking depth vs summary re-walk) and either addressed here or filed as a follow-up
<!-- AC:END -->
