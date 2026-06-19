---
id: TASK-6.2
title: 'JSONL index: build the cp<->docno sidecar via the generic module'
status: To Do
assignee: []
created_date: '2026-06-19 03:44'
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

The JSONL indexer **steps up to the generic module** (Child A, TASK-6.1): during
`cottontail-jsonl-index`, build the `cp <-> docno` sidecar so the produced static
warren carries it. Per doc-4 / docs/indexing.md, this is the first concrete use of
the internal-id + sidecar model on our real collection.

## IMPORTANT — additive and non-breaking (read this)

The index format and the query readers are coupled: today the JSONL stack tokenizes
the docid and annotates `:docno`, and `jsonl_get` / `jsonl_query` / `cover_search`
read `:docno` (cover_search also has a `(>> :docno ...)` exclusion carve). Removing
`:docno` now would break those readers and their tests, dragging in the retrieval
cutover that doc-4 **defers**.

So this task is strictly **ADDITIVE**: keep the current indexing (docid + `:docno`
+ `:item`) exactly as-is, and ALSO build the sidecar alongside it. Nothing in the
query path changes; the build stays green. The cutover — dropping the docid
tokenization / `:docno` and migrating the readers + exclusion + B1/B2 to `cp` — is
the deferred work to be planned AFTER this lands (per doc-4). Do NOT do it here.

## Required behavior

1. In `jsonl_index` (apps/jsonl_core.cc), while indexing each row, capture that
   document's `cp` (the `:item` container start — `container_p`; today `:item` =
   `[p_id, q_body]`, so `cp = p_id`) and its `docno` (the JSON docid), plus the
   final document end. Keep the existing `add_text(docid)` / `:docno` / `:item`
   calls unchanged.
2. After indexing, call the Child A builder to write the sidecar into the burrow
   working dir. Surface duplicate-docno detection (the builder's hard error) as an
   index failure with a clear message.
3. The produced static warren now contains the sidecar; opening the burrow can load
   it. (No reader is required to USE it yet — that is the deferred cutover — but the
   data is present and verifiable.)
4. `IndexSummary` may note the sidecar (optional).

## Verify

- A test (test/jsonl.cc or test/jsonl_cli.cc) indexes a small fixture, then loads
  the sidecar from the burrow and round-trips: a known docid -> its `cp`, and `cp`
  -> docno; `text_by_docno`/`text_by_cp` return the right body; a fixture with a
  duplicate docid fails indexing.
- All existing JSONL tests still pass unchanged (additive).

## Where it lives / may modify

`apps/jsonl_core.{h,cc}`, `apps/cottontail-jsonl-index.cc`; tests in
`test/jsonl.cc` / `test/jsonl_cli.cc`; a note in `docs/cottontail-jsonl-cli-spec.md`
and/or `docs/indexing.md` that the indexer now also emits the sidecar
(transitional: `:docno` retained for now). Depends on Child A (TASK-6.1).

## Non-goals

- Do NOT remove the docid tokenization or `:docno`, and do NOT touch
  `jsonl_get` / `jsonl_query` / `cover_search` / exclusion / B1 / B2 — that is the
  deferred cutover (doc-4).
- No new query behavior; no retrieval-side use of `cp` yet.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 cottontail-jsonl-index, while indexing, captures each document's cp (the :item container start) and docno (the JSON docid) plus the final end, and after indexing builds the cp<->docno sidecar (Child A) into the burrow working dir; the existing add_text(docid)/:docno/:item indexing is unchanged (additive).
- [ ] #2 A duplicate docid in the input is detected (via the builder) and reported as an index failure with a clear message.
- [ ] #3 The produced static warren contains the sidecar and it loads from the opened burrow; a test round-trips docid->cp and cp->docno and fetches the body via text_by_cp/text_by_docno, and a duplicate-docid fixture fails indexing.
- [ ] #4 No query-path change: jsonl_get / jsonl_query / cover_search / exclusion are untouched, and all existing JSONL tests (//test:jsonl_test //test:jsonl_server_test) still pass unchanged.
- [ ] #5 docs (cli-spec and/or indexing.md) note that the indexer now also emits the cp<->docno sidecar, transitionally alongside the retained :docno; the full cutover is deferred per doc-4.
- [ ] #6 Full build (//... minus the Boost-blocked targets) and //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test are green.
<!-- AC:END -->
