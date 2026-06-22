---
id: TASK-5.9
title: >-
  C3 — isj: CLI orchestrator (question -> Analyst -> per-intent Searcher ->
  write run output)
status: To Do
assignee: []
created_date: '2026-06-18 04:41'
updated_date: '2026-06-22 00:32'
labels:
  - python
  - isj
  - searcher
  - integration
dependencies:
  - TASK-5.6
  - TASK-5.7
  - TASK-5.8
  - TASK-6.3
references:
  - isj/isj_agent/orchestrator.py
  - isj/isj_agent/cli.py
  - isj/isj_agent/protocol/intents.py
  - isj/README.md
  - Scrapheap/climbmix-100k-porter.burrow
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
writer, incl. errors.log). NO C++.

## Context (for an agent new to this project)

The end-to-end runner AND the full real-LLM live integration gate: ONE question in, a run
output DIRECTORY out. Pipeline:
  Analyst.analyze(question) -> Intents (question + ordered interpretations)
  for each interpretation (in order): Searcher.run(interp) over the LIVE engine
      (HttpSearchEngine, C1) -> SearcherResult { ranked_list: RankedList,
      events: list[TraceEvent] }   (or, on failure, a recorded error)
  write the run directory via C2's write_run (intents.json + intent-NN.json +
      intent-NN.trace.jsonl, plus errors.log iff anything failed)
There is NO fusion (RRF/Task-R/RAG dropped/out of scope). One question per invocation.

Endpoints come from config.toml (see C1): [llm.default] -> the vLLM model (build_client);
[cottontail_http_json_server] -> the cottontail-jsonl-server (build_search_engine ->
HttpSearchEngine). The CLI takes ALL inputs as FLAGS (no subcommands), including the
question via --question, consistent with --out.

The trace is produced BY THE SEARCHER (B2): Searcher.run returns SearcherResult.events, a
list[TraceEvent] (the structured, timestamped event log). C3 captures sr.events per intent,
hands them to C2, and on --verbose renders them to the console. C3 builds no tracer.

## Required behavior (the contract)

1. Orchestrator (isj_agent/orchestrator.py): run_question(question: str) -> (Intents,
   outcomes). intents = self.analyst.analyze(question); for each interpretation in order,
   TRY sr = self.searcher.run(interpretation) and collect IntentResult{ranked_list,
   events}; on an EXCEPTION escaping the Searcher, CATCH it, collect a RunError(message)
   for that intent (with a useful message / short traceback), and CONTINUE to the next
   interpretation (one failed intent must not abort the rest). `outcomes` is one entry per
   interpretation (IntentResult on success, RunError on failure), in order. Run-level
   failures (e.g. Analyst.analyze raising) are also captured as errors. The orchestrator
   does NOT write files (C2) and does NOT fuse.

