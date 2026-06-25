---
id: TASK-5.12
title: >-
  A3 — Engine: cp-native query-path cutover (open warren, get_document/search by
  cp, restore tests)
status: In Progress
assignee:
  - '@claude'
created_date: '2026-06-21 04:42'
updated_date: '2026-06-25 22:14'
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
2. get_document accepts a cp (hot path) OR a docno (the CLI --get boundary case). By
   cp: translate(cp, cq), cq from the :item container at cp -- no map. By docno: read
   the SQLite map <burrow>/docno-cp.sqlite (read-only) for docno->cp, then translate.
   The boundary --get <docno> is the ONLY place C++ touches the map; cover_search and
   exclusion never do.
3. search emission (jsonl_query, text + gcl): rank within plain :item; each returned
   hit carries its `cp` (= container_p()). Drop the :docno hopper; no docno in the
   engine.
4. CLI + server: cottontail-jsonl-query --get takes a docno (reads the map, read-only)
   or a cp; --text/--gcl emit cp; the server /tools/{get_document,search_text,
   search_gcl} use the cp-native functions (the hot path stays map-free). C++ gains a
   read-only SQLite dependency used solely by the boundary --get <docno>.
5. Tests: restore the TASK-6.2-quarantined non-cover query-path tests (get / search /
   count in test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc) as cp-native
   tests; cover_search tests belong to A1/A2.

## Non-goals

- cover_search (A1/A1b/A2).
- The Python isj agent (B/C); the SQLite map + index CLI (TASK-6.3); the docno->cp
  human-fetch wrapper (Python).
- C++ touches the map only on the boundary --get <docno> (read-only); the hot
  cover_search / exclusion path is map-free.
<!-- SECTION:DESCRIPTION:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @claude
created: 2026-06-25 21:23
---
NAMING (doc-7): adopt the canonical vocabulary when doing the cp-native query cutover. Internally use docno (identity) and text (body), never docid/contents. The query/response path still emits docid -- Hit.docid and the "docid" keys in apps/jsonl_json.cc (search/get responses + describe) -- which A3 must rename per doc-7: results carry cp on the wire; any persisted id is docno; the SQLite reader table is docno_map at <burrow>/docno-cp.sqlite.
---
<!-- COMMENTS:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 open_burrow returns just the started warren (default container :item); it opens NO sidecar and builds NO docno->cp cache -- the multi-threaded query path is map-free.
- [ ] #2 get_document (core jsonl_get + server /tools/get_document + CLI --get) is BY cp ONLY: translate(cp, cq), cq from the :item container at cp -- no docno and no map anywhere in C++. An unknown cp is not-found (not an error). docno->cp is Python-only (DocnoMap, TASK-6.3); human docno fetch is the Python helper (TASK-6.4).
- [ ] #3 search_text and search_gcl rank within plain :item and each returned hit carries its cp (= container_p()); the :docno hopper is removed; no docno is materialized in the engine.
- [ ] #4 cottontail-jsonl-query --get takes a cp; --text/--gcl emit cp. The CLI and the SERVER /tools/{get_document,search_text,search_gcl} are cp-only and NEVER touch docno or any map. C++ takes NO SQLite dependency and never sees docno (human docno fetch is the Python helper, TASK-6.4).
- [ ] #5 The TASK-6.2-quarantined NON-cover query-path tests (get/search/count cases in test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc) are restored as cp-native tests and pass; cover_search tests stay with A1/A2.
- [ ] #6 bazel build //... minus the Boost-blocked targets and the suite (//test:tests //test:hazel_test //test:jsonl_test //test:jsonl_server_test) are green.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Revised cp-only: the C++ engine NEVER reads the map (doc-8). docno leaves C++ entirely; docno<->cp is Python-only (DocnoMap, TASK-6.3). No MODULE.bazel change, no SQLite dependency. Lands on PR #5.

C++ cutover (apps/, cp-only):
1. jsonl_core.h: Hit.docid (string) -> Hit.cp (addr).
2. jsonl_core.cc jsonl_query: drop the :docno hopper; h.cp = r.container_p(); body/full_text via translate(container_p(), container_q()). Leave jsonl_cover_search (A1/A2) untouched.
3. jsonl_core.cc jsonl_get(warren, addr cp): cq from the :item container at cp (hopper_from_gcl(":item") tau(cp)); translate(cp, cq); unknown cp -> found=false.
4. jsonl_json.{h,cc}: hit "docid" -> "cp" (integer); get_json -> {cp, found, text}; describe_json search_text/search_gcl/get_document schemas -> cp. (cover_search describe stays A2.)
5. cottontail-jsonl-query.cc: --get <cp> (by cp, integer); --text/--gcl emit cp. No docno, no SQLite.
6. cottontail-jsonl-server.cc: /tools/get_document by cp; search_* hits carry cp; map-free (already).
7. Confirm open_burrow is map-free (AC#1 already holds).

Tests (restore cp-native; assert on translate(cp,cq) content, not docid strings):
- test/jsonl.cc: un-DISABLE + rewrite JsonlQuery.*, JsonlGet.*, JsonlCount.*, JsonlExplain.* to cp; cover/stem-cover stay DISABLED_ (A1/A2).
- test/jsonl_cli.cc, test/jsonl_server.cc: restore the get/search/count cases cp-native.

Out of scope: cover_search (A1/A1b/A2); the Python fetch helper (TASK-6.4).
Propagation: indexing.md sec 5/6 -> C++ cp-only + docno<->cp Python-only; doc-8 records it.
Gate: bazel build //... minus Boost; //test:{tests,hazel_test,jsonl_test,jsonl_server_test} green.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21; refined 2026-06-22 for issue #8). The HOT path and the SERVER are cp-only / map-free: open_burrow returns just the warren; search returns cp; the :docno hopper is dropped; the server get_document is BY cp. Only the CLI cottontail-jsonl-query --get additionally resolves a docno -> cp by reading the SQLite map <burrow>/docno-cp.sqlite READ-ONLY (a read-only SQLite dep used solely there), then get-by-cp. cp is on the wire; the cp->docno rewrite for persisted output is C2. The server never knows about docno. Authoritative: doc-6 + docs/indexing.md.
<!-- SECTION:NOTES:END -->
