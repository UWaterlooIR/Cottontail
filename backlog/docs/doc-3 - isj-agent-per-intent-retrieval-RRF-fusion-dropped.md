---
id: doc-3
title: 'isj-agent: per-intent retrieval (RRF fusion dropped)'
type: specification
created_date: '2026-06-16 23:29'
updated_date: '2026-06-18 04:45'
---
# isj-agent: Per-Intent Retrieval (RRF fusion DROPPED)

> **Status (2026-06-18): SUPERSEDED — RRF is dropped.** We do NOT fuse the per-intent
> lists. Current plan: the Analyst splits a question into intents; each intent is searched
> independently by the Searcher; the per-intent results (a RankedList + the verbose loop
> trace) are PERSISTED to a run output directory (see TASK-5, C2/C3). Deciding what to do
> with them — fusion, Task-R, RAG — is deferred. The per-intent INDEPENDENCE below still
> holds; the RRF method below is NOT implemented. Retained for reference / possible future
> use.

## Still in force: per-intent independence

When the Analyst divides a question into multiple intents (interpretations), each intent is
processed INDEPENDENTLY as its own retrieval: every intent produces its own ranked list (a
RankedList of judged passages). A question that yields a single interpretation produces a
single ranked list.

## Dropped: RRF fusion (original proposal, retained for reference)

The per-intent ranked lists were to be combined with Reciprocal Rank Fusion (RRF):

    score(d) = sum over lists i of  1 / (k + rank_i(d))     [k = 60, equal weight]

ranked by descending fused score; single-intent = no-op. The rationale was rank-based
fusion (doc-2: carry the signal by rank, not weights) so documents ranked highly across
multiple interpretations rise to the top. This is NOT currently implemented — per-intent
results are persisted UNFUSED instead. If fusion is revisited, this is the starting point.

## Related

- doc-2 (simplified Analyst output / Intents) — the source of the multiple interpretations.
- TASK-5 (Searcher), C2 (run-output writer), C3 (CLI orchestrator) — the current,
  fusion-free plan that persists per-intent results.
