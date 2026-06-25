---
id: TASK-5
title: Searcher — per-intent ISJ search agent over Cottontail
status: To Do
assignee: []
created_date: '2026-06-17 12:47'
updated_date: '2026-06-25 21:23'
labels:
  - searcher
dependencies: []
references:
  - docs/searcher-agent-lessons-June-16-2026.md
  - backlog/docs/doc-3
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Umbrella task for the **Searcher**: the per-intent ISJ (Interactive Searching and
Judging) search agent for the TREC RAG 2026 entry. One interpretation ("intent") of
a question goes in; a ranked, graded passage list comes out. Each intent is searched
INDEPENDENTLY and its per-intent results are PERSISTED to a run output directory.
Fusion (RRF), Task-R formatting, and RAG are deferred / OUT OF SCOPE for now.

## cp-native re-baseline (2026-06-21, doc-6 supersedes doc-5)

The identity model is **cp-native** (doc-6): `cp` (the `:item` start address) is the
working identity on the wire, in the engine, and in the live agent loop. **docno is
optional and appears only at a boundary** (persistence + human/external fetch), via a
`cp <-> docno` **SQLite map** (TASK-6.3) — never on the hot path.

- **The hot path is sidecar-free.** cover_search returns `cp` per hit; the agent
  holds its judged set as `cp` and sends `exclude` as `cp` integers -> a direct `cp`
  post-filter; the agent reads a candidate by the `cp` it holds. No docno, no
  sidecar, no cache in the engine.
- **docno appears only at the boundary:** C2 rewrites `cp -> docno` (via the
  TASK-6.3 SQLite reader) when persisting an intent results + trace; a human/external
  `docno -> cp` lookup is Python (SQLite) then a C++ get-by-cp. `cp` is the working
  id; docno the persisted id.
- **docno is optional:** over a knowledge base with no docnos the Searcher runs on
  `cp` alone (no map). The TREC path has docids and produces the map.

(This re-baselines the earlier docno-on-the-wire spec; doc-5 is superseded.)

## Architecture (decided)

- The Cottontail HTTP server is a COLLECTION OF TOOLS (/tools/<name> + /describe);
  not aware of agents/profiles. cover_search is one tool. **It opens just the warren
  — no sidecar.**
- search_gcl stays a PURE GCL primitive. cover_search understands the word* family
  marker and returns a cover-biased summary; on the cp-native index it ranks plain
  `:item`, excludes by a direct `cp` post-filter, returns each hit `cp`, and computes
  total/unjudged_matches as a byproduct of the single ssr pass.
- The word*->feature stemming lives in the C++ tool layer (parity with the burrow Porter).
- The Python isj agent holds the judged set as `cp` and passes `exclude` as `cp`
  integers (the engine is stateless). The judge verdict tool is controller-side.
- GCL validity is the ENGINE truth (EngineError; the controller bounces it back).
- Judgement grade scale is 0-4 (UMBRELA-aligned).
- No fusion yet. Each intent RankedList (judged passages, keyed on `cp`) + a
  structured event trace are written to a run output directory; **C2 rewrites
  `cp -> docno` at write time** so the saved artifacts carry docno (portable), not cp.
- The user-facing CLI is a SINGLE flag-based entry (--question).

## Decomposition (subtasks)

Engine/server track (C++) -- cp-native; A3 (plumbing) first, then A1 -> A1b -> A2:
- A3 (5.12) the query-path cutover: open the warren (NO sidecar); get_document BY
  `cp`; search_text/search_gcl return `cp`; drop the :docno hopper; restore the
  non-cover query-path tests. A1/A2 build on it.
- A1 (5.1) cover_search: word* stemming + cover-biased summary; ranks plain `:item`;
  returns `cp` per hit. [REOPENED]
- A1b (5.11) cover_search returns a CoverResponse aggregate (results carry `cp`).
- A2 (5.2) enrichment: total/unjudged_matches as a byproduct of the single pass;
  exclusion as a direct `cp` post-filter (`exclude` = cp integers); atom_counts;
  window. [REOPENED]
- Retire the example agent (5.4): archive examples/agent/, superseded by isj/.

Python agent track (isj/) -- cp-keyed:
- B1 (5.5) engine contract types + SearchEngine Protocol + FakeEngine: `exclude` =
  cp; each Hit carries `cp`; the judged set is `cp`.
- B2 (5.6) Searcher agent + guardrailed loop controller; judged set keyed on `cp`.
  run(intent) -> SearcherResult { RankedList (keyed on cp) + structured trace }.
- C1 (5.7) HttpSearchEngine implementing the B1 Protocol against cover_search.
- C2 (5.8) run-output writer: persist intents + per-intent RankedList + trace;
  **rewrite `cp -> docno` via the TASK-6.3 SQLite reader at write time** so the saved
  files carry docno (portable); + errors.log.
- C3 (5.9) the CLI: Analyst -> per-intent Searcher over the live engine (C1) -> write
  the run output. Live gate against the cp-native burrow (built via the TASK-6.3
  index CLI; the dev burrow is Scrapheap/climbmix-100k-porter.burrow).

Docs track:
- Docs (5.10) update the run/usage docs for the cp-native Searcher.

Out of scope: fusion (RRF, dropped); Task-R TSV / RAG-JSONL; the dev-data eval
harness; real-model policy tuning.
<!-- SECTION:DESCRIPTION:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @claude
created: 2026-06-25 21:23
---
NAMING convention recorded in doc-7: docno (identity) and text (body) are the canonical internal terms; the indexer maps the raw JSON keys via docno_field/text_field (defaults docid/contents). Applies across all Searcher subtasks; cp stays the on-the-wire working id (doc-6).
---
<!-- COMMENTS:END -->
