---
id: TASK-6.1
title: 'Generic indexing: cp<->docno sidecar module (src/)'
status: To Do
assignee: []
created_date: '2026-06-19 03:43'
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

A small, **format-agnostic** C++ module in `src/` implementing the internal-id +
`cp <-> docno` sidecar machinery from **docs/indexing.md** (decision doc-4). It is
the reusable core that any TREC-like indexer (the JSONL CLI in Child B, others
later) calls; it must NOT depend on `apps/` or JSONL specifics — only on the
Cottontail core (`Warren`/`Txt`/`Idx`, `addr`).

## Background (read docs/indexing.md §3, §5, §6)

- A document is text contents + a unique string `docno`.
- Its **internal id is the `:item` start address `cp`** — the value `ssr_ranking`
  returns as `RankingResult::container_p()` (src/ranking.cc), unique by
  construction (monotonic, non-overlapping document spans).
- The docno is NOT in the inverted index; this module holds the `cp <-> docno`
  mapping in a sidecar built from docnos supplied by the indexer.
- This is the same idea as core `FastidTxt` (src/fastid_txt.cc — position->id via a
  binary search on a sorted position array) but (a) built from supplied docnos
  rather than by translating a `:docno` annotation, and (b) it adds the reverse
  `docno -> cp` direction `FastidTxt` lacks.

## Required behavior

1. A sidecar **builder**: given, per document, `(cp, docno)` in `cp` order plus the
   corpus end (the last document's `cq`), and given the burrow's working directory,
   write a sidecar file. Validate **docno uniqueness** while building — a duplicate
   docno is a hard error.
2. A sidecar **reader/loader**: open the sidecar from a burrow's working dir, with
   lookups:
   - `docno_of(cp) -> docno` (and the inverse position via the sorted `cp[]`),
   - `span_of(cp) -> (cp, cq)`,
   - `cp_of(docno) -> cp` (or "not found").
3. **Fetch helpers** (take a `Warren`): `text_by_cp(warren, cp)` =
   `txt()->translate(cp, cq)`; `text_by_docno(warren, docno)` = `cp_of` then
   translate; "not found" is not an error.
4. **Sized for ~500M documents** (docs/indexing.md §6):
   - keep the `cp[]` array resident and **binary-search** it (`O(log m)`),
   - **do NOT store `cq`**: derive `cq_i = cp_{i+1} - 1`, with the final `cq` stored
     once,
   - read docno **text lazily from the on-disk blob** (one small read per lookup),
     not all resident,
   - the reverse `docno -> cp` may be disk-resident (a docno-sorted index or hash);
     it serves a rare human fetch and need not be in RAM.
   (Match the spirit of FastidTxt's packed/compressed file; reuse its helpers if
   convenient.)

## Where it lives / may modify

New files `src/<name>.{h,cc}` (e.g. `src/docno_sidecar.{h,cc}` — final name your
call), wired into `src/BUILD` (the `cottontail` lib) and exported via
`src/cottontail.h` if appropriate; unit tests in `test/` wired into `test/BUILD`.
Do NOT modify `apps/` (that is Child B) or the JSONL CLI.

## Non-goals

- No JSONL/`apps` coupling; no changes to `cover_search`/`get_document`/ranking.
- Does not decide the `:item` layout (the indexer owns that); it only stores and
  serves the `(cp, cq, docno)` it is given.
- Not the retrieval-side cutover (deferred per doc-4).

## Acceptance criteria are below; keep the build + tests green.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A new src/ module (e.g. src/docno_sidecar.{h,cc}) provides a sidecar builder (per-document (cp, docno) in cp order + final cq -> a sidecar file in the burrow working dir) and a reader with docno_of(cp), span_of(cp)->(cp,cq), and cp_of(docno); it depends only on the Cottontail core (no apps/JSONL coupling) and is wired into src/BUILD.
- [ ] #2 The builder validates docno uniqueness and reports a duplicate docno as a hard error.
- [ ] #3 Fetch helpers text_by_cp(warren, cp) and text_by_docno(warren, docno) return the document body via txt()->translate(cp,cq); an unknown cp/docno is reported as not-found (not an error).
- [ ] #4 The layout is sized for ~500M docs: cp[] is resident and binary-searched (O(log m)); cq is NOT stored but derived as cp_{i+1}-1 (final cq stored once); docno text is read lazily from the on-disk blob rather than held resident; the reverse docno->cp need not be RAM-resident.
- [ ] #5 Unit tests in test/ (wired into test/BUILD) build a small set of (cp, docno), write and reload the sidecar, and assert: cp<->docno round-trips, span_of derives cq correctly (including the final document), text_by_cp/text_by_docno fetch the right body from a tiny built warren, an unknown docno/cp is not-found, and a duplicate docno is rejected at build.
- [ ] #6 bazel build of //src:cottontail and bazel test of the new test target (plus //test:tests //test:hazel_test) are green.
<!-- AC:END -->
