---
id: TASK-5.9
title: >-
  C3 — isj: CLI orchestrator (question -> Analyst -> per-intent Searcher ->
  write run output)
status: To Do
assignee: []
created_date: '2026-06-18 04:41'
updated_date: '2026-06-18 13:30'
labels:
  - python
  - isj
  - searcher
  - integration
dependencies:
  - TASK-5.6
  - TASK-5.7
  - TASK-5.8
references:
  - isj/isj_agent/orchestrator.py
  - isj/isj_agent/cli.py
  - isj/isj_agent/protocol/intents.py
  - isj/README.md
  - Scrapheap/climbmix-1000-utf8-porter.burrow
parent_task_id: TASK-5
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

Python, in the `isj/` uv project (package `isj_agent`). Fleshes out
`isj_agent/orchestrator.py` (currently a stub) and REWRITES `isj_agent/cli.py`. DEPENDS ON
B2 (TASK-5.6: the Searcher, which returns a SearcherResult{ranked_list, events}), C1
(TASK-5.7: HttpSearchEngine + build_search_engine config), C2 (TASK-5.8: the run-output
writer). NO C++.

## Context (for an agent new to this project)

The end-to-end runner AND the full real-LLM live integration gate: ONE question in, a run
output DIRECTORY out. Pipeline:
  Analyst.analyze(question) -> Intents (question + ordered interpretations)
  for each interpretation (in order): Searcher.run(interp) over the LIVE engine
      (HttpSearchEngine, C1) -> SearcherResult { ranked_list: RankedList,
      events: list[TraceEvent] }
  write the run directory via C2's write_run (intents.json + intent-NN.json +
      intent-NN.trace.jsonl)
There is NO fusion (RRF/Task-R/RAG dropped/out of scope). One question per invocation.

Endpoints come from config.toml (see C1): [llm.default] -> the vLLM model (build_client);
[cottontail_http_json_server] -> the cottontail-jsonl-server (build_search_engine ->
HttpSearchEngine). The CLI takes ALL inputs as FLAGS (no subcommands), including the
question via --question, consistent with --out.

The trace is produced BY THE SEARCHER (B2): Searcher.run returns SearcherResult.events, a
list[TraceEvent] (the structured, timestamped event log — a research artifact). C3 does NOT
build its own tracer; it just captures sr.events per intent, hands them to C2 (which writes
intent-NN.trace.jsonl), and on --verbose renders them to the console.

## Required behavior (the contract)

1. Orchestrator (isj_agent/orchestrator.py): run_question(question: str) -> (Intents,
   list[IntentResult]). intents = self.analyst.analyze(question); for each interpretation in
   order, sr = self.searcher.run(interpretation); collect IntentResult{ranked_list:
   sr.ranked_list, events: sr.events}; return (intents, results). The orchestrator does NOT
   write files (C2) and does NOT fuse.

2. CLI — a SINGLE entry, NO subcommands; ALL inputs are flags:
     python -m isj_agent.cli --question <q> --out <dir> [--overwrite] [--verbose]
   It reads config.toml; builds the LLM client (build_client) and HttpSearchEngine
   (build_search_engine); constructs Analyst + Searcher + Orchestrator; runs
   run_question(question); calls C2 write_run(out_dir, intents, results, overwrite=...); and
   prints a short summary (out_dir, #interpretations, per-intent entry counts). This REPLACES
   the current Analyst-only demo in cli.py (rewrite main(); the Analyst is now an internal
   pipeline step). One question per invocation.

3. Trace: the per-intent trace is B2's SearcherResult.events (a list[TraceEvent] — the
   timestamped, type-tagged event log). It is ALWAYS captured per intent and saved as
   intent-NN.trace.jsonl (via C2, one event per line). --verbose additionally RENDERS the
   events to the console during the run (a human-readable live transcript). C3 builds no
   tracer of its own; the events come from the Searcher.

4. The CLI run IS the full real-LLM live integration GATE. With the C++ stack built (A0/A1/A2
   cover_search + isj profile), cottontail-jsonl-server running over
   Scrapheap/climbmix-1000-utf8-porter.burrow on a loopback port, and vLLM gpt-oss-120b up,
   running the CLI on a question exercises the WHOLE pipeline live: cover_search with word*,
   exclude_docids accumulation, an EngineError bounce, the controller loop, and a populated
   output directory (with the per-intent event traces). External services -> obtain explicit
   operator go-ahead before running.

## Non-goals

