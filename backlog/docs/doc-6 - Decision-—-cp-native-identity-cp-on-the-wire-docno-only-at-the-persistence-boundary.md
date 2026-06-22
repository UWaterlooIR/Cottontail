---
id: doc-6
title: >-
  Decision — cp-native identity: cp on the wire, docno only at the persistence
  boundary
type: specification
created_date: '2026-06-21 18:23'
updated_date: '2026-06-22 00:43'
---
**Status:** accepted (2026-06-21). **Supersedes doc-5.**

Related: doc-4 (indexing model), docs/indexing.md, TASK-5 (Searcher), TASK-6 (indexing).

## Context — why this supersedes doc-5

doc-5 put **docno on the wire** (the agent speaks docno; the engine resolves
docno<->cp per request via a sidecar + cache). Planning the engine cutover
(TASK-5.12 / A3) surfaced the concrete cost: under the multi-threaded server that
forces a **per-thread / per-clone sidecar** with the reverse map and cache resident
on the hot path (~8 GB x N at 500M docs), plus a docno->cp resolution on every
request. That complexity is entirely a consequence of docno-on-the-wire.

The ISJ Searcher is also not TREC-only: it can run over a plain knowledge base
whose items have **no docno at all**. Requiring docno everywhere locks that out.

## Decision — cp-native; docno only at the boundary

**`cp` (the `:item` start address Cottontail assigns at insert) is the working
identity** — on the wire, in the engine, and in the live agent loop. **docno is
optional enrichment that appears only at the boundary.**

- **The hot interactive path is sidecar-free.** cover_search returns `cp` per hit;
  exclusion is the agent's `cp` set -> a direct integer post-filter (no docno->cp
  resolution, no cache); the agent reads a candidate by the `cp` it already holds;
  the judged set is keyed on `cp`.
- **docno appears at exactly two boundary points, both off the hot path:**
  - **forward `cp -> docno`** when persisting an intent's results + trace to disk
    (the run-output writer rewrites the bounded set of `cp`s to docnos), and
  - **reverse `docno -> cp`** for a human at the CLI / another agent or task that
    holds only a docno and wants to fetch or act on the document.
  Both are occasional, latency-tolerant, served by **one shared store** — never
  per-request, never per-clone.
- **`cp` is the working id; docno is the persisted id.** The rewrite at the disk
  boundary is the discipline for `cp`'s burrow-instance-locality: a raw `cp` is
  never persisted; it is mapped to the portable docno on the way out.
- **docno is optional.** A corpus with no docnos yields a cp-only burrow and no
  map; the JSONL / TREC path always has docids and always produces the map.

## The map — SQLite, built at index time, off the hot path

The `cp <-> docno` map is a **SQLite store** (replacing the custom binary sidecar of
TASK-6.1):

- **Build (two steps, one front door).** A Python index CLI orchestrates:
  (1) the C++ `cottontail-jsonl-index` indexes the JSONL into a plain cp-native
  burrow — `add_document(contents) -> cp` — and dumps a flat `docno<TAB>cp` file;
  (2) the CLI loads the flat file into SQLite `(cp INTEGER PRIMARY KEY,
  docno TEXT UNIQUE)` and deletes the flat file. The `UNIQUE` index **is** the
  docno-uniqueness check.
- **Read (boundary only).** Two read-only readers; the multi-threaded query path
  never opens the map. Python (C2) does the run-output cp->docno rewrite (results +
  trace); the C++ CLI `cottontail-jsonl-query --get <docno>` does docno->cp then
  translate. C++ takes a read-only SQLite dependency used solely by this boundary
  CLI `--get`. The **server stays docno-free and map-free** (cp-only — cover_search,
  exclusion, and get_document-by-cp); fetch-by-docno is the CLI's job only.

## Consequences / scope

- **Supersedes doc-5** and **revises docs/indexing.md sections 3-6** (cp-native; the
  sidecar becomes the SQLite boundary store).
- **Re-specs TASK-6.1** (cp-returning `add_document` + flat-file dump; delete the
  custom `DocnoContentsSidecar`), adds a **Python index-CLI** task, and touches
  **TASK-6.2**.
- **Re-baselines TASK-5** to cp-native: cover_search / get-by-cp / exclusion on
  `cp` (A1/A2/A3); B1/B2 keyed on `cp`; C2 does the cp->docno rewrite at
  persistence via SQLite.
- Detailed mechanics live in docs/indexing.md; this records the decision.
