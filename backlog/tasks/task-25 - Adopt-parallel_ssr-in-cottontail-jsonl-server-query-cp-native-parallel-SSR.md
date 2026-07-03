---
id: TASK-25
title: Adopt parallel_ssr in cottontail-jsonl-server/-query (cp-native parallel SSR)
status: To Do
assignee: []
created_date: '2026-07-03 00:47'
labels: []
dependencies:
  - TASK-24
priority: high
ordinal: 39000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Bring Charlie's parallel shortest-substring-ranking speedup into OUR search stack instead of running his ssr-server. Upstream commit acf9237e adds parallel_ssr() to src/ranking.cc: it splits a shard's token span into contiguous ranges (>=1M tokens each, capped by allowed_threads), runs the SSR recurrence per range on a warren->clone() per worker, and merges the per-range top-k. It is a library function; ssr-server is only a thin wrapper. Our jsonl_core.cc already calls ssr_ranking(warren, query, container, top_k) on the ssr path (and the tiered path), the signature is unchanged upstream, and SimpleWarren implements clone_() — so this is a small, contained swap that keeps cp on the wire (doc-8) and the whole isj stack unchanged.

Scope: add a threads option (CLI flag for cottontail-jsonl-query, config/flag for cottontail-jsonl-server; default 0 = allowed_threads) and route the SSR ranking call(s) in apps/jsonl_core.cc through parallel_ssr(). Decide during implementation whether the tiered_ranking SSR stage should also parallelize (flag it; do not silently expand scope).

Depends on TASK-24 (the upstream sync that brings in parallel_ssr). Validation burrows: Scrapheap/climbmix-1M-porter.burrow and /share/indexes/climbmix-100M-porter.burrow (outside-repo path pre-approved by Mark for read-only validation). Restarting/replacing the running dev jsonl-server counts as a server-side change — coordinate per the leave-dev-server-running agreement.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 cottontail-jsonl-query and cottontail-jsonl-server expose a threads option (default 0 = allowed_threads) and route SSR ranking through parallel_ssr()
- [ ] #2 Parity: on Scrapheap/climbmix-1M-porter.burrow, parallel (threads>1) and sequential (threads=1) runs return the same top-k documents and scores for a fixed query set
- [ ] #3 Measured latency for a fixed query set on both Scrapheap/climbmix-1M-porter.burrow and /share/indexes/climbmix-100M-porter.burrow, threads=1 vs parallel, recorded in task notes
- [ ] #4 bazel test //test:tests //test:hazel_test and the isj Python suite stay green
- [ ] #5 running-the-search-stack.md documents the threads option
<!-- AC:END -->
