---
id: TASK-6.2
title: >-
  JSONL index: produce the new-style (TREC-generic) index via the generic
  indexer
status: To Do
assignee: []
created_date: '2026-06-19 03:44'
updated_date: '2026-06-19 04:04'
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

`cottontail-jsonl-index` produces the **new-style (TREC-generic) index** by using
the Child A generic indexer (TASK-6.1): per document **contents + one `:item`
annotation + the `cp <-> docno` sidecar** (built by default). The internal id is
the `:item` start `cp`; the docno lives only in the sidecar. See docs/indexing.md /
doc-4.

This **replaces** the old style — there is no docno tokenization, no `:docno`
annotation, and no opt-in flag. We have no use for the old-style index, so the
indexer simply produces the new one.

## What to do

1. In `jsonl_index` (apps/jsonl_core.cc), parse each row to `(docid, contents)` and
   call the generic indexer's `add_document(docid, contents)`; `finalize()` writes
   the sidecar. Remove the old `add_text(docid)` + `:docno` indexing. docno
   uniqueness is validated by the indexer (a duplicate docid fails the build).
2. `cottontail-jsonl-index` produces the new-style burrow by default (no flag — the
   sidecar is intrinsic to the generic indexing). Update usage/help and
   `IndexSummary` as needed.
3. Docs: note in `docs/cottontail-jsonl-cli-spec.md` / `docs/indexing.md` that the
   indexer now produces the new-style index (contents + `:item` + sidecar).

## The query side is being REDONE — not preserved here

`jsonl_get` / `jsonl_query` / `cover_search` read `:docno` and are incompatible with
the new-style burrow; they (and B1/B2) are slated for a separate redo against the
`cp`/sidecar model (the deferred cutover, doc-4). Do **not** try to keep them
working here. To leave the repo building and the suite green, **retire/quarantine
the now-obsolete query-path tests** (the `:docno`-dependent cases in `test/jsonl.cc`,
`test/jsonl_cli.cc`, `test/jsonl_server.cc`); the query functions themselves can
remain in source until the redo. Add a sidecar round-trip test in their place.

## Non-goals

- No old-style index, no flag, no additive coexistence.
- Do NOT rebuild the query side (cover_search/get/query) or B1/B2 — that is the
  separate redo.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 cottontail-jsonl-index produces the new-style index via the TASK-6.1 generic indexer: per row it parses (docid, contents) and calls add_document; the burrow has contents + one :item per document + the cp<->docno sidecar built by default; there is NO add_text(docid) and NO :docno annotation; the internal id is the :item start cp. The old style is removed (no docno tokenization, no opt-in flag).
- [ ] #2 docno uniqueness is validated: a duplicate docid fails indexing with a clear message.
- [ ] #3 A test indexes a small fixture and, from the produced burrow + sidecar, round-trips docid->cp and cp->docno and fetches the body via text_by_cp/text_by_docno.
- [ ] #4 The repo builds (//... minus the Boost-blocked targets) and the test suite is green: the :docno-dependent query-path tests (jsonl_get/jsonl_query/cover_search cases in test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc) are retired/quarantined since that side is being redone; no attempt is made to keep old-style query behavior working.
- [ ] #5 docs (cli-spec, indexing.md) state that cottontail-jsonl-index now produces the new-style (TREC-generic) index with the sidecar, and that the query side is pending the redo.
<!-- AC:END -->
