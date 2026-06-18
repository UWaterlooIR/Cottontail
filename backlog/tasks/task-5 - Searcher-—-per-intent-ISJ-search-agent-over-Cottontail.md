---
id: TASK-5
title: Searcher — per-intent ISJ search agent over Cottontail
status: To Do
assignee: []
created_date: '2026-06-17 12:47'
updated_date: '2026-06-18 02:37'
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
a question goes in; a ranked, graded passage list comes out. RRF later fuses the
per-intent lists into the question's final ranking.

The design was validated by live scouting against gpt-oss-120b, Qwen3.6-27B, and
gemma-4-31B. The scouting writeup (loop, prompt, tools, controller, evidence) is
docs/searcher-agent-lessons-June-16-2026.md (a snapshot; where it and these tasks
disagree, the tasks are current). Background: docs/agentic-isj-investigation-planner.md
(the over-built spec we are simplifying away from) and backlog/docs/doc-3 (per-intent
retrieval + RRF fusion). A reusable probe lives at isj/scouting/.

## Architecture (decided)

- The CLI/HTTP server is a PLATFORM of named tools; an agent = a prompt + a chosen
  PROFILE (subset) of tools. Discovery is per-profile (A0).
- `search_gcl` stays a PURE GCL primitive (it does not learn agent conveniences). The
  ISJ agent gets a NEW, separate tool `cover_search` (in the `isj` profile) that
  understands the `word*` family marker, returns a cover-biased extractive `summary`,
  and (A2) carries breadth/novelty signals + exclusion + a window override.
- The word*->feature stemming translation lives in the C++ tool layer (parity with the
  burrow's own Porter), NOT in Python and NOT in GCL/search_gcl.
- The Python isj agent holds the judged set and passes it as exclude_docids (the engine
  is stateless); the `judge` verdict tool is controller-side, not a server endpoint.
- Judgement grade scale is 0-4 (UMBRELA-aligned).

## Server vs. client — where the HTTP work splits (so A and C1 are not redundant)

The cover_search HTTP/JSON contract has two ends:
- SERVER = the A tasks (C++): cottontail-jsonl-server's `cover_search` endpoint — JSON
  request parsing (spec_from) + response serialization (jsonl_json), registered in the
  isj profile and advertised by GET /describe. This is the PROVIDER; it does the actual
  searching (covers, stemming, summary, counts) and emits JSON. It only waits to be
  called (by curl, the CLI, or a client).
- CLIENT = C1 (Python): `HttpSearchEngine` — a class in isj_agent/engine/ that implements
  the B1 SearchEngine Protocol by POSTing to /tools/cover_search and parsing the JSON
  response into B1's SearchResponse type. It is the CONSUMER / transport glue: no search
  logic, no schema invention.

The agent (B2) only knows the in-process SearchEngine Protocol (B1) and is
transport-agnostic:
  B2 -> engine.search(...) -> { FakeEngine (canned; tests; B1) |
                                HttpSearchEngine (HTTP -> the C++ server; live; C1) }

The JSON shape is defined ONCE and mirrored, not duplicated: A owns the server-side
contract (advertised via /describe); B1 defines the Python pydantic mirror
(SearchResponse / Hit / AtomCount); C1 is only the glue mapping HTTP JSON <-> those
types. Without C1 the server has no in-process Python caller for the agent (only
curl/CLI); without A the client has nothing to call; B2 needs neither, because
FakeEngine satisfies the same Protocol with no HTTP.

## Decomposition (subtasks)

Engine/server track (C++); dependency A0 -> A1 -> A2:
- A0 (5.3) Tool registry + per-agent profiles + /describe filtering; migrate existing
  tools into a `gcl` profile, establish the `isj` profile.
- A1 (5.1) New `cover_search` tool: per-atom `word*` stemming (+ honored in phrases) and
  a cover-biased extractive `summary` (default window 75 tokens). Leaves search_gcl pure.
- A2 (5.2) `cover_search` enrichment: total_matches + unjudged_matches (document counts),
  atom_counts (occurrences, no stream), exclude_docids (container-carve), and a `window`
  request override for A1's summary.
- Retire the example agent (5.4): archive examples/agent/, superseded by isj/.

Python agent track (isj/), mock-tested, independent of the engine track; then converge:
- B1 (5.5) Searcher engine contract types + SearchEngine Protocol + scripted FakeEngine
  (SearchResponse/Hit/AtomCount + Judgement grade 0-4; RankedList deferred to B2).
- B2 Searcher agent + guardrailed loop controller (search/judge[batch]/read, one tool
  call per turn, GCL-validity + judge-before-search guards, controller-owned
  termination), tested against the mock with a stub LLM. [to write, dep B1]
- C1 HTTP engine client (HttpSearchEngine) implementing the Protocol against cover_search
  (isj profile) + live end-to-end against a real burrow. [to write, dep A0/A1/A2/B1/B2]
- C2 RRF fusion (pure function; doc-3, k=60, single-intent no-op). [to write, dep B1]
- C3 Orchestrator wiring (Analyst -> Intents -> Searcher-per-intent -> RRF -> final
  ranked list). [to write, dep B2/C2]

Out of scope of this umbrella (downstream): Task-R TSV / RAG-JSONL output + Writer/
Validator, the dev-data eval harness, real-model policy tuning.
<!-- SECTION:DESCRIPTION:END -->
