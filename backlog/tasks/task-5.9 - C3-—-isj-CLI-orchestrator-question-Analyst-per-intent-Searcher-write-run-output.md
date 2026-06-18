---
id: TASK-5.9
title: >-
  C3 — isj: CLI orchestrator (question -> Analyst -> per-intent Searcher ->
  write run output)
status: To Do
assignee: []
created_date: '2026-06-18 04:41'
updated_date: '2026-06-18 05:01'
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
B2 (TASK-5.6: the Searcher), C1 (TASK-5.7: HttpSearchEngine + build_search_engine config),
C2 (TASK-5.8: the run-output writer). NO C++.

## Context (for an agent new to this project)

This is the end-to-end runner AND the full real-LLM live integration gate: ONE question in,
a run output DIRECTORY out. Pipeline:
  Analyst.analyze(question) -> Intents (question + ordered interpretations)
  for each interpretation (in order): Searcher.run(interp) over the LIVE engine
      (HttpSearchEngine, C1), capturing a verbose loop trace -> (RankedList, trace)
  write the run directory via C2's write_run (intents.json + intent-NN.json + intent-NN.trace.txt)
There is NO fusion (RRF/Task-R/RAG dropped/out of scope). One question per invocation.

Endpoints come from config.toml (see C1): [llm.default] -> the vLLM model (build_client);
[cottontail_http_json_server] -> the cottontail-jsonl-server (build_search_engine ->
HttpSearchEngine). The CLI takes ALL inputs as FLAGS (no subcommands, no positional args),
including the question via --question, consistent with --out.

## Required behavior (the contract)

1. Orchestrator (isj_agent/orchestrator.py): run_question(question: str) -> (Intents,
   list[IntentResult]). intents = self.analyst.analyze(question); for each interpretation in
   order, run the Searcher capturing its verbose trace, collect IntentResult{ranked_list,
   trace}; return (intents, results). The orchestrator does NOT write files (C2) and does
   NOT fuse.

