---
id: TASK-6.2
title: >-
  JSONL index: produce the new-style (TREC-generic) index via the generic
  indexer
status: To Do
assignee:
  - '@claude'
created_date: '2026-06-19 03:44'
updated_date: '2026-06-21 18:41'
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

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
## 1. jsonl_index (apps/jsonl_core.cc) -- use the generic indexer
Keep existing setup (find_shards, tokenizer/stemmer selection, Working::mkdir, Featurizer, SimpleBuilder::make with opts.buffer). Then:
- include src/docno_contents_index.h.
- Wrap the builder: auto indexer = DocnoContentsIndexer::make(builder, working, &error).
- In the row loop, replace the 4-call block (add_text(docid)+:docno, add_text(contents)+:item over p_id..q_body) with a single indexer->add_document(docid, contents, &error).
- Q1 DECISION: an add_document that returns false is treated as a SKIPPED row (++rows_skipped), like the existing missing/non-string-field handling; fatal only under --strict. Covers empty docid, empty contents, and zero-token contents without aborting a large crawl. (Duplicate docids stay a hard build failure -- detected at finalize, AC#2.)
- Replace builder->finalize with indexer->finalize (writes the sidecar; duplicate docid fails here).
Result: burrow = contents + one :item per doc + sidecar; no :docno, no docno tokens; internal id = :item start cp. Old style removed, no flag.

## 2. cottontail-jsonl-index.cc + IndexSummary
CLI already just calls jsonl_index and prints the summary -- no flag to add/remove. Update the header comments in cottontail-jsonl-index.cc and apps/jsonl_core.h that describe the old :docno model. No new IndexSummary field (rows_indexed already = doc count).

## 3. Query side -- left in source, untouched (deliberate)
jsonl_query/jsonl_get/jsonl_count/jsonl_explain/jsonl_cover_search still compile; the -query/-server binaries still build. They read :docno, so against a new-style burrow they return empty docids (no crash). Not rewritten here -- deferred cutover (doc-4). Docs note the query side is pending the redo.

## 4. Tests -- Q2 DECISION: quarantine query-dependent cases with DISABLED_ in place; keep structure cases; add sidecar test
Recon: 44 query/:docno-dependent cases (A), 16 indexing/structure-only (B).
- test/jsonl.cc: keep the 6 B cases (BuildCounts, SkipNonStrict, StrictIsFatal, Utf8KeepsAccentedWordsWholeAsciiDoesNot, DefaultsToUtf8AndReportsIt, UnknownTokenizerIsAnError). DISABLED_ the ~34 A cases (JsonlQuery/Explain/Cover/Get/Count + Utf8WithStem). Add a new JsonlSidecar.RoundTrip case (AC#3): jsonl_index a small fixture -> open_burrow + DocnoContentsSidecar::open -> assert cp_of(docid)/docno_of(cp) round-trip, text_by_cp/text_by_docno return the body, and idx count of :docno == 0.
- test/jsonl_cli.cc: keep the 7 B cases (summary-to-stdout, usage/runtime-error exits, describe, stem/cover error-path exits). DISABLED_ the 8 A query/get/count cases.
- test/jsonl_server.cc: all 3 cases are query e2e -> DISABLED_ all 3 (binary still builds; 0 tests run -> target still green). Keep the jsonl_server_test BUILD target.
Query functions remain in source (the cases are preserved for the deferred redo; reversible).

## 5. Docs (AC#5)
- docs/cottontail-jsonl-cli-spec.md: rewrite the index-model lines (~148-162) to the new model (:item = body only; docno lives in the sidecar, not the index; no :docno annotation). Add a prominent note to the query/cover_search/get sections that the query side is being redone against the cp/sidecar model and does NOT work against new-style burrows yet.
- docs/indexing.md: change the section-1 framing from this-note-is-the-target to implemented-by-jsonl_index, and note the retrieval-side cutover is still pending (doc-4).

## 6. Build / verify
bazel build //... minus the four Boost-blocked targets; then bazel test //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test -- all green.

## 7. AC mapping
#1 -> step 1 (+2). #2 -> finalize duplicate failure (CLI exit 2). #3 -> new JsonlSidecar.RoundTrip. #4 -> steps 4 + 6 (quarantine A, keep B, suite green). #5 -> step 5.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented. jsonl_index now drives DocnoContentsIndexer (apps/jsonl_core.cc): per row add_document(docid, contents); an add_document failure (empty docid/contents or zero-token contents) is a SKIP (++rows_skipped, fatal only under --strict, per Q1); indexer->finalize writes the sidecar and fails the build on a duplicate docid. Removed the old add_text(docid)+:docno block. Header comments updated in jsonl_core.h and cottontail-jsonl-index.cc. Query side (jsonl_query/get/count/explain/cover_search) left in source unchanged (pending the doc-4 cutover). Tests: 45 :docno/query-dependent cases quarantined with DISABLED_ (34 in jsonl.cc, 8 in jsonl_cli.cc, 3 in jsonl_server.cc) via an allowlist script that asserted each rename hit exactly once; the 16 indexing/structure cases kept; added JsonlSidecar.RoundTrip (AC#3) and JsonlIndex.DuplicateDocidFails (AC#2). Docs: cli-spec 3.3/3.4 + a query-side pending-redo banner on 4 + 7/8 fixes; indexing.md 1. Verified: bazel build //... minus the 4 Boost targets (47 targets) green; bazel test //test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test all green.

RE-SPEC for cp-native (doc-6, 2026-06-21). jsonl_index uses the TASK-6.1 cp-native CONTENT indexer (add_document(contents) -> cp) and, per row, dumps a flat (docid<TAB>cp) file alongside the burrow INSTEAD of building a sidecar. CHANGES: no sidecar; the burrow is cp-native (contents + :item only); docno uniqueness is NOT validated here -- it is enforced when the SQLite map is built (TASK-6.3, the UNIQUE index). KEPT: contentless rows skipped (fatal under --strict). The SQLite map + the Python front-door CLI are TASK-6.3. ACs replaced. Authoritative: doc-6 + docs/indexing.md.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
cottontail-jsonl-index now produces the new-style (TREC-generic) burrow via the TASK-6.1 generic indexer: each document is stored as contents + one :item annotation, with the docid only in the cp<->docno sidecar (no docno tokenization, no :docno, no opt-in flag). jsonl_index calls DocnoContentsIndexer::add_document per row (contentless rows skipped like malformed rows; fatal under --strict) and indexer->finalize (writes the sidecar; a duplicate docid fails the build with a clear message). The :docno-based query side (jsonl_query/get/count/explain/cover_search and the server tools) is left in source unchanged and is the deferred cp/sidecar cutover (doc-4) -- its query-path tests are quarantined with DISABLED_ (45 cases) and the indexing/structure tests stay green; new tests JsonlSidecar.RoundTrip and JsonlIndex.DuplicateDocidFails cover the new behavior. Docs (cli-spec 3.3/3.4/4/7/8, indexing.md 1) state the new-style index + sidecar and that the query side is pending the redo. Verified: full build minus the Boost targets and all four test targets green.
<!-- SECTION:FINAL_SUMMARY:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 cottontail-jsonl-index produces a cp-native burrow via the TASK-6.1 content indexer: per row parse (docid, contents), cp = add_document(contents); the burrow has contents + one :item per document, no :docno, no docno tokens. There is NO add_text(docid) and no sidecar.
- [ ] #2 The indexer writes a flat (docid<TAB>cp) file alongside the burrow, one line per indexed row, cp matching that row :item start. (A docno-less corpus writes no flat file.)
- [ ] #3 Contentless rows (empty/zero-token contents) are skipped (rows_skipped; fatal under --strict). docno uniqueness is NOT checked here -- it is enforced at SQLite build (TASK-6.3 UNIQUE index).
- [ ] #4 The repo builds (//... minus the Boost-blocked targets) and the suite is green; the :docno-dependent query-path tests stay quarantined (the query side is redone cp-native under TASK-5).
- [ ] #5 A test indexes a small fixture and asserts the burrow has no :docno / no docno tokens and the flat file lists (docid, cp) for each indexed row with cp matching the :item container_p(); docs (cli-spec, indexing.md) state cottontail-jsonl-index produces a cp-native burrow + a flat (docid,cp) dump, with the SQLite map built by the index CLI (TASK-6.3).
<!-- AC:END -->
