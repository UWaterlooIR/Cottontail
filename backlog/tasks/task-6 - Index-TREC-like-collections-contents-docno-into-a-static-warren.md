---
id: TASK-6
title: Index TREC-like collections (contents + docno) into a static warren
status: To Do
assignee: []
created_date: '2026-06-19 03:40'
labels:
  - cpp
dependencies: []
references:
  - docs/indexing.md
  - backlog/docs/doc-4
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Umbrella for indexing a **TREC-like document collection** — each document is text
contents plus a unique string identifier (`docno`, our JSON `docid`) — into a
static SimpleWarren, per the model in **docs/indexing.md** (decision: doc-4).

The core idea: the burrow stores only **contents + one `:item` annotation** per
document; the **internal id is the `:item` start address `cp`** (from
`ssr_ranking`'s `container_p()`); and a small **`cp <-> docno` sidecar** (built
from the JSON docids, not the inverted index) carries the docno for result output
and human fetch. This removes the docno-token index bloat and the `(>> :docno ...)`
machinery, and fits the static, stateless burrow.

## Decomposition

- Child A — a **generic, format-agnostic src/ module** for the internal-id +
  `cp <-> docno` sidecar machinery (builder, reader/lookups, fetch helpers,
  docno-uniqueness validation), sized for ~500M documents.
- Child B — the **JSONL indexer steps up to those methods**: `cottontail-jsonl-index`
  builds the sidecar via Child A and produces a static warren carrying it
  (additive / non-breaking; see Child B).

## Out of scope (deliberately deferred — plan AFTER this is built)

The retrieval-side cutover that this model eventually implies — `cover_search`
returning `cp` + `cp`-post-filter exclusion + counts inline in the ranking pass,
`get_document`/`read` reframed on `cp`, and B1/B2 keying the judged set on `cp` —
and the removal of the existing `:docno` tokenization/carve (A1/A2). Per doc-4 we
build the indexing capability first and plan that cutover based on what actually
gets built; do NOT start it under this umbrella.
<!-- SECTION:DESCRIPTION:END -->
