---
name: naming-docno-text
description: Canonical naming — docno (identity) + text (body) downstream of the indexer; docid/contents are only JSON field names (config). Decision doc-7.
metadata:
  type: project
---

Canonical vocabulary for a document's parts (decision **doc-7**, 2026-06-25):

- **docno** = the external string id; **text** = the body. Use these everywhere in
  code / artifacts / tests / specs **downstream of the indexer**; never
  `docid`/`contents`.
- `docid`/`contents` survive ONLY as default JSON field names. The indexer maps raw
  JSON keys via `docno_field` (`--docno-field`, default `"docid"`) and `text_field`
  (`--text-field`, default `"contents"`) — so it works with any JSON.
- Artifacts: flat dump `<burrow>/docno-cp.tsv` (`docno<TAB>cp`); SQLite map
  `<burrow>/docno-cp.sqlite`, table `docno_map(cp INTEGER PRIMARY KEY, docno TEXT UNIQUE)`.

**Why:** input-side JSON names were leaking into internal artifacts (a `docid-cp.tsv`
next to `docno-cp.sqlite` split). One canonical vocabulary; the raw JSON names stay
local to the indexer.

**Applied:** the index path (TASK-6.1/6.2/6.3) + `docs/indexing.md` +
`docs/cottontail-jsonl-cli-spec.md`. **Still pending:** the query/response path still
emits `docid` (`Hit.docid`, the `"docid"` keys in `apps/jsonl_json.cc`) — **A3 /
TASK-5.12** must rename per doc-7 (results carry `cp`; persisted id = `docno`).
Builds on cp-native identity (doc-6). See [[project-cottontail-overview]] and
[[pr-jsonl-cli]].
