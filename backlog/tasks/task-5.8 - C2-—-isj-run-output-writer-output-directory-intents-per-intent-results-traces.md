---
id: TASK-5.8
title: >-
  C2 — isj: run-output writer (output directory: intents + per-intent results &
  traces)
status: To Do
assignee: []
created_date: '2026-06-18 04:40'
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
PURE filesystem — NO network, NO LLM. DEPENDS ON B2 (TASK-5.6) for the RankedList type, and
uses the existing Intents type (isj_agent/protocol/intents.py, from the Analyst work).

## Context (for an agent new to this project)

The Searcher pipeline runs, per question: Analyst.analyze(question) -> Intents (the question
plus an ordered list of interpretations); then, for each interpretation, the Searcher
produces a RankedList (judged passages) plus a verbose loop trace. Those per-intent results
must be PERSISTED to disk for later analysis. IMPORTANT: we are NOT fusing or post-processing
the lists — RRF, Task-R formatting, and RAG are explicitly OUT OF SCOPE (dropped for now).
C2 just defines the on-disk format and writes it; the orchestrator (C3) produces the data.

The types involved:
- Intents (isj_agent/protocol/intents.py): { question: str, interpretations: list[str] }
  (ordered, most-plausible-first).
- RankedList (B2, in isj_agent/protocol/): { intent: str, entries: list[RankedEntry] },
  RankedEntry = { rank, docid, grade (0-4), score, summary, reason, surfacing_query }.

## Required behavior (the contract)

1. Output directory layout — ONE directory per run (one question per run):

   <outdir>/
     intents.json            the Intents (question + ordered interpretations), pretty JSON
     intent-00.json          interpretation #0: its RankedList (intent + entries), pretty JSON
     intent-00.trace.txt     interpretation #0: the verbose Searcher loop trace (plain text)
     intent-01.json
     intent-01.trace.txt
     ...

   - NN is the zero-based, zero-padded (>= 2 digits) index matching the interpretation's
     position in Intents.interpretations (intent-00 <-> interpretations[0]).
   - intents.json   = Intents.model_dump_json(indent=2).
   - intent-NN.json = the RankedList for interpretations[NN], model_dump_json(indent=2).
   - intent-NN.trace.txt = the verbose loop-trace string for that intent's Searcher run
     (the same content as C1's --verbose/--trace); written when a trace is provided.

2. A writer in isj_agent/run_output.py, e.g.:
     write_run(out_dir: Path, intents: Intents, results: Sequence[IntentResult],
               *, overwrite: bool = False) -> None
   where IntentResult bundles { ranked_list: RankedList, trace: str | None } (a small
   dataclass/pydantic model is fine; or pass parallel lists). The number of results MUST
   equal len(intents.interpretations) — a mismatch is an error. The writer creates out_dir;
   if out_dir already exists and is non-empty it refuses unless overwrite=True (mirror the
   index CLI's --overwrite stance). UTF-8; pretty JSON; stable field order via pydantic.

3. PURE: no network, no LLM, no Searcher logic. The trace is just a string the caller
   (C3) supplies; C2 persists whatever RankedList/trace it is given.

## Non-goals

- No fusion/RRF (dropped), no Task-R/RAG formatting (downstream).
- No orchestration (C3 owns running Analyst + the Searcher and producing the data).
- No trace GENERATION (the Searcher/runner produces it — B2/C1/C3); C2 only writes the
  trace string.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 isj_agent/run_output.py defines the run-directory layout and a writer (write_run) that, given an Intents and the per-intent results, writes <outdir>/intents.json plus intent-NN.json and intent-NN.trace.txt as specified.
- [ ] #2 intents.json is Intents.model_dump_json(indent=2); each intent-NN.json is the RankedList for interpretations[NN] (model_dump_json indent=2); NN is zero-based, zero-padded (>=2 digits), and matches the interpretation index.
- [ ] #3 intent-NN.trace.txt holds the verbose Searcher loop-trace string for that intent when one is provided; the writer accepts results carrying an optional trace.
- [ ] #4 The number of per-intent results must equal len(intents.interpretations); a mismatch raises an error.
- [ ] #5 The writer creates the output directory and refuses to overwrite a non-empty existing directory unless overwrite=True.
- [ ] #6 C2 is pure (filesystem only): no network, no LLM, no Searcher logic; it persists whatever RankedList/trace it is given (trace generation belongs to the Searcher/runner).
- [ ] #7 Tests (no network) write a run to a temp dir and assert: intents.json round-trips to the Intents; each intent-NN.json round-trips to its RankedList; intent-NN.trace.txt holds the trace; file count and NN padding are correct; the count-mismatch and overwrite guards work.
- [ ] #8 uv run --directory isj pytest tests/ exits 0; isj/README.md documents the run-output directory layout.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Pure Python in isj/. Depends on B2's RankedList. Adapt as needed.

1. uv sync --project isj. Read isj_agent/protocol/intents.py (Intents) and B2's RankedList
   (isj_agent/protocol/) for model_dump_json usage.
2. isj_agent/run_output.py: optionally a small IntentResult { ranked_list: RankedList,
   trace: str | None }; and write_run(out_dir, intents, results, *, overwrite=False):
   validate len(results) == len(intents.interpretations); create/guard out_dir; write
   intents.json (Intents.model_dump_json(indent=2)); per i, write intent-{i:02d}.json
   (results[i].ranked_list.model_dump_json(indent=2)) and, if results[i].trace is not None,
   intent-{i:02d}.trace.txt.
3. isj/tests/test_run_output.py (no network): write a run to tmp_path with a constructed
   Intents + a couple of RankedLists + traces; assert intents.json round-trips to the
   Intents; each intent-NN.json round-trips to its RankedList; intent-NN.trace.txt holds the
   trace; file count and zero-padding are correct; a count mismatch raises; writing into a
   non-empty dir without overwrite raises and with overwrite succeeds.
4. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: document the
   run-output directory layout (intents.json + intent-NN.json + intent-NN.trace.txt).
<!-- SECTION:PLAN:END -->