- No subcommands (the CLI is a single flag-based entry).
- No fusion/RRF, no Task-R TSV / RAG-JSONL output, no Writer/Validator.
- No multi-question batch — one question per run.
- No C++ or server changes; no new engine tools. No trace GENERATION (the Searcher/B2 emits
  the events; C3 only captures, renders, and routes them to C2).
<!-- SECTION:DESCRIPTION:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Python in isj/. Depends on B2, C1, C2. Adapt as needed.

1. uv sync --project isj. Read isj_agent/orchestrator.py (stub), cli.py (the current Analyst
   demo + config loading), C1's build_search_engine + HttpSearchEngine, B2's Searcher.run
   (returns SearcherResult{ranked_list, events}) + the TraceEvent type, and C2's write_run.
2. Orchestrator.run_question(question): analyst.analyze -> Intents; per interpretation,
   sr = searcher.run(interp); collect IntentResult{ranked_list=sr.ranked_list,
   events=sr.events}; return (intents, results). No tracer of its own — use sr.events.
3. cli.py: REWRITE main() to a single flag-based argparse entry — --question (required),
   --out (required), --overwrite, --verbose. NO subparsers, NO positional args. Read
   config.toml; build_client([llm.default]); build_search_engine([cottontail_http_json_server]);
   construct Analyst + Searcher + Orchestrator; run_question; write_run; print the summary;
   if --verbose, render each intent's events to the console (human-readable). Remove the old
   Analyst-only demo behavior.
4. isj/tests/test_orchestrator.py (no network): drive run_question with a STUB Analyst
   (fixed Intents) + a STUB/Fake Searcher (returns fixed SearcherResults with ranked_list +
   events, or B2 over the B1 FakeEngine + a stub LLM); assert one IntentResult per
   interpretation, each carrying ranked_list + events; write_run to tmp_path and assert the
   directory contents (intents.json + intent-NN.json + intent-NN.trace.jsonl). No live network.
5. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: the CLI
   (--question/--out/--overwrite/--verbose, no subcommands), the output directory (incl. the
   per-intent .trace.jsonl event logs), and the live-run prerequisites (server + vLLM up,
   operator go-ahead).
6. LIVE gate (after A0/A1/A2/B2/C1/C2 exist + go-ahead): config.toml -> vLLM + the running
   server over Scrapheap/climbmix-1000-utf8-porter.burrow; run
   `python -m isj_agent.cli --question <q> --out runs/<name> --verbose`; confirm a populated
   output directory with sensible per-intent RankedLists + event traces; debug any contract
   mismatch the trace reveals; capture notes.
<!-- SECTION:PLAN:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 orchestrator.run_question(question) -> (Intents, list[IntentResult]): Analyst.analyze -> Intents, then for each interpretation in order sr = Searcher.run(interpretation); collect IntentResult{ranked_list: sr.ranked_list, events: sr.events}; it does not write files and does not fuse.
- [ ] #2 The CLI is a SINGLE entry with NO subcommands and all inputs as flags: python -m isj_agent.cli --question <q> --out <dir> [--overwrite] [--verbose]; it reads config.toml, builds the LLM client (build_client) and HttpSearchEngine (build_search_engine), runs run_question, writes the output directory via C2 write_run, and prints a summary; it replaces the current Analyst-only demo (Analyst becomes an internal step).
- [ ] #3 The per-intent structured event trace is B2's SearcherResult.events (a list of TraceEvent); it is always captured per intent and saved as intent-NN.trace.jsonl via C2 (one event per line); --verbose additionally renders the events to the console live. C3 builds no tracer of its own.
- [ ] #4 One question per run; one output directory per run; no fusion/RRF.
- [ ] #5 Automated tests drive run_question with a stub Analyst + a stub/Fake Searcher (no network), assert one IntentResult per interpretation each carrying ranked_list + events, and assert the written output directory contents (intents.json + per-intent json + trace.jsonl).
- [ ] #6 The CLI run is the full real-LLM live integration gate: with the C++ stack built, cottontail-jsonl-server over Scrapheap/climbmix-1000-utf8-porter.burrow, and vLLM gpt-oss-120b up, running it on a question completes the whole pipeline (cover_search with word*, exclude_docids accumulation, an EngineError bounce) and produces a populated output directory with per-intent event traces; external services require operator go-ahead; the transcript/notes are captured.
- [ ] #7 uv run --directory isj pytest tests/ exits 0; no automated test contacts a network or a real model.
- [ ] #8 isj/README.md documents the CLI (--question/--out/--overwrite/--verbose, no subcommands), the run output directory (incl. the per-intent .trace.jsonl event logs), and the live-run prerequisites/go-ahead.
<!-- AC:END -->
