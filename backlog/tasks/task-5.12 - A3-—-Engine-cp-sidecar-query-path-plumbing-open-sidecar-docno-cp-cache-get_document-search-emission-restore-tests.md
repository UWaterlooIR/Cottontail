---
id: TASK-5.12
title: >-
  A3 — Engine: cp-native query-path cutover (open warren, get_document/search by
  cp, restore tests)
status: To Do
assignee: []
created_date: '2026-06-21 04:42'
updated_date: '2026-06-21 19:36'
labels:
  - cpp
  - searcher
  - engine
dependencies:
  - TASK-6.2
references:
  - docs/indexing.md
  - backlog/docs/doc-6
  - apps/jsonl_core.cc
  - apps/cottontail-jsonl-server.cc
parent_task_id: TASK-5
ordinal: 5900
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

C++. The cp-native query-path cutover (doc-6) for the NON-cover-search tools. May
modify: apps/jsonl_core.{h,cc}, apps/jsonl_json.{h,cc}, apps/cottontail-jsonl-query.cc,
apps/cottontail-jsonl-server.cc; tests in test/jsonl.cc, test/jsonl_cli.cc,
test/jsonl_server.cc. Do NOT change search_gcl semantics or the GCL core. The burrow
is cp-native (TASK-6.2); there is NO sidecar.

## What to do (doc-6: cp on the wire, sidecar-free hot path)

1. open_burrow returns just the started warren (default container :item). NO sidecar,
   NO docno->cp cache -- the hot path is map-free.
2. get_document is BY cp: get_document(cp) -> translate(cp, cq), with cq from the
   :item container at cp. No docno, no :docno hopper. (The human docno->cp fetch is a
   Python step -- SQLite docno->cp, then this get-by-cp -- not a C++ tool.)
3. search emission (jsonl_query, text + gcl): rank within plain :item; each returned
   hit carries its `cp` (= container_p()). Drop the :docno hopper; no docno in the
   engine.
4. CLI + server: cottontail-jsonl-query (--get takes a cp; --text/--gcl emit cp) and
   the server /tools/{get_document,search_text,search_gcl} use the cp-native
   functions. C++ stays SQLite-free.
5. Tests: restore the TASK-6.2-quarantined non-cover query-path tests (get / search /
   count in test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc) as cp-native
   tests; cover_search tests belong to A1/A2.

## Non-goals

- cover_search (A1/A1b/A2).
- The Python isj agent (B/C); the SQLite map + index CLI (TASK-6.3); the docno->cp
  human-fetch wrapper (Python).
- A C++ SQLite dependency: C++ is cp-only here.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). SUPERSEDES the prior docno/sidecar note. The hot path is sidecar-free: open_burrow returns just the warren (no sidecar, no docno->cp cache); get_document is BY cp; search returns cp; the :docno hopper is dropped. cp is on the wire (the working id); the cp->docno rewrite is C2 persistence; the docno->cp human fetch is Python (SQLite, TASK-6.3) then C++ get-by-cp. C++ stays SQLite-free. ACs replaced. Authoritative: doc-6 + docs/indexing.md.
<!-- SECTION:NOTES:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 open_burrow returns just the started warren (default container :item); it opens NO sidecar and builds NO docno->cp cache -- the multi-threaded query path is map-free.
- [ ] #2 get_document is by cp: get_document(cp) returns translate(cp, cq) (cq from the :item container at cp); no docno, no :docno hopper; an unknown/invalid cp is not-found (not an error).
- [ ] #3 search_text and search_gcl rank within plain :item and each returned hit carries its cp (= container_p()); the :docno hopper is removed; no docno is materialized in the engine.
- [ ] #4 cottontail-jsonl-query (--get <cp>, --text, --gcl) and the server /tools/{get_document,search_text,search_gcl} use the cp-native functions; C++ stays SQLite-free (the docno->cp human fetch is a Python step in TASK-6.3 / isj, not a C++ tool).
- [ ] #5 The TASK-6.2-quarantined NON-cover query-path tests (get/search/count cases in test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc) are restored as cp-native tests and pass; cover_search tests stay with A1/A2.
- [ ] #6 bazel build //... minus the Boost-blocked targets and the suite (//test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test) are green.
<!-- AC:END -->
