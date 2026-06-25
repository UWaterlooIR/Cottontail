---
id: doc-8
title: >-
  Decision — the C++ engine is cp-only; docno<->cp is Python-only (no C++ map
  read)
type: other
created_date: '2026-06-25 22:14'
updated_date: '2026-06-25 22:15'
---
Status: accepted (2026-06-25). Refines doc-6 (cp-native identity).

## Decision

The **C++ engine never opens the `cp <-> docno` SQLite map.** docno does not
appear in C++ at all: the query path (search / get / count / explain), the CLI
`cottontail-jsonl-query`, and the HTTP server are **cp-only**.

- Search results carry `cp` (= `:item` container_p()); `get_document` /
  `--get` take a `cp`; `--text` / `--gcl` emit `cp`.
- `docno <-> cp` lives **only in Python** — `isj_agent.docno_map.DocnoMap`
  (TASK-6.3): `cp -> docno` for the run-output rewrite (C2), `docno -> cp` for a
  human/external fetch.
- The **human "fetch by docno"** path is a small Python helper (TASK-6.4):
  `DocnoMap.cp(docno)` -> subprocess `cottontail-jsonl-query --get <cp>` -> text.

## Why this supersedes the earlier spec

doc-6 / `docs/indexing.md` originally had the C++ CLI `--get <docno>` read the
SQLite map, giving C++ a read-only SQLite dependency. That was redundant:
`DocnoMap` already does `docno -> cp` in Python and C++ already fetches by `cp`,
so the C++ map read bought only "resolve a docno without Python" — not worth a
C++ SQLite dependency (a Bazel module or a `libsqlite3-dev` system install).
Keeping C++ strictly cp-only is simpler and **more** faithful to doc-6/doc-7:
the engine is cp-native; `docno` is confined to the Python boundary.

## Consequences

- **TASK-5.12 (A3):** cp-only C++ cutover; no SQLite dependency; `--get` takes a
  `cp`. (ACs amended accordingly.)
- **TASK-6.4:** the Python `cottontail-fetch` helper for human docno fetch.
- `docs/indexing.md` sections 5-6 updated to match.
