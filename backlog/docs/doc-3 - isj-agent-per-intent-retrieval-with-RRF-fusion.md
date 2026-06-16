---
id: doc-3
title: 'isj-agent: per-intent retrieval with RRF fusion'
type: specification
created_date: '2026-06-16 23:29'
updated_date: '2026-06-16 23:30'
---
# isj-agent: Per-Intent Retrieval with RRF Fusion

## Decision

When the Analyst divides a question into multiple intents (interpretations),
each intent is processed **independently** as its own retrieval: every intent
produces its own ranked list of results. The per-intent ranked lists are then
combined with **Reciprocal Rank Fusion (RRF)** to produce the single final
ranking returned for the question.

A question that yields a single interpretation produces a single ranked list,
and fusion is a no-op (the list passes through unchanged).

## Rationale

- Each interpretation is a self-contained, search-ready restatement (see doc-2),
  so it can drive a retrieval on its own.
- Searching each interpretation separately and fusing avoids conflating distinct
  readings into one muddled query, and gives every plausible reading a chance to
  contribute to the final ranking.
- RRF is **rank-based**, which aligns with the decision in doc-2 to carry the
  signal by rank order rather than by weights: documents ranked highly across
  multiple interpretations rise to the top without needing calibrated per-intent
  scores.

## Method

RRF combines lists by summing reciprocal ranks:

    score(d) = sum over lists i of  1 / (k + rank_i(d))

over each ranked list i in which document d appears, where rank_i(d) is the
1-based rank of d in list i. We use the conventional default **k = 60**.
Documents are then sorted by descending fused score.

## Status / open points

- The order of interpretations (most-plausible-first) is currently NOT used to
  weight the fusion; all intents contribute equally. If we later want the
  primary interpretation to dominate, a per-intent weight could be introduced,
  consistent with the stance in doc-2 of adding weights only when a consumer
  needs them.
- Any per-intent result caps are left for the retrieval implementation.

## Related

- doc-2 (simplified Analyst output / Intents) — the source of the multiple
  interpretations fused here.
