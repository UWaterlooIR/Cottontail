---
id: TASK-6.3
title: >-
  Index CLI — cp-native front door + cp<->docno SQLite map (run jsonl-index,
  build SQLite from the flat dump)
status: Done
assignee:
  - '@claude'
created_date: '2026-06-21 18:44'
updated_date: '2026-06-25 20:46'
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
- [x] #1 A Python CLI is the front door: given JSONL input + an output burrow path, it subprocesses cottontail-jsonl-index to build the cp-native burrow + the flat dump at <burrow>/docid-cp.tsv, then builds the SQLite map, then deletes the flat file.
- [x] #2 The SQLite store (cp INTEGER PRIMARY KEY, docno TEXT UNIQUE) is built at <burrow>/docno-cp.sqlite from <burrow>/docid-cp.tsv; the UNIQUE index enforces docno uniqueness -- a duplicate docid fails with a clear message naming the offender, leaving the burrow + flat file in place and exiting non-zero.
- [x] #3 On success the flat file is deleted; a docno-less corpus (no flat file) builds no SQLite (a cp-only burrow).
- [x] #4 The reader module isj_agent/docno_map.py (stdlib sqlite3, no extra dependency) opens the map READ-ONLY (mode=ro / immutable=1) and exposes cp->docno (single + batch) and docno->cp; it is importable by C2/C3. The multi-threaded C++ query path never opens the map (the C++ CLI --get <docno> reads it as a boundary op, A3).
- [x] #5 Tests build a tiny burrow + SQLite from a fixture and round-trip docid->cp and cp->docno; a duplicate docid fails the build naming the offending docno.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Lands on PR #5 (claude/trec-rag-2026-design). No new runtime deps (stdlib sqlite3). Decisions: binary path via config.toml [index].binary (+ --index-bin override); console-script entry cottontail-index.
1. isj_agent/docno_map.py (READER, AC#4): class DocnoMap over sqlite3.connect('file:<path>?immutable=1', uri=True) (read-only, lock-free, fit for a static burrow). Methods: docno(cp)->str|None; docnos(cps: Iterable[int])->dict[int,str] (batched IN, chunked <=900 for SQLITE_MAX_VARIABLE_NUMBER); cp(docno)->int|None; context manager + close(). Importable by C2/C3 as isj_agent.docno_map.
2. isj_agent/index.py (FRONT DOOR, AC#1-3) with main():
   - build_sqlite_map(flat_path, sqlite_path): stream <burrow>/docid-cp.tsv -> table (cp INTEGER PRIMARY KEY, docno TEXT UNIQUE); batched executemany; build PRAGMAs (journal_mode=OFF, synchronous=OFF). On a UNIQUE violation, narrow the failing batch row-by-row (savepoint) to name the offending docno -> raise DuplicateDocnoError(docno).
   - argparse: mirror the C++ flags (--input/--burrow/--docid-field/--contents-field/--tokenizer/--stem/--buffer/--limit/--strict/--overwrite/--verbose) + --config (default isj/config.toml) + --index-bin override. Binary resolution: --index-bin -> config [index].binary (repo-root-relative or absolute) -> error if unresolved/not executable.
   - Steps: (1) subprocess cottontail-jsonl-index (passthrough flags); non-zero return -> exit non-zero. (2) flat=<burrow>/docid-cp.tsv; if ABSENT -> cp-only burrow, done (AC#3). (3) sqlite=<burrow>/docno-cp.sqlite; remove any stale; build_sqlite_map. (4) SUCCESS: flat.unlink() + print summary (AC#3). (5) DuplicateDocnoError: remove the partial sqlite, LEAVE burrow+flat in place, print "duplicate docid '<docno>'", exit non-zero (AC#2).
3. config.toml + config.example.toml: new [index] section, binary = "bazel-bin/apps/cottontail-jsonl-index" (repo-root-relative default).
4. pyproject.toml: [project.scripts] cottontail-index = "isj_agent.index:main".
5. Tests (AC#5): tests/test_docno_map.py (build sqlite from a fixture flat file; round-trip docid<->cp and cp<->docno; batch; unknown->None; duplicate docid -> DuplicateDocnoError naming offender; read-only write rejected). tests/test_index_cli.py (pure path: stub the subprocess to drop a known docid-cp.tsv, assert sqlite built + flat deleted; + one auto-SKIPPED e2e running the real cottontail-index on a tiny JSONL fixture, skipped when the binary is unresolvable).
Validate: uv sync --project isj; uv run --project isj pytest. Forward-compat: schema (cp PK, docno UNIQUE) + immutable=1 read-only <-> A3/5.12 C++ --get <docno>; docnos(cps) batch <-> C2/5.8 cp->docno rewrite.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented in isj/: isj_agent/docno_map.py (DocnoMap; sqlite3 immutable=1 read-only; docno(cp)/docnos(cps batch, chunked 900)/cp(docno); table docno_map) and isj_agent/index.py (build_sqlite_map with batched insert + row-by-row narrowing to name a duplicate; front-door main(): subprocess cottontail-jsonl-index, build SQLite, delete flat on success; on DuplicateDocnoError remove partial sqlite, leave burrow+flat, exit 1; no-flat -> cp-only). Binary path from config.toml [index].binary (repo-root-relative) + --index-bin override; console script cottontail-index in pyproject. config.example.toml [index] added. Tests: tests/test_docno_map.py (4) + tests/test_index_cli.py (5, incl. an auto-skipped-if-unbuilt e2e against the real binary). VERIFIED: uv sync + uv run pytest = 16 passed (e2e RAN against bazel-built binary, not skipped); cottontail-index --help OK; manual front-door run on test/jsonl/plain built docno-cp.sqlite (4 docids), removed docid-cp.tsv, DocnoMap round-tripped cp<->docno. Table name docno_map is the contract A3/TASK-5.12 must read.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added the cp-native index front door (isj_agent.index / cottontail-index console script): runs cottontail-jsonl-index, builds the cp<->docno SQLite map (docno_map(cp PK, docno UNIQUE)) at <burrow>/docno-cp.sqlite from the flat docid-cp.tsv dump, deletes the flat on success, and fails non-zero naming a duplicate docid (leaving burrow+flat for inspection). Added the read-only reader isj_agent/docno_map.py (immutable=1; cp->docno single+batch, docno->cp) for C2/C3 and the A3 boundary. Binary path via config.toml [index].binary (+ --index-bin). Verified: 16 pytest pass incl. a real-binary e2e, plus a manual front-door run.
<!-- SECTION:FINAL_SUMMARY:END -->
