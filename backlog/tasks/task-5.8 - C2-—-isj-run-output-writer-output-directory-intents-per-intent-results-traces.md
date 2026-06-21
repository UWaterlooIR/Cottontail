---
id: TASK-5.8
title: >-
  C2 — isj: run-output writer (output directory: intents + per-intent results &
  traces)
status: To Do
assignee: []
created_date: '2026-06-18 04:40'
updated_date: '2026-06-21 19:41'
labels:
  - python
  - isj
  - searcher
dependencies:
  - TASK-5.6
references:
  - isj/isj_agent/protocol/intents.py
  - isj/README.md
parent_task_id: TASK-5
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

Python, in the `isj/` uv project (package `isj_agent`; `uv sync --project isj` after
changes). New file `isj_agent/run_output.py` (the layout + writer); tests in `isj/tests/`.
PURE filesystem — NO network, NO LLM. DEPENDS ON B2 (TASK-5.6) for the RankedList,
TraceEvent and SearcherResult types, and uses the existing Intents type
(isj_agent/protocol/intents.py).

## Context (for an agent new to this project)

The Searcher pipeline runs, per question: Analyst.analyze(question) -> Intents (the question
plus an ordered list of interpretations); then, per interpretation, the Searcher produces a
SearcherResult = a RankedList (judged passages) + a structured event trace (a
list[TraceEvent]; see B2). Some intents may FAIL (an exception escapes the Searcher). The
per-intent results that succeeded must be PERSISTED to disk, and failures recorded, for
later analysis. NOT fused or post-processed — RRF, Task-R, RAG are OUT OF SCOPE (dropped).
C2 just defines the on-disk format and writes it; the orchestrator (C3) produces the data
and catches the errors.

The types:
- Intents (isj_agent/protocol/intents.py): { question: str, interpretations: list[str] }.
- RankedList (B2): { intent: str, entries: list[RankedEntry] }, RankedEntry =
  { rank, cp, grade (0-4), score, summary, reason, surfacing_query }.
- TraceEvent (B2): { type, ts (epoch seconds), duration_ms, ...type-specific fields }
  (extra="allow") — the trace is a list of these (a research artifact for statistics).

## Required behavior (the contract)

1. Output directory layout — ONE directory per run (one question per run):

   <outdir>/
     intents.json            the Intents (question + ordered interpretations), pretty JSON
     intent-00.json          interpretation #0: its RankedList (intent + entries), pretty JSON
     intent-00.trace.jsonl   interpretation #0: the event trace, ONE TraceEvent JSON per line
     intent-01.json
     intent-01.trace.jsonl
     ...
     errors.log              PRESENT ONLY IF SOMETHING WENT WRONG — error messages

   - NN is the zero-based, zero-padded (>= 2 digits) index matching the interpretation's
     position in Intents.interpretations (intent-00 <-> interpretations[0]).
   - intents.json   = Intents.model_dump_json(indent=2).
   - intent-NN.json = the RankedList for interpretations[NN] (only for intents that
     SUCCEEDED), model_dump_json(indent=2).
   - intent-NN.trace.jsonl = the SearcherResult.events for that intent, serialized as JSON
     Lines: one TraceEvent JSON object per line (event.model_dump_json() per line).
   - errors.log = written IFF something went wrong (>=1 intent failed, or a run-level
     error). It contains human-readable error messages, each tagged with the failing
     intent's index (and interpretation text) where applicable. THE ABSENCE OF errors.log
     MEANS EVERY INTENT COMPLETED SUCCESSFULLY; its PRESENCE means something failed and the
     file explains what. (A failed intent has no intent-NN.json/.trace.jsonl; it appears in
     errors.log instead.)

2. A writer in isj_agent/run_output.py, e.g.:
     write_run(out_dir: Path, intents: Intents,
               outcomes: Sequence[IntentResult | RunError],
               *, overwrite: bool = False) -> None
   where IntentResult bundles { ranked_list: RankedList, events: list[TraceEvent] } (success)
   and RunError bundles { message: str } (failure). `outcomes` is one entry PER
   interpretation, in order (so len(outcomes) == len(intents.interpretations)). For each
   success write intent-NN.json + intent-NN.trace.jsonl; for each failure write nothing for
   that intent. If ANY outcome is a RunError (or a run-level error is also passed in), write
   errors.log with one entry per error (prefixed with the intent index + interpretation when
   intent-specific); otherwise do NOT create errors.log. Create out_dir; if it exists and is
   non-empty, refuse unless overwrite=True. UTF-8; pretty JSON for the .json files; JSON
   Lines for the .trace.jsonl; stable field order via pydantic.

3. PURE: no network, no LLM, no Searcher logic, no error CATCHING (C3 catches the errors and
   passes them in as RunError outcomes / a run-level error). C2 only persists.

