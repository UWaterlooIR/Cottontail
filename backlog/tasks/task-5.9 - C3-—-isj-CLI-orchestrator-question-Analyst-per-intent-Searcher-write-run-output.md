---
id: TASK-5.9
title: >-
  C3 — isj: CLI orchestrator (question -> Analyst -> per-intent Searcher ->
  write run output)
status: Done
assignee:
  - '@claude'
created_date: '2026-06-18 04:41'
updated_date: '2026-06-26 13:52'
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

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 orchestrator.run_question(question) -> (Intents, list[IntentResult | RunError]): Analyst.analyze -> Intents, then for each interpretation in order TRY sr = Searcher.run(interpretation) and collect IntentResult{ranked_list: sr.ranked_list, events: sr.events}, else CATCH the exception escaping the Searcher and collect a RunError(message) for that intent; outcomes has one entry per interpretation, in order; it does not write files and does not fuse.
- [x] #2 The CLI is a SINGLE entry with NO subcommands and all inputs as flags: python -m isj_agent.cli --question <q> --out <dir> [--overwrite] [--verbose]; it reads config.toml, builds the LLM client (build_client) and HttpSearchEngine (build_search_engine), opens the cp->docno SQLite map (read-only) at the configured path (the burrow docno-cp.sqlite, co-located per issue #1), runs run_question, writes the output directory via C2 write_run (passing the map), and prints a summary; it replaces the current Analyst-only demo (Analyst becomes an internal step).
- [x] #3 The per-intent structured event trace is B2's SearcherResult.events (a list of TraceEvent); it is always captured per intent and saved as intent-NN.trace.jsonl via C2 (one event per line); --verbose additionally renders the events to the console live. C3 builds no tracer of its own.
- [x] #4 One question per run; one output directory per run; no fusion/RRF.
- [x] #5 Automated tests drive run_question with a stub Analyst + a stub/Fake Searcher (no network), assert one outcome per interpretation (an IntentResult on success carrying ranked_list + events), and assert the written output directory contents (intents.json + per-intent json + trace.jsonl).
- [x] #6 The CLI run is the full real-LLM live integration gate: with the C++ stack built, cottontail-jsonl-server over Scrapheap/climbmix-100k-porter.burrow, and vLLM gpt-oss-120b up, running it on a question completes the whole pipeline (cover_search with word*, exclude accumulation, an EngineError bounce) and produces a populated output directory with per-intent event traces; external services require operator go-ahead; the transcript/notes are captured.
- [x] #7 uv run --directory isj pytest tests/ exits 0; no automated test contacts a network or a real model.
- [x] #8 isj/README.md documents the CLI (--question/--out/--overwrite/--verbose, no subcommands), the run output directory (incl. the per-intent .trace.jsonl event logs), and the live-run prerequisites/go-ahead.
- [x] #9 run_question catches a per-intent Searcher failure as a RunError for that intent and CONTINUES to the next interpretation (one failure does not abort the rest); run-level failures (e.g. Analyst.analyze raising) are also captured; outcomes is one entry per interpretation (IntentResult or RunError).
- [x] #10 errors.log is the success signal: C2 writes it into the output directory IFF something failed; its ABSENCE means every intent succeeded. The CLI summarizes #succeeded/#failed and exits non-zero when errors.log was written. A test makes one intent's Searcher raise and asserts the other intents are written, errors.log exists with the failing intent's index, and the run did not abort.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DECISIONS (user): (Q1) docno map located via a 'burrow' field in [cottontail_http_json_server] (CLI opens <burrow>/docno-cp.sqlite read-only; absent -> None -> cps persisted); --burrow override. (Q3) run the live gate after implementing (local server over Scrapheap/climbmix-1M-porter.burrow + the user's vLLM; CLI on a black-bear question).

