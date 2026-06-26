---
id: TASK-6
title: Index TREC-like collections (contents + docno) into a static warren
status: Done
assignee: []
created_date: '2026-06-19 03:40'
updated_date: '2026-06-26 19:58'
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
static SimpleWarren, per **docs/indexing.md** (decisions **doc-4** + **doc-6**;
doc-6 makes the model cp-native).

The core idea (cp-native, doc-6): the burrow stores only **contents + one `:item`
annotation** per document; the **identity is the `:item` start address `cp`** (from
`ssr_ranking` container_p()), and `cp` is the working id everywhere (wire, engine,
agent loop). The **`docno` is optional** and lives only at a boundary, in a
**`cp <-> docno` SQLite map** built from a flat `(docno, cp)` dump — consulted off
the hot path (the `cp -> docno` rewrite at persistence and a `docno -> cp`
human/external fetch). This removes the docno-token index bloat and the
`(>> :docno ...)` machinery, and fits the static, stateless burrow.

## Decomposition

- **6.1** — a thin **cp-native content indexer** (src/): `add_document(contents)
  -> cp` (add_text + one `:item`); no docno, no map. (Re-specced from the original
  docno+sidecar module; the custom binary sidecar is deleted.)
- **6.2** — `cottontail-jsonl-index` uses 6.1 and, per row, **dumps a flat
  `(docid, cp)` file** alongside the cp-native burrow (no sidecar).
- **6.3** — a **Python index CLI** (front door): runs 6.2, builds the
  `cp <-> docno` **SQLite** map from the flat dump (UNIQUE docno = the uniqueness
  check), cleans up; plus a Python reader for the boundary lookups.

## Out of scope (the retrieval-side cutover is TASK-5)

The cp-native query path — `cover_search` returning `cp` + `cp`-post-filter
exclusion + counts inline, `get_document` / `read` on `cp`, and the Searcher keyed
on `cp` — is **TASK-5 engine track** (A1/A2/A3) and the B/C tracks, not this
umbrella.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
cp-native TREC-like indexing is complete. A generic content indexer in src/ (6.1: add_document(text) -> cp, no docno/sidecar in C++); the JSONL new-style index produced via the generic indexer (6.2); the cp-native index front door + cp<->docno SQLite map (6.3: jsonl-index dumps a flat docno<TAB>cp file, the Python CLI loads it into <burrow>/docno-cp.sqlite); and the human docno fetch helper (6.4: cottontail-fetch, docno->cp->text, plus the cp->docno+text reverse added in TASK-15). The C++ engine stays cp-only and never opens the map (doc-8). All 4 subtasks Done.
<!-- SECTION:FINAL_SUMMARY:END -->
