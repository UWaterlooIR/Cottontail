---
id: TASK-5.9
title: >-
  C3 — isj: CLI orchestrator (question -> Analyst -> per-intent Searcher ->
  write run output)
status: To Do
assignee: []
created_date: '2026-06-18 04:41'
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
`isj_agent/orchestrator.py` (currently a stub holding the Analyst) and extends
`isj_agent/cli.py`. DEPENDS ON B2 (TASK-5.6: the Searcher), C1 (TASK-5.7: HttpSearchEngine
+ build_search_engine config + the verbose --trace facility) and C2 (TASK-5.8: the
run-output writer). NO C++.

## Context (for an agent new to this project)

This is the end-to-end runner: ONE question in, a run output DIRECTORY out. Pipeline:
  Analyst.analyze(question) -> Intents (question + ordered interpretations)
  for each interpretation (in order): Searcher.run(interp) over the LIVE engine
      (HttpSearchEngine, C1) with verbose tracing -> (RankedList, trace)
  write the run directory via C2's write_run (intents.json + intent-NN.json + intent-NN.trace.txt)
There is NO fusion: RRF/Task-R/RAG are dropped/out of scope. We persist the raw per-intent
results so we can decide what to do with them later. One question per invocation.

The two endpoints come from config.toml (see C1): [llm.default] -> the vLLM model
(via build_client); [cottontail_http_json_server] -> the cottontail-jsonl-server
(via build_search_engine -> HttpSearchEngine). The Analyst and Searcher are constructed
with the LLM client; the Searcher additionally with the engine.

## Required behavior (the contract)

1. Orchestrator (isj_agent/orchestrator.py): drive the pipeline. e.g.
     run_question(question: str) -> tuple[Intents, list[IntentResult]]
   intents = self.analyst.analyze(question); for each interpretation in order, run the
   Searcher capturing its verbose trace, collect IntentResult{ranked_list, trace}; return
   (intents, results). The orchestrator does NOT write files itself (that is C2) and does
   NOT fuse.
2. CLI: a subcommand `python -m isj_agent.cli run "<question>" --out <dir> [--overwrite]`
   that reads config.toml, builds the LLM client (build_client) and HttpSearchEngine
   (build_search_engine, C1), constructs the Analyst + Searcher + Orchestrator, runs
   run_question(question), calls C2's write_run(out_dir, intents, results, overwrite=...),
   and prints a short summary (the out_dir, the number of interpretations, per-intent entry
   counts). One question per run.
3. Trace capture: each intent's Searcher run must be traced and the trace string captured
   for C2 (intent-NN.trace.txt). Reuse C1's --verbose/--trace facility — either Searcher.run
   exposes the trace (a sink/return) or the orchestrator wraps the loop with the same
   tracer. This is the one integration point with B2/C1 tracing; keep the trace content
   identical to C1's.
4. The full LIVE run is the product-level end-to-end (C1's live e2e was a single intent):
   real LLM (gpt-oss-120b) + the running cottontail-jsonl-server over
   Scrapheap/climbmix-1000-utf8-porter.burrow, producing a real output directory for one
   question. External services -> obtain explicit operator go-ahead before running.

## Non-goals

- No fusion/RRF, no Task-R TSV / RAG-JSONL output, no Writer/Validator (all downstream or
  dropped).
- No multi-question batch — one question per run.
- No C++ or server changes; no new engine tools.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 isj_agent/orchestrator.py drives the pipeline: run_question(question) calls Analyst.analyze -> Intents, then for each interpretation in order runs the Searcher capturing its trace, collecting per-intent (RankedList, trace); it does not write files and does not fuse.
- [ ] #2 A CLI subcommand python -m isj_agent.cli run "<question>" --out <dir> [--overwrite] reads config.toml, builds the LLM client (build_client) and HttpSearchEngine (build_search_engine), wires Analyst + Searcher + Orchestrator, runs one question, and writes the output directory via C2's write_run.
- [ ] #3 Each intent's Searcher run is traced and the trace captured and saved per intent (intent-NN.trace.txt via C2); the trace content matches C1's --verbose/--trace.
- [ ] #4 One question per run; one output directory per run; no fusion/RRF is performed (per-intent RankedLists are persisted as-is).
- [ ] #5 Automated tests drive run_question with a stub Analyst + a stub/Fake Searcher (no network), assert one IntentResult per interpretation, and assert the written output directory contents (intents.json + per-intent json + trace).
- [ ] #6 The full live run (real LLM gpt-oss-120b + the running cottontail-jsonl-server over Scrapheap/climbmix-1000-utf8-porter.burrow) is documented and, run with operator go-ahead, produces a real output directory for one question; external services require go-ahead.
- [ ] #7 uv run --directory isj pytest tests/ exits 0; no automated test contacts a network or a real model.
- [ ] #8 isj/README.md documents the run command (question -> output directory), one question per run, and the live-run prerequisites.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Python in isj/. Depends on B2, C1, C2. Adapt as needed.

1. uv sync --project isj. Read isj_agent/orchestrator.py (stub), cli.py (the Analyst demo +
   config loading), C1's build_search_engine + HttpSearchEngine + trace facility, B2's
   Searcher.run, and C2's write_run.
2. Orchestrator.run_question(question): analyst.analyze -> Intents; per interpretation, run
   the Searcher with tracing on, collect IntentResult{ranked_list, trace}; return
   (intents, results). Decide trace capture with B2/C1 (Searcher.run trace sink/return, or
   wrap with the C1 tracer); keep trace content identical to C1's.
3. cli.py: add a `run` subcommand (argparse): positional question, --out <dir>, --overwrite.
   Read config.toml; build_client([llm.default]); build_search_engine([cottontail_http_json_server]);
   construct Analyst + Searcher + Orchestrator; run_question; write_run(out_dir, intents,
   results, overwrite); print a summary.
4. isj/tests/test_orchestrator.py (no network): drive run_question with a STUB Analyst
   (returns a fixed Intents) + a STUB/Fake Searcher (returns fixed RankedLists + traces, or
   the B2 Searcher over the B1 FakeEngine + a stub LLM); assert it returns one IntentResult
   per interpretation; then write_run to tmp_path and assert the directory contents
   (intents.json + intent-NN.json + intent-NN.trace.txt). No live network.
5. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: the `run` command
   (question -> output directory), one question per run, and that the live run needs the
   server + vLLM up (operator go-ahead).
6. LIVE run (after A0/A1/A2/B2/C1/C2 exist + go-ahead): config.toml -> vLLM + the running
   server over Scrapheap/climbmix-1000-utf8-porter.burrow; `python -m isj_agent.cli run
   "<question>" --out runs/<name>`; confirm the output directory is produced with sensible
   per-intent results + traces; capture notes.
<!-- SECTION:PLAN:END -->