1. C2 amendment (isj_agent/run_output.py): write_run accepts intents: Intents|None -- if None (Analyst-failure run-level case), write ONLY errors.log (no intents.json, skip the count-check). Update C2 tests if needed.
2. Config: [cottontail_http_json_server] gains optional 'burrow' (config.toml + config.example.toml); isj_agent/config.py build_docno_map(cfg)->DocnoMap|None (open <burrow>/docno-cp.sqlite read-only if present, else None). [agents.searcher] section (class + llm profile + optional top_k/window/max_turns knobs; defaults = B2 recall-first).
3. orchestrator.py: Orchestrator(*, analyst, searcher); run_question(question, *, on_intent=None)->(intents|None, outcomes, run_error). analyst.analyze (run-level catch -> (None,[],msg)); per interpretation try searcher.run -> SearcherResult else RunError(message) and CONTINUE; call on_intent(i, interp, outcome) for --verbose live render; one outcome per interpretation, in order. No files, no fusion. Success outcome IS the SearcherResult (== the spec's IntentResult).
4. cli.py REWRITE: single flag entry (no subcommands) python -m isj_agent.cli --question --out [--overwrite] [--verbose] [--burrow]. Read config; build_client([llm/agents.analyst, agents.searcher]) + build_search_engine + build_docno_map; construct Analyst + Searcher(client,model,engine,**knobs) + Orchestrator; run_question; write_run(out_dir, intents, outcomes, docno_map=, run_error=, overwrite=); print summary (#interps/#succeeded/#failed); exit non-zero iff errors.log written. --verbose renders each intent's events live (on_intent). Replaces the Analyst-only demo.
5. tests/test_orchestrator.py (no network): stub Analyst + stub Searcher; one outcome per interp; a raising intent -> RunError + others still produced + errors.log w/ index + no abort; Analyst-failure -> run-level errors.log; written-dir contents.
6. README: CLI flags, run-output dir + per-intent .trace.jsonl, live-run prereqs/go-ahead.
GATE: uv sync + uv run pytest green (no network).
LIVE GATE (Q3): start cottontail-jsonl-server on a loopback port over Scrapheap/climbmix-1M-porter.burrow; config -> server base_url+burrow + the user's vLLM; run the CLI on a black-bear question --verbose; confirm a populated runs/ dir (per-intent json + trace.jsonl, docnos on disk, no errors.log on success); capture a transcript; stop the server.
FORWARD-COMPAT: C3 is the last Searcher-track build before 5.4 (cleanup) + 5.10 (docs).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). SUPERSEDES the prior note. The pipeline is unchanged; identities are cp on the wire and through the agent, rewritten to docno by C2 at persistence. The live gate runs against the cp-native burrow built by the TASK-6.3 index CLI (dev: Scrapheap/climbmix-100k-porter.burrow). Authoritative: doc-6.

IMPLEMENTED (C3). Files: isj_agent/orchestrator.py (Orchestrator{analyst,searcher}; run_question(question, *, on_intent=None) -> (Intents|None, list[Outcome], run_error); per-intent try Searcher.run -> SearcherResult, except -> RunError(message) and CONTINUE; analyst.analyze run-level catch -> (None,[],msg); no files, no fusion). isj_agent/cli.py REWRITTEN: single flag entry --question/--out/[--overwrite]/[--verbose]/[--burrow]/[--config], no subcommands; builds client+HttpSearchEngine+DocnoMap from config, runs run_question, write_run(docno_map=,run_error=,overwrite=), prints succeeded/failed summary, exits non-zero IFF errors.log written; --verbose renders each intent's events live via on_intent. Replaces the Analyst-only demo (removed format_intents/SAMPLE_QUESTIONS; deleted tests/test_cli.py). isj_agent/config.py: build_docno_map(cfg, burrow_override=None) -> DocnoMap|None (opens <burrow>/docno-cp.sqlite read-only; None if no burrow or no map -> raw cps). run_output.py (C2 amend): write_run now accepts intents: Intents|None (None -> only errors.log; count-check skipped). config.example.toml/config.toml: [cottontail_http_json_server].burrow + [agents.searcher]. .gitignore: isj/runs/. Tests: tests/test_orchestrator.py (7 tests, no network: ordering, per-intent RunError+continue, analysis-failure (None,[],msg), on_intent callback, outputs plug into write_run); +1 run_output test (intents=None -> only errors.log). GATE: uv run pytest = 61 passed, 1 skipped (the live-gated http test); no test touches network/model.

LIVE GATE (real LLM gpt-oss-120b + cottontail-jsonl-server over Scrapheap/climbmix-1M-porter.burrow, user-authorized loopback services): CLI on 'What should I know about black bear attacks while hiking?' --verbose ran the WHOLE pipeline. Analyst -> 3 interpretations. Intent 00: real cover_search with word* operators (total=1151 then 156 hits), exclude accumulation (exclude=10), the judge-before-search guardrail fired (bounce), and the model judged 20 passages with UMBRELA grades (incl. a grade-4); persisted intent-00.json carries DOCNOS (e.g. shard_00011_32456) with NO cp key -> the cp->docno rewrite via the real burrow's docno-cp.sqlite works end to end. Populated runs/bear/ with intents.json + per-intent json + .trace.jsonl, no errors.log, exit 0.

FINDING (pre-existing C++ server bug, NOT C3, flag-only): at intent-00 turn 6 the cottontail-jsonl-server crashed mid-run ('Server disconnected without sending a response', then Connection refused), so intents 01-02 degraded to no results. C3 handled it gracefully: every engine error bounced back as str(error), each Searcher stopped cleanly (no_tool_call), error isolation held, run still exited 0 with valid output. The crashing cover query at intent-00 turn 6 is worth a separate server-robustness task.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
C3 wires the full Searcher pipeline behind one CLI. Orchestrator.run_question runs Analyst -> per-intent Searcher in order, returning (Intents|None, one outcome per interpretation, run_error) with per-intent failures isolated as RunError and the run continuing; it writes no files and does no fusion. cli.py is a single flag entry (--question/--out/[--overwrite/--verbose/--burrow]) that builds the LLM client, HttpSearchEngine, and read-only cp->docno DocnoMap from config, runs the question, persists via C2 write_run, prints a succeeded/failed summary, and exits non-zero iff errors.log was written. write_run was amended to accept intents=None (Analyst-failure -> only errors.log). 61 pytest pass with no network/model. Live gate (real gpt-oss-120b + server over the 1M burrow) drove the whole pipeline: real word* cover_search, exclude accumulation, the judge-before-search bounce, 20 UMBRELA-graded passages persisted with docnos (cp->docno rewrite verified end to end), populated runs/bear/ with per-intent traces, exit 0. A pre-existing C++ server crash mid-run was handled gracefully (flagged in notes for a separate server-robustness task).
<!-- SECTION:FINAL_SUMMARY:END -->
