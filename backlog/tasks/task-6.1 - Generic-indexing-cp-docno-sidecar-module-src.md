---
id: TASK-6.1
title: >-
  Generic cp-native content indexer (src/): add_document(contents) -> cp (no
  docno, no sidecar)
status: To Do
assignee:
  - '@claude'
created_date: '2026-06-19 03:43'
updated_date: '2026-06-21 19:36'
labels:
  - cpp
dependencies: []
references:
  - docs/indexing.md
  - backlog/docs/doc-4
  - src/fastid_txt.cc
  - src/ranking.cc
parent_task_id: TASK-6
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Goal

A thin, format-agnostic src/ module: the cp-native way to index a document as
**contents + one `:item` annotation**, returning the document `cp`. Per doc-6,
`add_document(contents) -> cp`; it takes no docno, stores no docno, and builds no
map/sidecar. docno is the caller concern (the JSONL indexer pairs `cp` with the
docid and dumps the flat (docid,cp) file -- TASK-6.2). Depends only on the
Cottontail core (no apps/JSONL coupling).

## The model (docs/indexing.md sections 2-3)

Per document: `add_text(contents)` + one `:item` annotation over the body; return
`cp` = the `:item` start (= ssr_ranking container_p()). No `:docno`, no docno
tokens, no sidecar/map.

## Required behavior

1. A content indexer over a builder: `add_document(contents) -> cp` does
   `add_text(contents)` + one `:item` annotation, and RETURNS `cp`; `finalize()`
   finalizes the underlying builder. No docno parameter, no map.
2. `cp` is the `:item` container start, unique and strictly increasing by
   construction.
3. HARD ERROR on empty/whitespace-only contents, or contents with no indexable
   tokens (the cp-uniqueness invariant: an empty body occupies no address range, so
   its `cp` would collide with the next document).

## Where it lives / what is deleted

A renamed cp-native `src/<name>.{h,cc}` (no docno in the name), wired into
`src/BUILD`; unit tests in `test/`. The previous `DocnoContentsSidecar` (binary
`cp<->docno` format, the docno-sorted permutation, the lazy readers) and the docno
machinery of `DocnoContentsIndexer` are **DELETED**.

## Non-goals

- No docno, no map: the `cp<->docno` SQLite map is TASK-6.3, built from the flat
  (docid,cp) dump the JSONL indexer writes.
- No JSONL/apps coupling; not the query path.
<!-- SECTION:DESCRIPTION:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @claude
created: 2026-06-20 20:33
---
Plan + 2 new ACs added per the 2026-06-20 design discussion. Differences vs prior task text, all additive (nothing dropped): (1) concrete names docno_contents_index / DocnoContentsIndexer + DocnoContentsSidecar replace the placeholder TrecIndexer; (2) reverse docno->cp firmed from may-be-disk to MUST-be-disk (new AC); (3) empty/whitespace contents and empty docno are now an explicit hard error (new AC); (4) docno-text blob stored UNCOMPRESSED for lazy random reads (FastidTxt whole-blob compression is not reusable for the text); cp[]/offset[] reuse the post-compressed pattern via small local helpers, not by refactoring fastid_txt.cc; (5) fetch helpers are methods on the sidecar reader.
---
<!-- COMMENTS:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A src/ module provides a thin cp-native content indexer over a builder: add_document(contents) -> cp does add_text(contents) + one :item annotation per document (cp = the :item start) and RETURNS cp. It takes no docno, stores no docno, and builds no map/sidecar. Depends only on the Cottontail core; wired into src/BUILD.
- [ ] #2 The returned cp equals the :item container start (what ssr_ranking reports as container_p()), unique and strictly increasing by construction; finalize() finalizes the underlying builder.
- [ ] #3 add_document rejects empty/whitespace-only contents, and contents that yield no indexable tokens, as a HARD ERROR (an empty body occupies no address range, so its cp would collide with the next document). This is the cp-uniqueness invariant, independent of docno.
- [ ] #4 The custom DocnoContentsSidecar (binary cp<->docno format, permutation, lazy readers) and the docno parameter are REMOVED; the module/file is renamed to a cp-native name; the burrow has no :docno annotation and no docno tokens.
- [ ] #5 Unit tests (test/, wired into test/BUILD) index a few contents and assert: cp values are distinct and strictly increasing; the returned cp matches the :item container_p() (verified via a hopper over :item); the index has no :docno and no docno tokens; empty/zero-token contents are rejected.
- [ ] #6 bazel build //src:cottontail and the new test target (plus //test:tests //test:hazel_test) are green.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Rename src/docno_contents_index.{h,cc} to a cp-native name; reduce it to the
   content indexer: add_document(contents) -> cp = add_text(contents,&p,&q) +
   add_annotation(":item",p,q); return p; guard q<p (no indexable tokens) as a hard
   error; finalize() -> builder->finalize().
2. DELETE DocnoContentsSidecar (the binary format, the permutation, the readers) and
   the docno parameter / uniqueness machinery.
3. Update src/BUILD (the glob picks up the rename) and the unit tests (rename
   test/docno_contents_index.cc): assert distinct increasing cp; cp matches the
   :item container_p() via a hopper; no :docno / no docno tokens; empty/zero-token
   contents rejected.
4. Verify bazel build //src:cottontail + //test:tests //test:hazel_test green.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). Reframed to a THIN cp-native content indexer: add_document(contents) -> cp (add_text + one :item), no docno, no map. The prior implementation (DocnoContentsIndexer + the custom binary DocnoContentsSidecar in src/docno_contents_index.{h,cc}, with its test) shipped under the old docno+sidecar spec and is to be REPLACED -- delete the sidecar machinery, rename the module cp-native, have add_document return cp. The cp<->docno map is now a SQLite store built by the index CLI (TASK-6.3) from a flat (docid,cp) dump the JSONL indexer writes. Authoritative: doc-6 + docs/indexing.md.
<!-- SECTION:NOTES:END -->
