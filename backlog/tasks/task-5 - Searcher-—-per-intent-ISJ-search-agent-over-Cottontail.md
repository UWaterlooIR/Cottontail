---
id: TASK-5
title: Searcher — per-intent ISJ search agent over Cottontail
status: To Do
assignee: []
created_date: '2026-06-17 12:47'
updated_date: '2026-06-21 04:44'
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
Judging) search agent for the TREC RAG 2026 entry. One interpretation ("intent")
of a question goes in; a ranked, graded passage list comes out. Each intent is
searched INDEPENDENTLY and its per-intent results are PERSISTED to a run output
directory for later analysis. Fusion (RRF), Task-R formatting, and RAG are
deferred / OUT OF SCOPE for now.

## Re-baselined for the new-style index (2026-06-21)

This umbrella was first specced against the OLD burrow, where each document
carried a `:docno` annotation. The index has since moved to the **new-style**
model (TASK-6, doc-4): the burrow stores **contents + one `:item` annotation + a
`cp <-> docno` sidecar**, with **no `:docno`** and no docid tokens. The identity /
wire decision is settled in **doc-5**:

- **The agent speaks `docno`** (the JSON docid) end to end -- every result carries
  a docno; the agent reads (`get_document`) and excludes (`exclude_docids`) by
  docno; it persists and cites docnos. Unchanged from the original design.
- **`cp` (the `:item` start address) is engine-internal only.** The sidecar
  translates `docno -> cp` inbound (exclusion, get_document) and `cp -> docno`
  outbound (the emitted page).
- **Invariant (doc-5): internal results, ranking, the exclude post-filter, and the
  match counts are keyed on `cp` only; docno is materialized only at the boundary,
  for the returned `top_k`.** `cp` never crosses the wire or reaches persisted
  output.

What that means for the tracks:
- **A (engine) is REDONE** on the cp/sidecar model -- A1/A1b/A2 shipped against
  `:docno` and are superseded; the query-path tests they relied on are currently
  quarantined (TASK-6.2) and return as new-model tests.
- **B / C (Python) stay docno-keyed** and need only light updates -- the contract
  identity does not change.
- The **Analyst (TASK-1-4)** is unaffected (question -> Intents; it never touches
  the index).
- Dev/test target for the redo and the live gates: the new-style
  **Scrapheap/climbmix-100k-porter.burrow**.

Authoritative for the retrieval model: docs/indexing.md sections 3-6 + doc-4 +
doc-5. Background: the design was validated by live scouting against gpt-oss-120b,
Qwen3.6-27B, and gemma-4-31B; the scouting writeup is
docs/searcher-agent-lessons-June-16-2026.md (a snapshot; where it and these tasks
disagree, the tasks are current). docs/agentic-isj-investigation-planner.md is the
over-built spec we are simplifying away from, and backlog/docs/doc-3 is per-intent
retrieval (its RRF-fusion proposal is DROPPED -- we persist per-intent results
instead). A reusable probe lives at isj/scouting/.

## Architecture (decided)

- The Cottontail HTTP server is just a COLLECTION OF TOOLS (/tools/<name>, with
  /describe listing them). It is NOT aware of agents or "profiles"; the CLIENT
  chooses which tools its agent gets. When the server opens a burrow it also opens
  that burrow's **sidecar** (the cp<->docno map); the agent never sees cp.
- search_gcl stays a PURE GCL primitive. The ISJ agent gets a separate tool
  **cover_search** that understands the word* family marker and returns a
  cover-biased extractive summary. On the new index it ranks within **plain
  `:item`** (no docno carve), excludes via an internal **`cp` post-filter**
  (resolving the supplied exclude docnos -> cp through the sidecar, cached), emits
  each hit's **docno** via `cp -> docno`, and computes total/unjudged_matches as a
  **byproduct of the single ranking pass** (doc-5).
