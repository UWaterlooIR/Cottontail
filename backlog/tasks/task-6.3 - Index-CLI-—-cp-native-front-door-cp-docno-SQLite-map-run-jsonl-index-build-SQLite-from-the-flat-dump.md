---
id: TASK-6.3
title: >-
  Index CLI — cp-native front door + cp<->docno SQLite map (run jsonl-index,
  build SQLite from the flat dump)
status: To Do
assignee: []
created_date: '2026-06-21 18:44'
updated_date: '2026-06-21 23:27'
labels:
  - python
  - indexing
dependencies:
  - TASK-6.2
references:
  - backlog/docs/doc-6
  - docs/indexing.md
  - apps/cottontail-jsonl-index.cc
parent_task_id: TASK-6
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

Python (the isj uv project or a tooling module). The cp-native front-door indexer
plus the cp<->docno SQLite map. Depends on TASK-6.2 (the C++ cottontail-jsonl-index
that dumps the flat docid<TAB>cp file). See doc-6 + docs/indexing.md section 6.

## What to do (doc-6 model)

A Python CLI is the single front door for building a searchable index from JSONL:
1. Run the C++ cottontail-jsonl-index (subprocess) -> a cp-native burrow
   (contents + :item) + a flat docid<TAB>cp dump alongside it.
2. Load <burrow>/docid-cp.tsv into the SQLite store <burrow>/docno-cp.sqlite: table
   (cp INTEGER PRIMARY KEY, docno TEXT UNIQUE). The UNIQUE index enforces docno
   uniqueness.
3. Delete the flat file on success. On failure (e.g. a duplicate docid) leave the
   burrow + flat file in place and exit non-zero, naming the offending docno.
For a docno-less corpus there is no flat file and no SQLite (a cp-only burrow).

The Python reader module isj_agent/docno_map.py (importable by C2/C3) opens the SQLite READ-ONLY (mode=ro / immutable=1) and (stdlib sqlite3, no extra dependency)
exposes the boundary lookups: cp->docno (single + batch, for the run-output rewrite
in TASK-5 C2) and docno->cp (for a human/external fetch -> then the C++ get-by-cp).
The multi-threaded C++ query path never opens the SQLite.

## Non-goals

- The C++ indexer / burrow (TASK-6.1/6.2).
- The query engine and the Searcher (TASK-5).
- A C++ SQLite dependency: C++ writes the flat file only; all SQLite (build + read)
  is Python.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A Python CLI is the front door: given JSONL input + an output burrow path, it subprocesses cottontail-jsonl-index to build the cp-native burrow + the flat dump at <burrow>/docid-cp.tsv, then builds the SQLite map, then deletes the flat file.
- [ ] #2 The SQLite store (cp INTEGER PRIMARY KEY, docno TEXT UNIQUE) is built at <burrow>/docno-cp.sqlite from <burrow>/docid-cp.tsv; the UNIQUE index enforces docno uniqueness -- a duplicate docid fails with a clear message naming the offender, leaving the burrow + flat file in place and exiting non-zero.
- [ ] #3 On success the flat file is deleted; a docno-less corpus (no flat file) builds no SQLite (a cp-only burrow).
- [ ] #4 The reader module isj_agent/docno_map.py (stdlib sqlite3, no extra dependency) opens the map READ-ONLY (mode=ro / immutable=1) and exposes cp->docno (single + batch) and docno->cp; it is importable by C2/C3. The multi-threaded C++ query path never opens the map (the C++ CLI --get <docno> reads it as a boundary op, A3).
- [ ] #5 Tests build a tiny burrow + SQLite from a fixture and round-trip docid->cp and cp->docno; a duplicate docid fails the build naming the offending docno.
<!-- AC:END -->
