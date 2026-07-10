---
id: TASK-35
title: >-
  isj: live-stream Searcher activity during a run (observable per-event
  progress)
status: Done
assignee:
  - '@claude'
created_date: '2026-07-10 15:46'
updated_date: '2026-07-10 16:53'
labels: []
dependencies: []
ordinal: 49000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The ISJ agent surfaces activity only at INTENT granularity and persists the run directory only ONCE, at the very end: cli.py runs orchestrator.run_question() to completion, then calls write_run() a single time. Inside the Controller, emit() (controller.py) merely appends each TraceEvent to a local list that is returned in the SearcherResult when the intent finishes; nothing observes events as they are produced. Consequences: (1) within an intent there is NO visible progress, so a hung search, a stalled LLM call, or a model stuck in a pathological reasoning loop (the documented gpt-oss-120b failure mode) is invisible until -- if ever -- the intent returns; (2) with --verbose the CLI renders a whole intent's trace in one burst only after that intent completes; (3) a killed / timed-out run persists NOTHING (no partial run dir), losing all work. This makes long unattended batches (e.g. the 22 TREC-RAG dev-topic x 2-config runs) unsafe to watch or interrupt. Goal: add a live, near-real-time stream of activity so an operator can watch a run in flight, detect a stall or runaway LLM quickly, and recover partial work from a killed run. Streaming must be ADDITIVE -- the final run-output shape and content for a successful run stay byte-for-byte as today. Relevant files: isj/isj_agent/controller.py (emit/run/_descend), isj/isj_agent/orchestrator.py (on_intent), isj/isj_agent/cli.py (_render_event/_make_on_intent, write_run call), isj/isj_agent/run_output.py. See also TASK-11 (trace content/persist-on-failure) and TASK-8 (query in/out logging) for the existing trace design this extends.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The Controller invokes an optional event-observer callback the moment each TraceEvent is emitted (across run() and _descend()), while still returning the full events list in SearcherResult for run-output writing; when no observer is supplied, behavior is unchanged.
- [x] #2 A start marker is observable BEFORE each long LLM call (searcher turn and each judge call) so a stalled/hung call shows as activity that STARTED but has not completed -- the live stream's last line is an 'awaiting LLM' marker with a timestamp, not silence.
- [x] #3 With --verbose, the CLI renders events live and per-event as they occur (each line timestamped), streaming across all intents, instead of one burst per intent at intent completion.
- [x] #4 Activity is observable ON DISK during the run: trace events are appended incrementally as they occur (per-intent .trace.jsonl or a run-level live log), so a killed/timed-out run leaves a partial, inspectable trace rather than an empty directory.
- [x] #5 For a successful run, the final run-output directory (intents.json, intent-NN.json, intent-NN.trace.jsonl, errors.log semantics) is unchanged in shape and content from today; streaming is purely additive with no regression.
- [x] #6 Tests cover the observer firing in emission order and the pre-LLM-call start marker; the existing isj test suite passes.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Tier 1 (per owner decision 2026-07-10: observability + hang detection now; live LLM-token streaming deferred to a follow-up task).

1. Controller observer hook. Add an optional on_event callback to Controller (constructor-injected, default None). emit() appends to the events list AS TODAY and, if on_event is set, calls on_event(event) immediately. Thread the same emit through run() and _descend() (already passed as a param). No observer => byte-identical behavior. (AC1)

2. Live-only pre-call markers. Before each long LLM call -- the searcher turn (controller.run, before propose) and each judge call (controller._descend / judger wave) -- surface an 'awaiting' signal to the observer WITHOUT appending it to events, so the persisted trace stays byte-identical (AC5). Represent as a lightweight live signal object distinct from TraceEvent (e.g. on_event receives either a TraceEvent or a LiveMarker; renderer/logger handle both; only TraceEvents are persisted). Markers: 'awaiting searcher turn N', 'awaiting J judge calls'. (AC2)

3. Incremental on-disk trace. Refactor run_output so a run dir can be opened and appended to as events arrive: write intents.json right after analysis; open intent-NN.trace.jsonl and append each event line as emitted; write intent-NN.json (RankedList) when the intent completes. On success the files are identical to today's single-shot write; on a kill, finished intents are complete and the in-flight intent has a partial trace. errors.log semantics unchanged (absence == success). Provide a RunWriter/streaming-writer that the CLI drives via the observer; keep write_run() (or a thin equivalent) so non-streaming callers/tests still work. (AC4, AC5)