- The word*->feature stemming translation lives in the C++ tool layer (parity with
  the burrow's own Porter), NOT in Python and NOT in GCL/search_gcl.
- The Python isj agent holds the judged set as **docnos** and passes them as
  exclude_docids (the engine is stateless; it resolves docno->cp internally,
  cached). The judge verdict tool is controller-side, not a server endpoint.
- GCL validity (and any other engine failure) is the ENGINE's truth: there is no
  Python GCL validator; the engine raises EngineError and the controller bounces
  the message back to the model to self-correct.
- Judgement grade scale is 0-4 (UMBRELA-aligned).
- We do NOT fuse the per-intent lists yet. Each intent's results -- a RankedList of
  judged passages (keyed on **docno**) PLUS a structured event trace -- are written
  to a run output directory; fusion / Task-R / RAG are deferred.
- The user-facing CLI is a SINGLE flag-based entry (--question) that runs the whole
  pipeline and writes the output directory.

## Server vs. client -- where the HTTP work splits

- SERVER = the A tasks (C++): cottontail-jsonl-server's cover_search endpoint
  (request parse + response serialize), advertised by GET /describe. The PROVIDER:
  it opens the sidecar and does the actual searching (covers, stemming, summary,
  cp post-filter, counts, cp->docno emission) and emits docno-keyed JSON.
- CLIENT = C1 (Python): HttpSearchEngine -- implements the B1 SearchEngine Protocol
  by POSTing to /tools/cover_search and parsing the JSON into B1's types. Transport
  glue only; no search logic, no schema invention. The JSON shape is defined ONCE
  on the server (A) and MIRRORED in Python (B1), not duplicated; C1's live check
  and C3's full run catch any drift. The Searcher (B2) is transport-agnostic -- it
  only knows the Protocol -- so FakeEngine (tests) and HttpSearchEngine (live)
  both satisfy it.

## Decomposition (subtasks)

Engine/server track (C++) -- REDO on the cp/sidecar model; A3 (plumbing) first, then A1 -> A1b -> A2:
- A3 (5.12) cp/sidecar query-path plumbing: the shared open-burrow-plus-sidecar
  helper + a docno->cp cache; get_document reframed (docno -> cp -> translate); the
  search_text/search_gcl docid emission (cp -> docno); the cottontail-jsonl-query
  CLI + server /tools/* opened on the sidecar; and the quarantined (non-cover)
  query-path tests restored as new-model tests. A1/A2 build on its plumbing.
- A1 (5.1) cover_search: word* stemming + cover-biased summary; carry the sidecar,
  rank plain `:item`, emit docno via cp->docno. [REOPENED -- shipped on :docno.]
- A1b (5.11) cover_search returns a CoverResponse aggregate. [shape unchanged;
  field semantics per doc-5.]
- A2 (5.2) enrichment: total/unjudged_matches as a byproduct of the single pass;
  exclusion as a `cp` post-filter (resolve exclude docnos -> cp, cached);
  atom_counts; window override. [REOPENED -- shipped on :docno.]
- Retire the example agent (5.4): archive examples/agent/, superseded by isj/.

Python agent track (isj/) -- docno-keyed, LIGHT re-spec; mock-tested, then converge:
- B1 (5.5) engine contract types + SearchEngine Protocol (+ EngineError) + scripted
  FakeEngine. (docno contract intact; note exclusion/emission are sidecar-backed in
  the engine, not on the wire.)
- B2 (5.6) Searcher agent + guardrailed loop controller; judged set keyed on docno.
  run(intent) -> SearcherResult { RankedList + structured event trace }.
- C1 (5.7) HttpSearchEngine implementing the B1 Protocol against cover_search;
  config + build_search_engine; MockTransport tests + a gated live connectivity
  check.
- C2 (5.8) run-output writer: intents.json + per-intent RankedList + trace.jsonl
  (+ errors.log iff a failure); persists **docno** (portable), never cp. Pure; no
  fusion.
- C3 (5.9) the CLI: a SINGLE flag-based entry that runs Analyst -> per-intent
  Searcher over the live engine (C1) -> write the run output. The full real-LLM live
  gate, run against the new-style Scrapheap/climbmix-100k-porter.burrow.

Docs track:
- Docs (5.10) update the run/usage docs once 5.4 + 5.9 land (the new-style stack
  end to end + run-output layout; example agent noted as archived).

Out of scope of this umbrella: fusion (RRF, dropped); Task-R TSV / RAG-JSONL output
+ Writer/Validator; the dev-data eval harness; real-model policy tuning.
<!-- SECTION:DESCRIPTION:END -->
