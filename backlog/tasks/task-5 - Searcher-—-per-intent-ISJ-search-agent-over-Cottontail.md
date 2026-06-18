---
id: TASK-5
title: Searcher — per-intent ISJ search agent over Cottontail
status: To Do
assignee: []
created_date: '2026-06-17 12:47'
updated_date: '2026-06-18 14:19'
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
INDEPENDENTLY and its per-intent results are PERSISTED to a run output directory for later
analysis. Fusion (RRF), Task-R formatting, and RAG are deferred / OUT OF SCOPE for now.

The design was validated by live scouting against gpt-oss-120b, Qwen3.6-27B, and
gemma-4-31B. The scouting writeup (loop, prompt, tools, controller, evidence) is
docs/searcher-agent-lessons-June-16-2026.md (a snapshot; where it and these tasks
disagree, the tasks are current). Background: docs/agentic-isj-investigation-planner.md
(the over-built spec we are simplifying away from) and backlog/docs/doc-3 (per-intent
retrieval; its RRF-fusion proposal is DROPPED for now — we persist per-intent results
instead). A reusable probe lives at isj/scouting/.

## Architecture (decided)

- The Cottontail HTTP server is just a COLLECTION OF TOOLS (/tools/<name>, with
  /describe listing them). It is NOT aware of agents or "profiles". It is the CLIENT's job
  to choose which tools its agent gets and to supply them (from this server, a directory, or
  another server). cover_search is simply a new tool the server offers. (An earlier "tool
  registry + per-agent profiles" idea was rejected — the server must not model agents.)
- search_gcl stays a PURE GCL primitive (it does not learn agent conveniences). The
  ISJ agent gets a NEW, separate tool cover_search that understands the word* family
  marker, returns a cover-biased extractive summary, and (A2) carries breadth/novelty
  signals + exclusion + a window override.
- The word*->feature stemming translation lives in the C++ tool layer (parity with the
  burrow's own Porter), NOT in Python and NOT in GCL/search_gcl.
- The Python isj agent holds the judged set and passes it as exclude_docids (the engine
  is stateless); the judge verdict tool is controller-side, not a server endpoint. The
  agent's two LLM tools (search -> cover_search; judge) are defined client-side by B2.
- GCL validity (and any other engine failure) is the ENGINE's truth: there is no Python
  GCL validator; the engine raises EngineError and the agent controller handles it
  generally by feeding the message back to the model to self-correct.
- Judgement grade scale is 0-4 (UMBRELA-aligned).
- We do NOT fuse the per-intent lists yet. Each intent's results — a RankedList of judged
  passages PLUS a STRUCTURED EVENT TRACE (a list of timestamped TraceEvents with durations
  and type-specific fields, a research artifact) — are written to a run output directory;
  the trace is saved as intent-NN.trace.jsonl (JSON Lines). Deciding what to do with the
  results (fusion, Task-R, RAG) is deferred.
- The user-facing CLI is a SINGLE flag-based entry (no subcommands): it takes a question
  (--question) and runs the whole pipeline, writing the output directory.

## Server vs. client — where the HTTP work splits (so A and C1 are not redundant)

The cover_search HTTP/JSON contract has two ends:
- SERVER = the A tasks (C++): cottontail-jsonl-server's cover_search endpoint — JSON
  request parsing (spec_from) + response serialization (jsonl_json), added alongside the
  other tools and advertised by GET /describe. This is the PROVIDER; it does the actual
  searching (covers, stemming, summary, counts) and emits JSON. It only waits to be called
  (by curl, the CLI, or a client).
- CLIENT = C1 (Python): HttpSearchEngine — a class in isj_agent/engine/ that implements
  the B1 SearchEngine Protocol by POSTing to /tools/cover_search and parsing the JSON
  response into B1's SearchResponse type. It is the CONSUMER / transport glue: no search
  logic, no schema invention. (B1's SearchResponse is the Python MIRROR of A's server
  JSON; if they diverge, reconcile the mirror to the server — C1's live connectivity check
  and C3's full live run catch it.)

The Searcher agent (B2) is Python and only knows the SearchEngine Protocol (from B1) —
engine.search(...), engine.read(...). It is deliberately TRANSPORT-AGNOSTIC: it never
sees HTTP. So you can plug in either implementation:

```
B2 agent  ->  engine.search(...)              (the B1 Protocol)
                 |
                 |-- FakeEngine        -> canned responses              (tests; B1)
                 \-- HttpSearchEngine  -> POST /tools/cover_search -> C++ server  (live; C1 calls A)
```

The JSON shape shows up on both ends, but is defined ONCE and mirrored, not duplicated:
- A owns the server-side JSON contract (and advertises it via /describe).
- B1 defines the Python mirror of that contract (the SearchResponse / Hit / AtomCount
  pydantic types).
- C1 is just the glue: serialize the request -> HTTP -> deserialize the response JSON
  into the B1 types. No search logic, no schema invention — it conforms to A's contract.

So: A puts the JSON contract INTO the server; C1 writes the Python CLIENT that speaks that
contract and hands the agent typed objects. Without C1, the server (A) would have no
in-process Python caller for the agent — only curl/CLI could reach it. Without A, C1 would
have nothing to call. (That is also why B2 needs neither: it tests against FakeEngine,
which satisfies the same Protocol with zero HTTP — the whole point of the B1 Protocol seam.)

## Decomposition (subtasks)

Engine/server track (C++); dependency A1 -> A2:
- A1 (5.1) New cover_search tool (added as a /tools/cover_search endpoint alongside the
  existing tools + a /describe entry): per-atom word* stemming (+ honored in phrases) and
  a cover-biased extractive summary (default window 75 tokens). Leaves search_gcl pure.
- A2 (5.2) cover_search enrichment: total_matches + unjudged_matches (document counts),
  atom_counts (occurrences, no stream), exclude_docids (container-carve), and a window
  request override for A1's summary.
- Retire the example agent (5.4): archive examples/agent/, superseded by isj/.
(Note: an earlier A0 "tool registry + per-agent profiles" task was rejected and archived —
the server is just a bag of tools; clients choose what their agent uses.)

Python agent track (isj/), mock-tested, independent of the engine track; then converge:
- B1 (5.5) Searcher engine contract types + SearchEngine Protocol (+ EngineError channel)
  + scripted FakeEngine (SearchResponse/Hit/AtomCount + Judgement grade 0-4; RankedList
  deferred to B2).
- B2 (5.6) Searcher agent + guardrailed loop controller (search/judge[batch], one tool
  call per turn, judge-before-search guard, engine-delegated error bounce, controller-owned
  termination incl. a max-turns cap). run(intent) -> SearcherResult { RankedList (all judged,
  grade desc then score desc) + a structured event trace (list[TraceEvent]) }. Tested vs a
  stub LLM + FakeEngine.
- C1 (5.7) HttpSearchEngine (httpx) implementing the B1 Protocol against cover_search; the
  [cottontail_http_json_server] config + build_search_engine; MockTransport unit tests; and
  a go-ahead-gated live CONNECTIVITY check (cover_search round-trip + EngineError). C1 ships
  NO CLI entry. (Targets the server A1/A2 modify.)
- C2 (5.8) Run-output writer: persist a run to an output directory — intents.json (the
  Intents) + per SUCCESSFUL intent intent-NN.json (the RankedList) + intent-NN.trace.jsonl
  (the structured event trace, JSON Lines), plus an OPTIONAL errors.log written ONLY if an
  intent (or the run) failed — its ABSENCE means every intent completed successfully, its
  PRESENCE means something went wrong and it holds the error messages. Pure; no fusion.
- C3 (5.9) The CLI: a SINGLE flag-based entry
  python -m isj_agent.cli --question <q> --out <dir> [--overwrite] [--verbose] (NO
  subcommands) that runs the whole pipeline — Analyst -> Intents -> per-intent Searcher over
  the live engine (C1) -> capture each SearcherResult (RankedList + events) -> write the run
  output directory (C2). A per-intent failure is caught as a RunError and the run CONTINUES
  (one bad intent does not abort the rest); failures land in errors.log and the CLI exits
  non-zero. --verbose renders the events live. It replaces the Analyst-only demo
  and IS the full real-LLM live integration gate (gpt-oss-120b +
  Scrapheap/climbmix-1000-utf8-porter.burrow). No fusion.

Docs track (after archival + CLI land):
- Docs (5.10) Update the run/usage docs for the isj Searcher once 5.4 (archival) and 5.9
  (CLI) land: docs/running-the-search-stack.md (the single source) gains the isj path end to
  end + the run-output layout; isj/README.md drops the Analyst-only demo framing for the full
  pipeline; CLAUDE.md and any other docs note examples/agent/ as ARCHIVED and point to isj/.
  Documentation only. Depends on 5.4 + 5.9.

Out of scope of this umbrella: fusion (RRF, dropped for now); Task-R TSV / RAG-JSONL output
+ Writer/Validator; the dev-data eval harness; real-model policy tuning.
<!-- SECTION:DESCRIPTION:END -->