2. CLI — a SINGLE entry, NO subcommands; ALL inputs are flags:
     python -m isj_agent.cli --question <q> --out <dir> [--overwrite] [--verbose]
   It reads config.toml; builds the LLM client (build_client) and HttpSearchEngine
   (build_search_engine); constructs Analyst + Searcher + Orchestrator; runs
   run_question(question); calls C2 write_run(out_dir, intents, results, overwrite=...);
   and prints a short summary (out_dir, #interpretations, per-intent entry counts). This
   REPLACES the current Analyst-only demo in cli.py (rewrite main(); the Analyst is now an
   internal pipeline step, still exercised by its own tests). One question per invocation.

3. Trace: each intent's Searcher run is traced. The trace — full LLM messages
   (system/user/assistant/tool), the tool call (the GCL query, or the batch of
   {docid,grade,reason} judgements), the cover_search request actually sent
   (query/top_k/exclude_docids/window), the engine response (total_matches,
   unjudged_matches, atom_counts, results/summaries), any judge-before-search or EngineError
   bounce, the controller's termination reason, and the final RankedList — is ALWAYS
   captured and saved per intent (intent-NN.trace.txt via C2). --verbose additionally
   STREAMS it to the console during the run. (This is the trace previously specced on C1's
   live-run entry; it now lives here.)

4. The CLI run IS the full real-LLM live integration GATE (moved here from C1; the point of
   running it). With the C++ stack built (A0/A1/A2 cover_search + isj profile),
   cottontail-jsonl-server running over Scrapheap/climbmix-1000-utf8-porter.burrow on a
   loopback port, and vLLM gpt-oss-120b up, running the CLI on a question exercises the
   WHOLE pipeline live: cover_search with word*, exclude_docids accumulation across turns,
   an EngineError bounce, the controller loop, and a populated output directory. External
   services -> obtain explicit operator go-ahead before running.

## Non-goals

- No subcommands (the CLI is a single flag-based entry).
- No fusion/RRF, no Task-R TSV / RAG-JSONL output, no Writer/Validator.
- No multi-question batch — one question per run.
- No C++ or server changes; no new engine tools.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Python in isj/. Depends on B2, C1, C2. Adapt as needed.

1. uv sync --project isj. Read isj_agent/orchestrator.py (stub), cli.py (the current Analyst
   demo + config loading), C1's build_search_engine + HttpSearchEngine + trace facility,
   B2's Searcher.run, and C2's write_run.
2. Orchestrator.run_question(question): analyst.analyze -> Intents; per interpretation, run
   the Searcher with tracing on, collect IntentResult{ranked_list, trace}; return
   (intents, results). Trace capture: coordinate with B2/C1 (Searcher.run exposes the trace
   via a sink/return, or wrap the loop with the C1 tracer); keep the trace content per item 3.
3. cli.py: REWRITE main() to a single flag-based argparse entry — --question (required),
   --out (required), --overwrite, --verbose. NO subparsers, NO positional args. Read
   config.toml; build_client([llm.default]); build_search_engine([cottontail_http_json_server]);
   construct Analyst + Searcher + Orchestrator; run_question; write_run; print the summary;
   if --verbose, stream the per-intent trace. Remove the old Analyst-only demo behavior.
4. isj/tests/test_orchestrator.py (no network): drive run_question with a STUB Analyst
   (fixed Intents) + a STUB/Fake Searcher (fixed RankedLists + traces, or B2 over the B1
   FakeEngine + a stub LLM); assert one IntentResult per interpretation; write_run to
   tmp_path and assert the directory contents. No live network.
5. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: the CLI
   (--question/--out/--overwrite/--verbose, no subcommands), the output directory, and the
   live-run prerequisites (server + vLLM up, operator go-ahead).
6. LIVE gate (after A0/A1/A2/B2/C1/C2 exist + go-ahead): config.toml -> vLLM + the running
   server over Scrapheap/climbmix-1000-utf8-porter.burrow; run
   `python -m isj_agent.cli --question <q> --out runs/<name> --verbose`; confirm a populated
   output directory with sensible per-intent results + traces; debug any contract mismatch
   the trace reveals; capture notes.
<!-- SECTION:PLAN:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 orchestrator.run_question(question) drives Analyst.analyze -> Intents, then for each interpretation in order runs the Searcher capturing its verbose trace, returning per-intent (RankedList, trace); it does not write files and does not fuse.
- [ ] #2 The CLI is a SINGLE entry with NO subcommands and all inputs as flags: python -m isj_agent.cli --question <q> --out <dir> [--overwrite] [--verbose]; it reads config.toml, builds the LLM client (build_client) and HttpSearchEngine (build_search_engine), runs run_question, writes the output directory via C2 write_run, and prints a summary; it replaces the current Analyst-only demo (Analyst becomes an internal step).
- [ ] #3 The per-intent verbose loop trace (full LLM messages, the tool call, the cover_search request, the engine response, any judge-before-search/EngineError bounce, the termination reason, the final RankedList) is always captured and saved per intent (intent-NN.trace.txt via C2); --verbose additionally streams it to the console.
- [ ] #4 One question per run; one output directory per run; no fusion/RRF.
- [ ] #5 Automated tests drive run_question with a stub Analyst + a stub/Fake Searcher (no network), assert one IntentResult per interpretation, and assert the written output directory contents (intents.json + per-intent json + trace).
- [ ] #6 The CLI run is the full real-LLM live integration gate: with the C++ stack built, cottontail-jsonl-server over Scrapheap/climbmix-1000-utf8-porter.burrow, and vLLM gpt-oss-120b up, running it on a question completes the whole pipeline (cover_search with word*, exclude_docids accumulation, an EngineError bounce) and produces a populated output directory; external services require operator go-ahead; the transcript/notes are captured.
- [ ] #7 uv run --directory isj pytest tests/ exits 0; no automated test contacts a network or a real model.
- [ ] #8 isj/README.md documents the CLI (--question/--out/--overwrite/--verbose, no subcommands), the run output directory, and the live-run prerequisites/go-ahead.
<!-- AC:END -->
