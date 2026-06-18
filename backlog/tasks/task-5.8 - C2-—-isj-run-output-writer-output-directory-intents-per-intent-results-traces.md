---
id: TASK-5.8
title: >-
  C2 — isj: run-output writer (output directory: intents + per-intent results &
  traces)
status: To Do
assignee: []
created_date: '2026-06-18 04:40'
updated_date: '2026-06-18 13:29'
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
list[TraceEvent]; see B2). Those per-intent results must be PERSISTED to disk for later
analysis. NOT fused or post-processed — RRF, Task-R, RAG are OUT OF SCOPE (dropped). C2 just
defines the on-disk format and writes it; the orchestrator (C3) produces the data.

The types:
- Intents (isj_agent/protocol/intents.py): { question: str, interpretations: list[str] }.
- RankedList (B2): { intent: str, entries: list[RankedEntry] }, RankedEntry =
  { rank, docid, grade (0-4), score, summary, reason, surfacing_query }.
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

   - NN is the zero-based, zero-padded (>= 2 digits) index matching the interpretation's
     position in Intents.interpretations (intent-00 <-> interpretations[0]).
   - intents.json   = Intents.model_dump_json(indent=2).
   - intent-NN.json = the RankedList for interpretations[NN], model_dump_json(indent=2).
   - intent-NN.trace.jsonl = the SearcherResult.events for that intent, serialized as JSON
     Lines: one TraceEvent JSON object per line (event.model_dump_json() per line, no indent).
     Written when events are provided (an empty list writes an empty file).

2. A writer in isj_agent/run_output.py, e.g.:
     write_run(out_dir: Path, intents: Intents, results: Sequence[IntentResult],
               *, overwrite: bool = False) -> None
   where IntentResult bundles { ranked_list: RankedList, events: list[TraceEvent] } (a small
   dataclass/model is fine; or accept SearcherResult directly). The number of results MUST
   equal len(intents.interpretations) — a mismatch is an error. Create out_dir; if it exists
   and is non-empty, refuse unless overwrite=True. UTF-8; pretty JSON for the .json files;
   JSON Lines (one object per line) for the .trace.jsonl files; stable field order via pydantic.

3. PURE: no network, no LLM, no Searcher logic. The events are produced upstream (B2's
   controller, captured by C3); C2 persists whatever RankedList + events it is given.

## Non-goals

- No fusion/RRF (dropped), no Task-R/RAG formatting (downstream).
- No orchestration (C3 owns running Analyst + the Searcher and producing the data).
- No trace GENERATION (the B2 controller emits the TraceEvents; C3 captures them); C2 only
  serializes them to JSON Lines.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Pure Python in isj/. Depends on B2's RankedList/TraceEvent/SearcherResult. Adapt as needed.

1. uv sync --project isj. Read isj_agent/protocol/intents.py (Intents) and B2's
   RankedList/TraceEvent/SearcherResult for model_dump_json usage.
2. isj_agent/run_output.py: optionally a small IntentResult { ranked_list: RankedList,
   events: list[TraceEvent] } (or just accept SearcherResult); and write_run(out_dir,
   intents, results, *, overwrite=False): validate len(results) == len(intents.interpretations);
   create/guard out_dir; write intents.json (Intents.model_dump_json(indent=2)); per i, write
   intent-{i:02d}.json (ranked_list.model_dump_json(indent=2)) and intent-{i:02d}.trace.jsonl
   (one event.model_dump_json() per line).
3. isj/tests/test_run_output.py (no network): write a run to tmp_path with a constructed
   Intents + a couple of RankedLists + event lists; assert intents.json round-trips to the
   Intents; each intent-NN.json round-trips to its RankedList; intent-NN.trace.jsonl has one
   JSON object per line that round-trips to a TraceEvent and preserves order; file count and
   zero-padding are correct; a count mismatch raises; writing into a non-empty dir without
   overwrite raises and with overwrite succeeds.
4. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: document the
   run-output directory layout (intents.json + intent-NN.json + intent-NN.trace.jsonl), and
   that intent-NN.trace.jsonl is a JSON-Lines event log (a research artifact).
<!-- SECTION:PLAN:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 isj_agent/run_output.py defines the run-directory layout and a writer (write_run) that, given an Intents and the per-intent results, writes <outdir>/intents.json plus intent-NN.json and intent-NN.trace.jsonl as specified.
- [ ] #2 intents.json is Intents.model_dump_json(indent=2); each intent-NN.json is the RankedList for interpretations[NN] (model_dump_json indent=2); NN is zero-based, zero-padded (>=2 digits), and matches the interpretation index.
- [ ] #3 intent-NN.trace.jsonl is the per-intent event trace serialized as JSON Lines — one TraceEvent JSON object per line (event.model_dump_json() per line); an empty event list writes an empty file.
- [ ] #4 The number of per-intent results must equal len(intents.interpretations); a mismatch raises an error.
- [ ] #5 The writer creates the output directory and refuses to overwrite a non-empty existing directory unless overwrite=True.
- [ ] #6 C2 is pure (filesystem only): no network, no LLM, no Searcher logic, no trace generation; it persists whatever RankedList + events it is given.
- [ ] #7 Tests (no network) write a run to a temp dir and assert: intents.json round-trips to the Intents; each intent-NN.json round-trips to its RankedList; intent-NN.trace.jsonl has one JSON object per line that round-trips to a TraceEvent and preserves order; file count and NN padding are correct; the count-mismatch and overwrite guards work.
- [ ] #8 uv run --directory isj pytest tests/ exits 0; isj/README.md documents the run-output directory layout and that intent-NN.trace.jsonl is a JSON-Lines event log (a research artifact).
<!-- AC:END -->
