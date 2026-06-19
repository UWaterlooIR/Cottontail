---
id: doc-4
title: Decision — TREC-like indexing and internal-document-id model
type: specification
created_date: '2026-06-19 03:39'
updated_date: '2026-06-19 03:39'
---
**Status:** accepted (2026-06-19).

Authoritative detail: **docs/indexing.md** (this is a short pointer/record).

## Decision

We index a **TREC-like document collection** (each document = text contents + a
unique string `docno`, our JSON `docid`) using this model:

- Store **only the contents** + one `:item` annotation per document. Do NOT
  tokenize the docno into the index (its tokens, e.g. `shard_*`, are pure bloat we
  never search — ~85M postings for `shard` on the 1000-shard burrow).
- The **internal document id is the `:item` start address `cp`** (handed to us by
  `ssr_ranking` as `container_p()`), unique by construction. Everything internal
  (agents, our code, exclusion) keys on `cp`. `cp` is burrow-instance-local, so
  persisted outputs store the portable `docno`, not `cp`.
- A **`cp <-> docno` sidecar** (our own, built from the JSON docids) provides
  `cp -> docno` (result/output emission) and `docno -> cp` (rare human CLI fetch).
  Sized for ~500M docs: `cp[]` resident (binary search), `cq` derived
  (`cq_i = cp_{i+1}-1`), docno text read lazily from disk.
- **Filter judged documents by an integer `cp` post-filter** on ranked results
  (client-side judged set; over-fetch `top_k + |exclude|`). The static, stateless
  burrow rules out annotation-based marking; the docno GCL carve is rejected.
- **Document match counts** (total/unjudged) are a **byproduct of the single ssr
  ranking pass** (count containers as they close), not separate enumerations.
- Fetch text by `cp` internally (`translate(cp,cq)`); `docno -> cp -> translate`
  for human CLI fetch.

## Scope and supersession

- This **supersedes the current JSONL docno handling** (A1/A2 tokenized the docno
  and used a `(>> :docno ...)` carve). The retrieval-side cutover (cover_search
  `cp`/post-filter, get_document, B1/B2 keyed on `cp`) is **deliberately NOT
  planned yet** — we first build the generic indexing module and wire it into the
  JSONL indexer, then plan the cutover based on what is actually built.
- Tracked by the umbrella task "Index TREC-like collections (contents + docno) ->
  static warren" and its children.
