---
id: TASK-5.12
title: >-
  A3 — Engine: cp/sidecar query-path plumbing (open sidecar + docno-cp cache,
  get_document, search emission, restore tests)
status: To Do
assignee: []
created_date: '2026-06-21 04:42'
labels:
  - cpp
  - searcher
  - engine
dependencies:
  - TASK-6.1
references:
  - docs/indexing.md
  - backlog/docs/doc-5
  - apps/jsonl_core.cc
  - src/docno_contents_index.h
parent_task_id: TASK-5
ordinal: 5900
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

C++. The SHARED engine plumbing for the cp/sidecar cutover (doc-5) plus the
NON-cover-search query path. May modify: apps/jsonl_core.{h,cc},
apps/jsonl_json.{h,cc}, apps/cottontail-jsonl-query.cc,
apps/cottontail-jsonl-server.cc; tests in test/jsonl.cc, test/jsonl_cli.cc,
test/jsonl_server.cc. Do NOT change search_gcl semantics or the GCL core. Depends
on TASK-6.1 (the DocnoContentsSidecar module).

## Why this is its own task (A3)

cover_search (A1/A1b/A2) is the agent's tool, but the cp/sidecar cutover also needs
shared infrastructure and the rest of the query path reframed. That work is shared
by cover_search, get_document, and search, so it lives here; A1/A2 build on its
open-sidecar + cache plumbing. (Split out of A1's RE-SPEC note, 2026-06-21.)

## What to do (doc-5 model: docno on the wire, cp internal)

1. Shared open path: open_burrow returns the warren AND its DocnoContentsSidecar
   (DocnoContentsSidecar::open on the burrow working dir), plus a process-lifetime
   docno->cp cache keyed on the open burrow (docno->cp is immutable for a static
   burrow). cp stays engine-internal (doc-5 invariant).
2. get_document (jsonl_get): docno -> cp (sidecar reverse, cached) ->
   txt()->translate(cp,cq). No :docno. Unknown docno -> found=false (not an error).
3. search emission (jsonl_query, text + gcl): rank within plain :item; for the
   RETURNED PAGE ONLY map cp -> docno (sidecar forward) to fill each hit docid.
   No :docno hopper; internal results stay keyed on cp.
4. CLI + server: cottontail-jsonl-query (--get / --text / --gcl) and the server
   /tools/{get_document,search_text,search_gcl} open the sidecar and use the
   reframed functions.
5. Tests: restore the TASK-6.2-quarantined query-path tests that are NOT
   cover_search-specific (the get/search/count cases in test/jsonl.cc,
   test/jsonl_cli.cc, test/jsonl_server.cc) as new-model tests; cover_search tests
   belong to A1/A2.

## Non-goals

- cover_search (A1/A1b/A2) and its exclude/counts -- their tasks.
- The Python isj agent (B/C); the indexer (TASK-6).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 open_burrow returns the warren plus its DocnoContentsSidecar (opened on the burrow working dir); a process-lifetime docno->cp cache keyed on the open burrow backs the reverse lookups; cp is never emitted on the wire or persisted (doc-5 invariant).
- [ ] #2 get_document resolves docno -> cp (sidecar reverse, cached) -> txt()->translate(cp,cq); no :docno; an unknown docno is found=false (not an error).
- [ ] #3 search_text and search_gcl rank within plain :item and fill each returned hit docid via cp -> docno (sidecar forward) for the returned page only; internal results stay keyed on cp; no :docno hopper.
- [ ] #4 cottontail-jsonl-query (--get / --text / --gcl) and the server tools get_document/search_text/search_gcl open the sidecar and use the reframed functions.
- [ ] #5 The TASK-6.2-quarantined NON-cover query-path tests (get/search/count cases in test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc) are restored as new-model tests against Scrapheap/climbmix-100k-porter.burrow and pass; cover_search tests stay with A1/A2.
- [ ] #6 bazel build //... minus the Boost-blocked targets and the suite (//test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test) are green.
<!-- AC:END -->
