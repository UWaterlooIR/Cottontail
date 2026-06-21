---
id: TASK-6.1
title: >-
  Generic cp-native content indexer (src/): add_document(contents) -> cp (no
  docno, no sidecar)
status: To Do
assignee:
  - '@claude'
created_date: '2026-06-19 03:43'
updated_date: '2026-06-21 18:47'
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

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
## Module names (replacing the placeholder TrecIndexer)
- Files: src/docno_contents_index.{h,cc}; tests: test/docno_contents_index.cc.
- Classes: DocnoContentsIndexer (drives a Builder) and DocnoContentsSidecar (reader).
- Sidecar files in the burrow working dir: sidecar.index, sidecar.docno, sidecar.perm.
- Picked up automatically by src/BUILD glob(*.cc/*.h) and //test:tests glob(test/**/*.cc); no BUILD edits required (a dedicated cc_test may be added if useful).
- Alternative name if preferred: key_contents_index / KeyContents... with a "key" param. Chose docno_* to match the vocabulary in docs/indexing.md and doc-4.

## Seam
DocnoContentsIndexer::make(shared_ptr<Builder>, shared_ptr<Working>). The CALLER builds the Builder/Featurizer/Tokenizer/Working (so TASK-6.2 jsonl_index keeps its --tokenizer/--stemmer/buffer choices). Depends only on the Cottontail core; no apps/JSONL coupling.

## add_document(docno, contents)
- HARD ERROR on empty or whitespace-only contents, and on an empty docno (an empty body occupies no address range -> cp collides with the next document -> breaks the unique-id invariant). Not a silent skip.
- builder->add_text(contents, &p_body, &q_body); builder->add_annotation(":item", p_body, q_body, 0.0). NO add_text(docid); NO :docno annotation.
- Record entry (cp = p_body, docno) in doc order; track last_cq = q_body.
- cp = the :item start = what ssr_ranking returns as container_p().

## finalize()
1. builder->finalize().
2. Build the reverse order: perm = [0..m-1] sorted by docno string. Adjacent-equal docnos in the sorted order = DUPLICATE -> hard error with the offending docno (the sort IS the uniqueness check; no separate pass).
3. Write the sidecar (always, by default):
   - sidecar.index: header {m, n = total docno bytes, last_cq, perm_width} + cp[] (post-compressed) + offset[] (post-compressed). cq is NOT stored.
   - sidecar.docno: concatenated docno text, UNCOMPRESSED (random access for lazy reads).
   - sidecar.perm: perm[] as raw fixed-width uint32 entries (m < 2^31), entry r at byte r*width.

## Resident vs disk split (sized for ~500M docs)
- Resident at open: cp[] (~4GB, sorted, binary searched) + offset[] (~4GB); last_cq from the header.
- Disk, lazy: sidecar.docno (~9GB; one docno read per probe/result via Reader::read at offset) and sidecar.perm (~2-4GB; entries read on demand).
- NOTE: FastidTxt compresses the whole text blob as one block and loads it fully resident -> cannot be reused for lazy random reads. So only cp[]/offset[] follow the post-compressed pattern; the docno blob is uncompressed. FastidTxt helpers are anon-namespace; write small local equivalents rather than refactor fastid_txt.cc.

## DocnoContentsSidecar reader -- open(working)
- docno_of(cp): binary-search resident cp[] -> i -> read blob[offset[i], offset[i+1]) lazily. Unknown cp -> not-found (not an error).
- span_of(cp) -> (p, q): i from cp[]; q = (i < m-1) ? cp[i+1]-1 : last_cq.
- cp_of(docno): DISK-BASED binary search over sidecar.perm -- at probe r read perm[r] (uint32) -> j, read docno text of j lazily, compare, narrow; return cp[j]. O(log m) tiny reads, no full load. Unknown -> not-found.
- Fetch helpers (methods; take a warren for txt()->translate):
  - text_by_cp(warren, cp): span_of -> translate(p, q); found=false if cp unknown.
  - text_by_docno(warren, docno): cp_of -> span_of -> translate; found=false if docno unknown.
- Holds persistent Reader handles to sidecar.docno and sidecar.perm.

## Tests (test/docno_contents_index.cc) -> AC#4 + new ACs
Index a few (docno, contents) via a real SimpleBuilder into a temp working dir, finalize, reopen, and assert:
1. NO :docno annotation and NO docno tokens (e.g. for docno shard_00037_72680, idx()->count(featurize("shard")) == 0; :docno feature absent).
2. cp<->docno round-trips both ways.
3. span_of derives cq correctly INCLUDING the last document (last_cq).
4. text_by_cp / text_by_docno return the right body.
5. Unknown docno / unknown cp -> not-found (not an error).
6. Duplicate docno -> finalize() fails with a clear message.
7. Empty/whitespace contents and empty docno -> add_document hard error.