2. CLI — a SINGLE entry, NO subcommands; ALL inputs are flags:
     python -m isj_agent.cli --question <q> --out <dir> [--overwrite] [--verbose]
   Reads config.toml; builds the LLM client (build_client) and HttpSearchEngine
   (build_search_engine); constructs Analyst + Searcher + Orchestrator; runs
   run_question(question); calls C2 write_run(out_dir, intents, outcomes, overwrite=...);
   prints a short summary (out_dir, #interpretations, #succeeded, #failed). This REPLACES
   the current Analyst-only demo in cli.py. One question per invocation.

3. errors.log is the success/failure SIGNAL. C2 writes errors.log into the output directory
   IFF something went wrong (>=1 intent failed, or a run-level error). ABSENCE of errors.log
   means every intent completed successfully; its PRESENCE means something failed and it
   contains the error messages (tagged with the failing intent's index). The CLI surfaces
   this in its summary and exits non-zero when errors.log was written.

4. Trace: the per-intent trace is B2's SearcherResult.events. It is captured per intent and
   saved as intent-NN.trace.jsonl (via C2, one event per line). --verbose additionally
   RENDERS the events to the console during the run.

5. The CLI run IS the full real-LLM live integration GATE. With the C++ stack built (A1/A2
   cover_search), cottontail-jsonl-server running over
   Scrapheap/climbmix-100k-porter.burrow on a loopback port, and vLLM gpt-oss-120b up,
   running the CLI on a question exercises the WHOLE pipeline live and produces a populated
   output directory (with per-intent event traces, and errors.log iff anything failed).
   External services -> obtain explicit operator go-ahead before running.

## Non-goals

- No subcommands (the CLI is a single flag-based entry).
- No fusion/RRF, no Task-R TSV / RAG-JSONL output, no Writer/Validator.
- No multi-question batch — one question per run.
- No C++ or server changes; no new engine tools; no per-agent/profile filtering. No trace
  GENERATION (the Searcher/B2 emits the events; C3 only captures, renders, and routes them
  to C2).
<!-- SECTION:DESCRIPTION:END -->


## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Python in isj/. Depends on B2, C1, C2. Adapt as needed.

1. uv sync --project isj. Read isj_agent/orchestrator.py (stub), cli.py (the current Analyst
   demo + config loading), C1's build_search_engine + HttpSearchEngine, B2's Searcher.run
   (returns SearcherResult{ranked_list, events}) + the TraceEvent type, and C2's write_run
   (outcomes = IntentResult | RunError; errors.log).
2. Orchestrator.run_question(question): analyst.analyze -> Intents (catch a failure here as a
   run-level error); per interpretation, try searcher.run(interp) -> IntentResult else catch
   the exception -> RunError(message) and continue; return (intents, outcomes) with one
   outcome per interpretation. Use sr.events for the trace.
3. cli.py: REWRITE main() to a single flag-based argparse entry — --question (required),
   --out (required), --overwrite, --verbose. NO subparsers/positional args. Read config.toml;
   build_client + build_search_engine; construct Analyst + Searcher + Orchestrator;
   run_question; write_run(out_dir, intents, outcomes, overwrite); print a summary
   (#succeeded/#failed) and exit non-zero if any intent failed (errors.log written); if
   --verbose, render each intent's events live. Remove the old Analyst-only demo.
4. isj/tests/test_orchestrator.py (no network): (a) drive run_question with a STUB Analyst +
   a STUB/Fake Searcher (B2 over FakeEngine + a stub LLM, or a fake returning fixed
   SearcherResults); assert one outcome per interpretation; write_run to tmp_path and assert
   the dir contents (intents.json + intent-NN.json + intent-NN.trace.jsonl, NO errors.log).
   (b) make one intent's Searcher RAISE; assert run_question records a RunError for it and
   continues; assert the other intents are written and errors.log exists with the failing
   intent's index. No live network.
5. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: the CLI
   (--question/--out/--overwrite/--verbose, no subcommands), the output directory (incl.
   per-intent .trace.jsonl and the optional errors.log whose absence means full success),
   and the live-run prerequisites (server + vLLM up, operator go-ahead).
6. LIVE gate (after A1/A2/B2/C1/C2 exist + go-ahead): config.toml -> vLLM + the running
   server over Scrapheap/climbmix-100k-porter.burrow; run
   `python -m isj_agent.cli --question <q> --out runs/<name> --verbose`; confirm a populated
   output directory (and no errors.log on success); capture notes.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). SUPERSEDES the prior note. The pipeline is unchanged; identities are cp on the wire and through the agent, rewritten to docno by C2 at persistence. The live gate runs against the cp-native burrow built by the TASK-6.3 index CLI (dev: Scrapheap/climbmix-100k-porter.burrow). Authoritative: doc-6.
<!-- SECTION:NOTES:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 orchestrator.run_question(question) -> (Intents, list[IntentResult | RunError]): Analyst.analyze -> Intents, then for each interpretation in order TRY sr = Searcher.run(interpretation) and collect IntentResult{ranked_list: sr.ranked_list, events: sr.events}, else CATCH the exception escaping the Searcher and collect a RunError(message) for that intent; outcomes has one entry per interpretation, in order; it does not write files and does not fuse.
- [ ] #2 The CLI is a SINGLE entry with NO subcommands and all inputs as flags: python -m isj_agent.cli --question <q> --out <dir> [--overwrite] [--verbose]; it reads config.toml, builds the LLM client (build_client) and HttpSearchEngine (build_search_engine), opens the cp->docno SQLite map (read-only) at the configured path (the burrow docno-cp.sqlite, co-located per issue #1), runs run_question, writes the output directory via C2 write_run (passing the map), and prints a summary; it replaces the current Analyst-only demo (Analyst becomes an internal step).
- [ ] #3 The per-intent structured event trace is B2's SearcherResult.events (a list of TraceEvent); it is always captured per intent and saved as intent-NN.trace.jsonl via C2 (one event per line); --verbose additionally renders the events to the console live. C3 builds no tracer of its own.
- [ ] #4 One question per run; one output directory per run; no fusion/RRF.
- [ ] #5 Automated tests drive run_question with a stub Analyst + a stub/Fake Searcher (no network), assert one outcome per interpretation (an IntentResult on success carrying ranked_list + events), and assert the written output directory contents (intents.json + per-intent json + trace.jsonl).
- [ ] #6 The CLI run is the full real-LLM live integration gate: with the C++ stack built, cottontail-jsonl-server over Scrapheap/climbmix-100k-porter.burrow, and vLLM gpt-oss-120b up, running it on a question completes the whole pipeline (cover_search with word*, exclude accumulation, an EngineError bounce) and produces a populated output directory with per-intent event traces; external services require operator go-ahead; the transcript/notes are captured.
- [ ] #7 uv run --directory isj pytest tests/ exits 0; no automated test contacts a network or a real model.
- [ ] #8 isj/README.md documents the CLI (--question/--out/--overwrite/--verbose, no subcommands), the run output directory (incl. the per-intent .trace.jsonl event logs), and the live-run prerequisites/go-ahead.
- [ ] #9 run_question catches a per-intent Searcher failure as a RunError for that intent and CONTINUES to the next interpretation (one failure does not abort the rest); run-level failures (e.g. Analyst.analyze raising) are also captured; outcomes is one entry per interpretation (IntentResult or RunError).
- [ ] #10 errors.log is the success signal: C2 writes it into the output directory IFF something failed; its ABSENCE means every intent succeeded. The CLI summarizes #succeeded/#failed and exits non-zero when errors.log was written. A test makes one intent's Searcher raise and asserts the other intents are written, errors.log exists with the failing intent's index, and the run did not abort.
<!-- AC:END -->
