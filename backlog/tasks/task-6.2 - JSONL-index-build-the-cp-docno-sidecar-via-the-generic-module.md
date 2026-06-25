---
id: TASK-6.2
title: >-
  JSONL index: produce the new-style (TREC-generic) index via the generic
  indexer
status: Done
assignee:
  - '@claude'
created_date: '2026-06-19 03:44'
updated_date: '2026-06-25 20:20'
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
- [x] #1 cottontail-jsonl-index produces a cp-native burrow via the TASK-6.1 content indexer: per row parse (docid, contents), cp = add_document(contents); the burrow has contents + one :item per document, no :docno, no docno tokens. There is NO add_text(docid) and no sidecar.
- [x] #2 The indexer writes the flat dump at <burrow>/docid-cp.tsv (inside the burrow dir), docid<TAB>cp, one line per indexed row, cp matching that row :item start. (A docno-less corpus writes no flat file.)
- [x] #3 Contentless rows (empty/zero-token contents) are skipped (rows_skipped; fatal under --strict). docno uniqueness is NOT checked here -- it is enforced at SQLite build (TASK-6.3 UNIQUE index).
- [x] #4 The repo builds (//... minus the Boost-blocked targets) and the suite is green; the :docno-dependent query-path tests stay quarantined (the query side is redone cp-native under TASK-5).
- [x] #5 A test indexes a small fixture and asserts the burrow has no :docno / no docno tokens and the flat file lists (docid, cp) for each indexed row with cp matching the :item container_p(); docs (cli-spec, indexing.md) state cottontail-jsonl-index produces a cp-native burrow + a flat (docid,cp) dump, with the SQLite map built by the index CLI (TASK-6.3).
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Lands in the SAME branch/commit-pair as TASK-6.1 (PR #5) to restore the build green after 6.1 deletes the old module.
1. apps/jsonl_core.cc jsonl_index: replace DocnoContentsIndexer::make(builder,working) with ContentIndexer::make(builder). Per row: addr cp; if(!indexer->add_document(contents,&cp,&row_error)){skip; fatal under --strict;} else append docid<TAB>cp to the flat dump and rows++. No add_text(docid), no :docno, no duplicate-docid check (moves to TASK-6.3 SQLite UNIQUE).
2. Flat dump at <burrow>/docid-cp.tsv via working->make_name("docid-cp.tsv"): open before the row loop, write docid<TAB>cp per indexed row (streaming, no RAM accumulation), close after indexer->finalize(). (JSONL path always has docid, so always written.)
3. test/jsonl.cc: REMOVE JsonlSidecar.RoundTrip (sidecar deleted). QUARANTINE/REWRITE JsonlIndex.DuplicateDocidFails (a dup docid no longer fails at index time; it yields two rows + two flat lines). ADD a fixture test (AC#5): index a small fixture -> assert no :docno / no docno tokens, and docid-cp.tsv lists (docid,cp) per indexed row with cp == the :item container_p(). The already-DISABLED_ query/cover/stem/get/count tests stay quarantined (A3 = TASK-5.12 restores the non-cover ones cp-native).
4. Docs + stale comments: apps/jsonl_core.h (sidecar comment ~lines 10-16), apps/cottontail-jsonl-index.cc header, docs/cottontail-jsonl-cli-spec.md, docs/indexing.md -> state the indexer produces a cp-native burrow + a flat (docid,cp) dump, with the cp<->docno SQLite map built by the index CLI (TASK-6.3).
5. Gate: bazel build -c dbg --cxxopt=-Og -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example; bazel test -c dbg //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test  (all green; :docno query-path tests remain quarantined for A3).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). jsonl_index uses the TASK-6.1 content indexer (add_document(contents) -> cp) and dumps a flat (docid<TAB>cp) file alongside the cp-native burrow INSTEAD of building a sidecar. The prior implementation (drives DocnoContentsIndexer, writes the sidecar) is REPLACED. docno uniqueness moves to the SQLite build (TASK-6.3). Contentless rows still skipped (fatal under --strict). Authoritative: doc-6 + docs/indexing.md.

Implemented in apps/jsonl_core.cc jsonl_index: ContentIndexer::make(builder); per row addr cp + add_document(contents,&cp); append docid<TAB>cp to <burrow>/docid-cp.tsv (working->make_name; opened before the row loop, closed after finalize). No add_text(docid), no :docno, no dup-docid check. test/jsonl.cc: dropped #include docno_contents_index.h (-> src/cottontail.h), added <map>; rewrote JsonlIndex.DuplicateDocidFails -> DuplicateDocidIndexedNotRejected (dup docid accepted, two distinct-cp flat lines); replaced JsonlSidecar.RoundTrip -> JsonlFlatDump.MapsDocidToItemStart (no :docno/no docno tokens; flat dump maps each docid to a real :item start whose body translates back). Docs/comments: apps/jsonl_core.h, apps/cottontail-jsonl-index.cc headers + docs/cottontail-jsonl-cli-spec.md (3.3/3.4/4 warning) now state cp-native burrow + flat (docid,cp) dump, SQLite map by TASK-6.3; indexing.md already cp-native. VERIFIED: full build (//... minus Boost) green; //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test all PASS; new jsonl tests run (5/5); real cottontail-jsonl-index binary on test/jsonl/plain emits docid-cp.tsv with strictly-increasing cps and no sidecar files. :docno query-path tests remain DISABLED_ for A3/TASK-5.12.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
cottontail-jsonl-index now produces a cp-native burrow (contents + one :item per doc, no :docno/no docno tokens) via the TASK-6.1 ContentIndexer, and dumps a flat <burrow>/docid-cp.tsv (docid<TAB>cp per indexed row) for the TASK-6.3 SQLite map. Duplicate-docid detection moved off the index path. Verified by the full build + all four suites green and a real-binary smoke test.
<!-- SECTION:FINAL_SUMMARY:END -->
