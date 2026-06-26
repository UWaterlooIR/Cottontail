---
id: doc-7
title: >-
  Decision — canonical naming: docno (identity), text (body),
  docno_field/text_field config
type: other
created_date: '2026-06-25 21:19'
updated_date: '2026-06-25 21:19'
---
Status: accepted (2026-06-25). Builds on doc-4 / doc-6 (cp-native identity).

## Decision

Use one canonical vocabulary for a document's parts everywhere **after the
indexer reads the JSON**:

- **docno** — the document's external string id (TREC "document number"). The
  working id on the hot path is `cp` (doc-6); `docno` is the persisted / boundary
  id. Use `docno` (never `docid`) in code, artifacts, tests, and specs downstream
  of the JSON read.
- **text** — the document body. Use `text` (never `contents`) downstream of the
  JSON read.

The **indexer is the only component that knows the raw JSON field names**, given
as configuration so the indexer works with any JSON:

- `docno_field` (CLI `--docno-field`, default `"docid"`) — which JSON key holds
  the docno.
- `text_field` (CLI `--text-field`, default `"contents"`) — which JSON key holds
  the text.

The defaults (`"docid"`, `"contents"`) are the keys our ClimbMix JSONL uses, so
`docid` survives ONLY as a default JSON key string — not as an internal term.

## Artifacts

- Flat dump: `<burrow>/docno-cp.tsv` (`docno<TAB>cp`).
- SQLite map: `<burrow>/docno-cp.sqlite`, table
  `docno_map(cp INTEGER PRIMARY KEY, docno TEXT UNIQUE)`.

## Scope / status

- **Applied** — the index path (TASK-6.1/6.2/6.3): `IndexOptions.docno_field` /
  `text_field`, `--docno-field` / `--text-field`, the flat dump, the Python front
  door (`cottontail-index`) + reader (`isj_agent.docno_map`), and
  `docs/indexing.md` / `docs/cottontail-jsonl-cli-spec.md`.
- **Pending** — the query / response path still emits `docid` (`Hit.docid`, the
  `"docid"` keys in `apps/jsonl_json.cc` search/get responses + `describe`).
  **TASK-5.12 / A3** rewrites that path cp-native and MUST adopt this naming:
  results carry `cp`; any persisted id is `docno`; the body is `text`.

## Why

`docid` / `contents` were the input-side (JSON) names leaking into internal
artifacts, producing a split (`docid-cp.tsv` next to `docno-cp.sqlite`). One
canonical vocabulary downstream of the indexer; the raw JSON names stay
configurable and local to the indexer.
