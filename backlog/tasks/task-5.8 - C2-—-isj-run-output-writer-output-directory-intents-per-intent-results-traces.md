---
id: TASK-5.8
title: >-
  C2 — isj: run-output writer (output directory: intents + per-intent results &
  traces)
status: Done
assignee:
  - '@claude'
created_date: '2026-06-18 04:40'
updated_date: '2026-06-26 13:19'
labels:
  - python
  - isj
  - searcher
dependencies:
  - TASK-5.6
  - TASK-6.3
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

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 isj_agent/run_output.py defines the run-directory layout and a writer (write_run) that, given an Intents, the per-intent results, AND the cp->docno map (the TASK-6.3 isj_agent.docno_map reader, opened read-only), writes <outdir>/intents.json plus intent-NN.json and intent-NN.trace.jsonl as specified.
- [x] #2 intents.json is Intents.model_dump_json(indent=2); each intent-NN.json is the RankedList for interpretations[NN] (model_dump_json indent=2); NN is zero-based, zero-padded (>=2 digits), and matches the interpretation index.
- [x] #3 intent-NN.trace.jsonl is the per-intent event trace serialized as JSON Lines — one TraceEvent JSON object per line (event.model_dump_json() per line); an empty event list writes an empty file.
- [x] #4 The writer creates the output directory and refuses to overwrite a non-empty existing directory unless overwrite=True.
- [x] #5 C2 reads the cp->docno SQLite map (read-only, the TASK-6.3 reader) and rewrites cp->docno on the way out; it is otherwise pure -- no network, no LLM, no Searcher logic, no trace generation.
- [x] #6 Tests (no network) write a run to a temp dir and assert: intents.json round-trips to the Intents; each intent-NN.json round-trips to its RankedList; intent-NN.trace.jsonl has one JSON object per line that round-trips to a TraceEvent and preserves order; file count and NN padding are correct; the count-mismatch and overwrite guards work.
- [x] #7 uv run --directory isj pytest tests/ exits 0; isj/README.md documents the run-output directory layout and that intent-NN.trace.jsonl is a JSON-Lines event log (a research artifact).
- [x] #8 write_run takes one outcome per interpretation, in order (len(outcomes) == len(intents.interpretations)); each is a success (IntentResult) or a failure (RunError); a count mismatch raises.
- [x] #9 errors.log is written IFF at least one outcome is a failure (or a run-level error is passed): it contains the error messages, each tagged with the failing intent's index (and interpretation) where intent-specific. Its ABSENCE means every intent completed successfully; a failed intent has no intent-NN.json/.trace.jsonl and appears only in errors.log.
- [x] #10 Before persisting, C2 rewrites every cp to its docno via the TASK-6.3 reader -- in BOTH the RankedList (RankedEntry.cp) AND the trace events (the returned/judged/excluded cps) -- so the written intent-NN.json and intent-NN.trace.jsonl carry docnos, never raw cps; a docno-less corpus (no map) persists cps.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DECISIONS (user): (1) persisted id field RENAMED to 'docno' when a map is present (docno-less corpus keeps 'cp'); (2) full cp->docno consistency -- small B2 amendment so the judge_before_search bounce carries pending cps STRUCTURALLY (so C2 rewrites them; the bounce message no longer embeds raw cps; the LLM tool result still carries cps as it is not persisted). RECONCILIATIONS: write_run takes the DocnoMap (embedded signature was stale); rewrite is dict-level (RankedEntry.cp is a typed int); AC#6 round-trip-to-RankedList superseded by AC#10's docno rewrite (persisted-file test validates the docno form; in-memory RankedList still round-trips in B2 tests).

B2 amendment (isj_agent/agents/searcher.py): judge_before_search bounce -> emit cps=[h.cp for h in pending] + message='search refused: judge the surfaced passages first' (no embedded cps); tool result to the LLM keeps cps. Add a B2 test assertion that the bounce event carries structured cps; re-run B2 tests.