## Build / verify -> AC#5
bazel build //src:cottontail; bazel test //test:tests //test:hazel_test (green). Nothing in apps/ or the query path is touched.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Empty-span guard confirmed against src/simple_builder.cc:568-592: add_text returns q<p (and does NOT advance the address) both for an empty string and for non-empty text that tokenizes to zero tokens (whitespace/punctuation-only). add_document therefore guards on (q_body < p_body) after add_text -> hard error, covering all no-indexable-token cases, not just the empty string. perm stored as native uint32 (m < 2^32 guarded at finalize).

Implemented src/docno_contents_index.{h,cc} (DocnoContentsIndexer + DocnoContentsSidecar) and test/docno_contents_index.cc (5 test cases). Verified: bazel build //src:cottontail green; bazel test //test:tests //test:hazel_test green (tests 43.2s, hazel 0.4s). The new tests are picked up automatically by the //test:tests glob; no BUILD edits. Reader random-access (FileReader seeks to where, src/working.cc:44) confirms the lazy docno/perm reads work. The only build warnings are the pre-existing simple_posting operator== C++20 ambiguity (known backlog item), not from this module. Nothing in apps/ or the query path was touched.

RE-SPEC for cp-native (doc-6, 2026-06-21). Reframed from a docno+sidecar indexer to a THIN cp-native CONTENT indexer. CHANGES: add_document takes ONLY contents and RETURNS cp (the :item start); it does NOT take or store a docno and builds NO map/sidecar. The custom DocnoContentsSidecar (binary cp<->docno format, docno-sorted permutation, lazy readers) is DELETED -- the cp<->docno map is now a SQLite store built by the index CLI (TASK-6.3) from a flat (docno,cp) dump the caller writes. docno is the application concern (doc-6), not this module concern. KEPT: the empty/zero-token contents hard error (the cp-uniqueness invariant). Rename the module/file to a cp-native name (no docno). ACs replaced. Authoritative: doc-6 + docs/indexing.md.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @claude
created: 2026-06-20 20:33
---
Plan + 2 new ACs added per the 2026-06-20 design discussion. Differences vs prior task text, all additive (nothing dropped): (1) concrete names docno_contents_index / DocnoContentsIndexer + DocnoContentsSidecar replace the placeholder TrecIndexer; (2) reverse docno->cp firmed from may-be-disk to MUST-be-disk (new AC); (3) empty/whitespace contents and empty docno are now an explicit hard error (new AC); (4) docno-text blob stored UNCOMPRESSED for lazy random reads (FastidTxt whole-blob compression is not reusable for the text); cp[]/offset[] reuse the post-compressed pattern via small local helpers, not by refactoring fastid_txt.cc; (5) fetch helpers are methods on the sidecar reader.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added a generic, format-agnostic TREC-like indexing module in src/. DocnoContentsIndexer drives a Builder to store contents + one :item annotation per document (no docno tokenization, no :docno); the internal id is the :item start address cp. add_document hard-errors on empty docno/contents or zero-token contents (protects the unique-cp invariant). finalize() writes a cp<->docno sidecar by default (sidecar.index = header + post-compressed cp[]/offset[] loaded resident; sidecar.docno = uncompressed docno blob read lazily; sidecar.perm = docno-sorted uint32 permutation read lazily) and validates docno uniqueness via the sort that builds the reverse index. DocnoContentsSidecar reads back docno_of/span_of (cq derived as cp_{i+1}-1, final cq stored once)/cp_of (disk-based binary search, no full load) + text_by_cp/text_by_docno fetch via translate. Sized for ~500M docs per docs/indexing.md sec 6. Verified by test/docno_contents_index.cc and the full suite (//test:tests //test:hazel_test green).
<!-- SECTION:FINAL_SUMMARY:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A src/ module provides a thin cp-native content indexer over a builder: add_document(contents) -> cp does add_text(contents) + one :item annotation per document (cp = the :item start) and RETURNS cp. It takes no docno, stores no docno, and builds no map/sidecar. Depends only on the Cottontail core; wired into src/BUILD.
- [ ] #2 The returned cp equals the :item container start (what ssr_ranking reports as container_p()), unique and strictly increasing by construction; finalize() finalizes the underlying builder.
- [ ] #3 add_document rejects empty/whitespace-only contents, and contents that yield no indexable tokens, as a HARD ERROR (an empty body occupies no address range, so its cp would collide with the next document). This is the cp-uniqueness invariant, independent of docno.
- [ ] #4 The custom DocnoContentsSidecar (binary cp<->docno format, permutation, lazy readers) and the docno parameter are REMOVED; the module/file is renamed to a cp-native name; the burrow has no :docno annotation and no docno tokens.
- [ ] #5 Unit tests (test/, wired into test/BUILD) index a few contents and assert: cp values are distinct and strictly increasing; the returned cp matches the :item container_p() (verified via a hopper over :item); the index has no :docno and no docno tokens; empty/zero-token contents are rejected.
- [ ] #6 bazel build //src:cottontail and the new test target (plus //test:tests //test:hazel_test) are green.
<!-- AC:END -->
