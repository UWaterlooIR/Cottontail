---
id: TASK-6.2
title: >-
  JSONL index: produce the new-style (TREC-generic) index via the generic
  indexer
status: To Do
assignee:
  - '@claude'
created_date: '2026-06-19 03:44'
updated_date: '2026-06-21 19:36'
labels:
  - cpp
dependencies:
  - TASK-6.1
references:
  - docs/indexing.md
  - backlog/docs/doc-4
  - apps/jsonl_core.cc
  - apps/cottontail-jsonl-index.cc
parent_task_id: TASK-6
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Goal

`cottontail-jsonl-index` produces a **cp-native burrow** (contents + one `:item`
per document) using the TASK-6.1 content indexer (`add_document(contents) -> cp`),
and **dumps a flat `docid<TAB>cp` file** alongside the burrow -- one line per
indexed row. No `:docno`, no docno tokens, no sidecar. See doc-6 / docs/indexing.md.

The `cp<->docno` SQLite map is built from this flat dump by the index CLI
(TASK-6.3); docno uniqueness is enforced there (the SQLite UNIQUE index), not here.

## What to do

1. In `jsonl_index` (apps/jsonl_core.cc), parse each row to `(docid, contents)`;
   `cp = indexer.add_document(contents)`; append `docid<TAB>cp` to the flat file.
   No `add_text(docid)`, no `:docno`.
2. Contentless rows (empty/zero-token contents) are skipped (rows_skipped; fatal
   under `--strict`), as today. A duplicate docid is NOT detected here (it surfaces
   at the SQLite build, TASK-6.3).
3. `cottontail-jsonl-index` writes the burrow + the flat dump (path alongside the
   burrow). Update usage/help and `IndexSummary` as needed.
4. Docs: note in `docs/cottontail-jsonl-cli-spec.md` / `docs/indexing.md` that the
   indexer produces a cp-native burrow + a flat (docid,cp) dump.

## The query side stays quarantined (redone cp-native in TASK-5)

`jsonl_get` / `jsonl_query` / `cover_search` are reframed on `cp` in TASK-5
(A3/A1/A2). Leave the quarantined query-path tests quarantined; A3 restores the
non-cover ones cp-native.

## Non-goals

- No sidecar, no SQLite here (the map + the front-door CLI are TASK-6.3).
- Not the query side (TASK-5).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 cottontail-jsonl-index produces a cp-native burrow via the TASK-6.1 content indexer: per row parse (docid, contents), cp = add_document(contents); the burrow has contents + one :item per document, no :docno, no docno tokens. There is NO add_text(docid) and no sidecar.
- [ ] #2 The indexer writes a flat (docid<TAB>cp) file alongside the burrow, one line per indexed row, cp matching that row :item start. (A docno-less corpus writes no flat file.)
- [ ] #3 Contentless rows (empty/zero-token contents) are skipped (rows_skipped; fatal under --strict). docno uniqueness is NOT checked here -- it is enforced at SQLite build (TASK-6.3 UNIQUE index).
- [ ] #4 The repo builds (//... minus the Boost-blocked targets) and the suite is green; the :docno-dependent query-path tests stay quarantined (the query side is redone cp-native under TASK-5).
- [ ] #5 A test indexes a small fixture and asserts the burrow has no :docno / no docno tokens and the flat file lists (docid, cp) for each indexed row with cp matching the :item container_p(); docs (cli-spec, indexing.md) state cottontail-jsonl-index produces a cp-native burrow + a flat (docid,cp) dump, with the SQLite map built by the index CLI (TASK-6.3).
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. jsonl_index (apps/jsonl_core.cc): per row, cp = indexer.add_document(contents);
   append docid<TAB>cp to the flat dump file (opened next to the burrow). Remove the
   sidecar/finalize-writes-sidecar path.
2. Keep the contentless-row skip (rows_skipped; fatal under --strict). No duplicate
   check here.
3. cottontail-jsonl-index.cc: ensure the flat dump path is emitted/known; update
   usage + IndexSummary as needed.
4. Update the cp-native test: index a small fixture, assert no :docno / no docno
   tokens and the flat file lists (docid,cp) with cp matching the :item
   container_p(). Keep the query-path tests quarantined.
5. Docs: cli-spec + indexing.md note the cp-native burrow + flat dump.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). jsonl_index uses the TASK-6.1 content indexer (add_document(contents) -> cp) and dumps a flat (docid<TAB>cp) file alongside the cp-native burrow INSTEAD of building a sidecar. The prior implementation (drives DocnoContentsIndexer, writes the sidecar) is REPLACED. docno uniqueness moves to the SQLite build (TASK-6.3). Contentless rows still skipped (fatal under --strict). Authoritative: doc-6 + docs/indexing.md.
<!-- SECTION:NOTES:END -->