C2 (isj_agent/run_output.py):
- Types IntentResult{ranked_list:RankedList, events:list[TraceEvent]}, RunError{message:str}.
- write_run(out_dir, intents, outcomes, *, docno_map:DocnoMap|None=None, run_error:str|None=None, overwrite:bool=False): guard len(outcomes)==len(intents.interpretations) (else raise); create out_dir, refuse non-empty unless overwrite; intents.json=Intents.model_dump_json(indent=2); per success i: intent-{i:02d}.json = RankedList dumped to dict, cp->docno rewritten, json.dumps(indent=2); intent-{i:02d}.trace.jsonl = each event dumped, cp fields rewritten, one json line. errors.log IFF any RunError outcome or run_error (entries tagged 'intent NN (<interp>): <msg>'); absence => all succeeded; a failed intent gets no .json/.trace.jsonl.
- cp->docno rewrite (map present; batched via DocnoMap.docnos(); unmapped cp -> fallback to cp): scalar 'cp' key -> 'docno' in RankedEntry, search.results[], judge.judgements[]; list values -> docnos in search.exclude and bounce.cps (field names kept). docno_map=None -> no rewrite (cps persisted, AC#10).
- Pure filesystem; UTF-8; pydantic-stable order.

tests/test_run_output.py (no network): all-success (no errors.log; intents round-trip; intent-NN.json carries docno not cp; trace.jsonl one-event/line + order + cp fields are docnos); one-RunError (failed intent no files, others present, errors.log w/ index+message); count-mismatch raises; overwrite guard; docno-less (docno_map=None -> cps persisted).
README: run-output layout + 'docno on disk' + 'absence of errors.log => whole run succeeded'.
GATE: uv sync + uv run pytest green (B2 + C2).
FORWARD-COMPAT: C3 (5.9) opens DocnoMap(burrow/docno-cp.sqlite) read-only and calls write_run with the per-interpretation outcomes (IntentResult/RunError) it produces + catches.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). SUPERSEDES the prior note. CHANGE: C2 now performs the cp->docno REWRITE at write time -- it maps each persisted result/trace cp to its docno via the TASK-6.3 SQLite reader, so the saved files carry docno (portable), never a raw cp. Results are cp in memory; docno on disk. (A docno-less corpus persists cp.) The intents + per-intent RankedList + trace.jsonl + errors.log layout is unchanged. Authoritative: doc-6 + TASK-6.3.

Implemented per the (reconciled) plan + user decisions. isj_agent/run_output.py: RunError{message}; the SUCCESS outcome is reused as SearcherResult (identical to the spec's IntentResult -- avoided a duplicate type); write_run(out_dir, intents, outcomes, *, docno_map=None, run_error=None, overwrite=False) -- count guard, non-empty-dir guard + stale-managed-file cleanup on overwrite, intents.json, per success intent-NN.json + intent-NN.trace.jsonl (one event/line), errors.log iff any RunError outcome or run_error (tagged 'intent NN (<interp>): <msg>'). cp->docno REWRITE at write time via the read-only DocnoMap (TASK-6.3, cached): scalar 'cp' key RENAMED to 'docno' in RankedEntry/search.results[]/judge.judgements[]; list values mapped to docnos in search.exclude and bounce.cps; docno_map=None -> cps persisted (docno-less corpus). B2 amendment (consistency decision): the judge_before_search bounce now carries pending cps in a STRUCTURED cps field + a cp-free message (so C2 rewrites them; the LLM tool result still carries cps as it is not persisted) + a new B2 test assertion. AC#6 NOTE: the persisted intent-NN.json carries docnos (AC#10), so it is not a cp-typed RankedList; the test validates the docno form + intents.json<->Intents round-trip + trace one-event/line+order (the in-memory RankedList still round-trips in B2). README documents the layout. VERIFIED: uv sync + uv run pytest -> 55 passed, 1 skipped (live); 7 new C2 tests.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
C2 ships the run-output writer: write_run persists one question's run to <out_dir>/ -- intents.json + per-succeeded-intent intent-NN.json (RankedList) and intent-NN.trace.jsonl (JSON-Lines event trace) + errors.log iff something failed (absence => all succeeded). It rewrites every persisted cp -> docno via the read-only TASK-6.3 DocnoMap (RankedList + trace events; field renamed cp->docno), so saved files are portable; a docno-less corpus persists cps. Pure filesystem. Included a small B2 amendment so the bounce carries pending cps structurally (full cp->docno consistency). Verified by 7 new tests (uv pytest green, no network).
<!-- SECTION:FINAL_SUMMARY:END -->
