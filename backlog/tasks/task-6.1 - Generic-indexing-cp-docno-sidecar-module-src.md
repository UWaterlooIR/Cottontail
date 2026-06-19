---
id: TASK-6.1
title: >-
  Generic TREC-like indexing (src/): documents -> contents + :item + cp<->docno
  sidecar
status: To Do
assignee: []
created_date: '2026-06-19 03:43'
updated_date: '2026-06-19 03:57'
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

A small, **format-agnostic** C++ module in `src/` that is **the generic way to
index a TREC-like collection** into a static warren, per **docs/indexing.md**
(decision doc-4). A caller streams documents (each = a unique `docno` + text
`contents`); the module indexes them the new-model way and **produces the
`cp <-> docno` sidecar by default** — building the sidecar is intrinsic to using
the generic indexer, not an add-on. It depends only on the Cottontail core (no
`apps/`/JSONL coupling).

## The model it implements (docs/indexing.md §2,§3,§6)

- Per document: `add_text(contents)` + one `:item` annotation over the body. It does
  **NOT** tokenize the docno and creates **no `:docno`** annotation.
- The internal id is the `:item` start address `cp` (what `ssr_ranking` returns as
  `container_p()`), unique by construction.
- The docno lives only in the sidecar, built from the supplied docno strings.

## Required behavior

1. A generic indexer over a builder (e.g. a `TrecIndexer` wrapping a
   `SimpleBuilder` + the burrow working dir):
   - `add_document(docno, contents)` -> `add_text(contents)` + a `:item` annotation
     for that document; record `(cp, docno)` (cp = the document's `:item` start).
   - `finalize()` -> write the `cp <-> docno` sidecar (**by default**, always) and
     validate **docno uniqueness** (a duplicate docno is a hard error).
2. A sidecar **reader** that loads from a burrow's working dir, with
   `docno_of(cp)`, `span_of(cp) -> (cp,cq)`, `cp_of(docno)`; and fetch helpers
   `text_by_cp(warren, cp)` / `text_by_docno(warren, docno)` via `txt()->translate`.
   An unknown cp/docno is not-found (not an error).
3. **Sized for ~500M documents** (docs/indexing.md §6): `cp[]` resident +
   binary-searched (`O(log m)`); `cq` NOT stored but derived (`cq_i = cp_{i+1}-1`,
   final cq stored once); docno text read lazily from the on-disk blob; the reverse
   `docno -> cp` may stay disk-resident. (Reuse `FastidTxt`'s packed/compressed file
   helpers where convenient; src/fastid_txt.cc.)

## Where it lives / may modify

New files `src/<name>.{h,cc}` (final name your call, e.g. `src/trec_index.{h,cc}`
or split indexer/sidecar), wired into `src/BUILD` (`cottontail` lib); unit tests in
`test/` wired into `test/BUILD`. Do NOT modify `apps/` or the JSONL CLI (that is
Child B), and do NOT touch the existing query path / `:docno` consumers.

## Non-goals

- No JSONL/`apps` coupling; this is the reusable engine, not a CLI.
- Not the retrieval-side cutover (cover_search/get_document/B1/B2) — deferred
  (doc-4).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A new src/ module provides a generic indexer over a builder: add_document(docno, contents) indexes the contents (add_text) plus one :item annotation per document (internal id = the :item start cp) and does NOT tokenize the docno / creates no :docno; finalize() writes the cp<->docno sidecar BY DEFAULT (intrinsic, not opt-in) and validates docno uniqueness (a duplicate docno is a hard error). It depends only on the Cottontail core (no apps/JSONL coupling) and is wired into src/BUILD.
- [ ] #2 A sidecar reader loads from a burrow's working dir with docno_of(cp), span_of(cp)->(cp,cq), and cp_of(docno); fetch helpers text_by_cp(warren,cp) and text_by_docno(warren,docno) return the body via txt()->translate; an unknown cp/docno is not-found (not an error).
- [ ] #3 Layout sized for ~500M docs: cp[] resident and binary-searched (O(log m)); cq NOT stored but derived as cp_{i+1}-1 (final cq stored once); docno text read lazily from the on-disk blob; reverse docno->cp need not be RAM-resident.
- [ ] #4 Unit tests (test/, wired into test/BUILD) index a few (docno, contents) documents via the module and assert: the index contains NO :docno annotation and no docno tokens; cp<->docno round-trips; span_of derives cq correctly incl. the last document; text_by_cp/text_by_docno fetch the right body; an unknown docno/cp is not-found; a duplicate docno is rejected at finalize.
- [ ] #5 bazel build //src:cottontail and the new test target (plus //test:tests //test:hazel_test) are green.
<!-- AC:END -->