## Non-goals

- No fusion/RRF (dropped), no Task-R/RAG formatting (downstream).
- No orchestration (C3 owns running Analyst + the Searcher, catching errors, producing data).
- No trace GENERATION (B2's controller emits the TraceEvents; C3 captures them); C2 only
  serializes them to JSON Lines and writes errors.log from the errors it is given.
<!-- SECTION:DESCRIPTION:END -->


## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Pure Python in isj/. Depends on B2's RankedList/TraceEvent/SearcherResult. Adapt as needed.

1. uv sync --project isj. Read isj_agent/protocol/intents.py (Intents) and B2's
   RankedList/TraceEvent/SearcherResult for model_dump_json usage.
2. isj_agent/run_output.py: small types IntentResult { ranked_list: RankedList,
   events: list[TraceEvent] } and RunError { message: str }; write_run(out_dir, intents,
   outcomes, *, overwrite=False): validate len(outcomes) == len(intents.interpretations);
   create/guard out_dir; write intents.json (Intents.model_dump_json(indent=2)); for each
   index i, if outcomes[i] is an IntentResult write intent-{i:02d}.json
   (ranked_list.model_dump_json(indent=2)) + intent-{i:02d}.trace.jsonl (one
   event.model_dump_json() per line); collect RunError messages; if any, write errors.log
   (one error per line/block, prefixed "intent NN (<interpretation>): <message>"); else do
   not create errors.log.
3. isj/tests/test_run_output.py (no network): (a) all-success run -> intents.json + per-intent
   json/jsonl, NO errors.log; round-trips check. (b) a run with one RunError outcome -> the
   failed intent has no files, the others do, and errors.log exists and contains the failing
   intent's index + message. (c) count mismatch raises; (d) overwrite guard.
4. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: the run-output
   layout (intents.json + intent-NN.json + intent-NN.trace.jsonl + optional errors.log),
   that intent-NN.trace.jsonl is a JSON-Lines event log, and that the ABSENCE of errors.log
   means the whole run succeeded.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). SUPERSEDES the prior note. CHANGE: C2 now performs the cp->docno REWRITE at write time -- it maps each persisted result/trace cp to its docno via the TASK-6.3 SQLite reader, so the saved files carry docno (portable), never a raw cp. Results are cp in memory; docno on disk. (A docno-less corpus persists cp.) The intents + per-intent RankedList + trace.jsonl + errors.log layout is unchanged. Authoritative: doc-6 + TASK-6.3.
<!-- SECTION:NOTES:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 isj_agent/run_output.py defines the run-directory layout and a writer (write_run) that, given an Intents and the per-intent results, writes <outdir>/intents.json plus intent-NN.json and intent-NN.trace.jsonl as specified.
- [ ] #2 intents.json is Intents.model_dump_json(indent=2); each intent-NN.json is the RankedList for interpretations[NN] (model_dump_json indent=2); NN is zero-based, zero-padded (>=2 digits), and matches the interpretation index.
- [ ] #3 intent-NN.trace.jsonl is the per-intent event trace serialized as JSON Lines — one TraceEvent JSON object per line (event.model_dump_json() per line); an empty event list writes an empty file.
- [ ] #4 The writer creates the output directory and refuses to overwrite a non-empty existing directory unless overwrite=True.
- [ ] #5 C2 is pure (filesystem only): no network, no LLM, no Searcher logic, no trace generation; it persists whatever RankedList + events it is given.
- [ ] #6 Tests (no network) write a run to a temp dir and assert: intents.json round-trips to the Intents; each intent-NN.json round-trips to its RankedList; intent-NN.trace.jsonl has one JSON object per line that round-trips to a TraceEvent and preserves order; file count and NN padding are correct; the count-mismatch and overwrite guards work.
- [ ] #7 uv run --directory isj pytest tests/ exits 0; isj/README.md documents the run-output directory layout and that intent-NN.trace.jsonl is a JSON-Lines event log (a research artifact).
- [ ] #8 write_run takes one outcome per interpretation, in order (len(outcomes) == len(intents.interpretations)); each is a success (IntentResult) or a failure (RunError); a count mismatch raises.
- [ ] #9 errors.log is written IFF at least one outcome is a failure (or a run-level error is passed): it contains the error messages, each tagged with the failing intent's index (and interpretation) where intent-specific. Its ABSENCE means every intent completed successfully; a failed intent has no intent-NN.json/.trace.jsonl and appears only in errors.log.
- [ ] #10 Before persisting, C2 rewrites each RankedEntry cp to its docno via the TASK-6.3 SQLite reader, so the written intent-NN.json carries docno (portable), never a raw cp; a docno-less corpus (no map) persists cp.
<!-- AC:END -->