4. Live --verbose in the CLI. Wire the Controller's on_event to a live renderer that prints each event/marker as it arrives, timestamped (HH:MM:SS), streaming across all intents -- replacing the current post-intent burst in _make_on_intent/_render_event. Keep a concise non-verbose path (final summary line only). The incremental RunWriter (step 3) is wired regardless of --verbose. (AC3)

5. Tests. Unit-test that (a) the observer fires once per emitted event in emission order, (b) a pre-call marker is delivered before the corresponding llm_call event and is NOT present in the persisted trace, (c) the incrementally-written intent-NN.trace.jsonl after a completed run equals the current one-shot output, (d) a simulated mid-intent abort leaves a partial trace + intents.json on disk. Run the full isj suite (uv run --directory isj pytest). (AC6)

Non-goals: LLM token streaming (stream=True) -- deferred. No change to trace event CONTENT/shape, engine, or agents' prompts.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented Tier 1 + a run-level activity.log (owner add mid-task: 'produce an activity log in the out directory; create the dir if missing').

Changes:
- protocol/results.py: new LiveMarker (live-only, never persisted).
- controller.py: run() gains observer callback; emit() delivers each TraceEvent live; new mark() emits live-only 'await_searcher_turn' (before the searcher LLM call) and 'await_judge' (before each judge wave). No observer => byte-identical behavior.
- orchestrator.py: run_question() gains observer + on_analyzed callbacks; wraps a per-intent observer(i, ev).
- run_output.py: new StreamingRunWriter -- creates the out dir if missing; writes intents.json up front; streams a human-readable activity.log (all events + markers, across intents, flushed per line -- the tail -f target); appends intent-NN.trace.jsonl per event (persisted TraceEvents only); writes intent-NN.json at intent end and errors.log at finish. write_run kept for non-streaming callers/tests. Shared _activity_lines() renderer; echo=verbose mirrors to stdout.
- cli.py: drops the post-intent burst; drives StreamingRunWriter (on_analyzed=start, observer=observe, on_intent=finish_intent, then finish). Opens the run dir up front (fail-fast if non-empty and not --overwrite).

Tests (6 new, full suite 176 passed/1 skipped): observer streams events in order + markers precede LLM calls + markers not persisted; no-observer unchanged; StreamingRunWriter byte-for-byte == write_run; out dir created if missing; markers in activity.log not trace; partial (killed) run leaves intents.json + partial activity.log + flushed trace.

Live e2e over the 8-shard array + vLLM (config-gcl-cover): activity.log streamed the awaiting-LLM marker, the proposed cover query, a 26s search (total=11537), 'awaiting 25 judge call(s)', then per-doc grades with real shard_NNNNN_RRRR docnos. Killed mid-wave: partial activity.log (no DONE line) + 104-line flushed trace + intents.json survived; no errors.log. Confirms AC2/AC3/AC4.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added live, incremental observability to the ISJ Searcher run (Tier 1). The Controller now delivers each TraceEvent to an optional observer the moment it is emitted, plus live-only pre-call markers (await_searcher_turn / await_judge) so a hung/stalled LLM shows as a started-but-unfinished signal instead of silence. A new StreamingRunWriter creates the out dir if missing, writes intents.json up front, streams a human-readable activity.log (all events + markers, across intents, flushed per line -- the tail -f target), and appends intent-NN.trace.jsonl per event; the CLI drives it via the orchestrator's new on_analyzed/observer/on_intent callbacks (--verbose mirrors to stdout). A successful run's persisted output (intents.json, intent-NN.json, intent-NN.trace.jsonl, errors.log) is byte-for-byte unchanged from the old one-shot write_run; a killed run now leaves a partial, inspectable activity.log + flushed trace instead of an empty directory. Verified: 176 passed/1 skipped incl. a byte-for-byte StreamingRunWriter==write_run parity test and observer/marker/partial-run tests; live e2e over the 8-shard array + vLLM streamed the awaiting markers, a 26s search, and per-doc grades, and a mid-wave kill left partial output intact. Token streaming (watch reasoning tokens generate) deferred to a follow-up.
<!-- SECTION:FINAL_SUMMARY:END -->
