---
id: TASK-27
title: >-
  Judger resilience: retry failed judge calls, then record grade -2 instead of
  aborting the intent
status: Done
assignee:
  - '@claude'
created_date: '2026-07-03 12:59'
updated_date: '2026-07-03 15:07'
labels: []
dependencies: []
priority: high
ordinal: 41000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Today ONE failed judge call (LLM/transport error OR a completion that fails Verdict validation, e.g. an empty response) raises _JudgeFailure and ABORTS the whole intent with a partial result (isj/isj_agent/controller.py:207). Seen live in the TASK-22 A/B: cover/reading died because a single vLLM call returned an empty completion. A transient hiccup must not kill an intent.

Design (Mark, 2026-07-04):
1. RETRY: a failed judge call is retried (fresh LLM call) up to 2 more times; overwhelmingly these are transient.
2. RECORD, don't abort: if a doc still has no valid verdict after retries, it goes into the ranked list like any other doc but with grade = -2 (error sentinel) and reason "Judger agent failed to assess the relevance." Its cp enters the judged set (never re-surfaced or re-judged), it consumes judgment budget like any recorded doc, and the Searcher sees the -2 outcome in its feedback like any other judgment.
3. Streak: a -2 does NOT advance the non-relevant streak (it is evidence of an error, not of irrelevance) — flagged for review, adjust if Mark prefers otherwise.
4. SYSTEMIC GUARD: if an ENTIRE wave of judge calls fails (all of them, after retries), keep today's abort — that is an outage, not a hiccup.

Implementation notes: Verdict.grade currently validates 0-3 (guided decoding + pydantic) — the -2 sentinel is constructed controller-side, NOT parsed from the model, so the wire schema stays 0-3; widen only the internal/RankedEntry type as needed. Trace: emit a judge_failed event carrying the final error and retry count per the heavy-trace rule; each retry's llm_call is traced too. Downstream: run-output writer and any grade consumers must tolerate -2 (relevant_grade_threshold logic unaffected: -2 < 1); note it in isj/README's Judger section.

Tests: (a) transient failure then success -> normal verdict, retries visible in trace; (b) permanent failure on one doc -> grade -2 entry with the exact reason string, run completes, cp excluded from re-surfacing; (c) full-wave failure -> intent aborts as today; (d) -2 does not advance the streak; full isj suite green.

Fold into the current branch claude/ssr-parallel-etc (per the standing branch decision). Independent of TASK-22 but gates the A/B rerun.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A judge call that errors or fails Verdict validation is retried up to 2 more times; a retry success produces a normal verdict and the retries are visible in the trace
- [x] #2 After exhausted retries the doc is RECORDED in the ranked list with grade -2 and reason exactly 'Judger agent failed to assess the relevance.', consumes budget, enters the judged/exclude set, and is fed back to the Searcher like any judgment
- [x] #3 A -2 entry does not advance the non-relevant streak, and downstream consumers (run-output writer, summaries) handle -2 without error
- [x] #4 A fully-failed wave (every call in the wave failed after retries) still aborts the intent with today's partial-result behavior
- [x] #5 Unit tests cover retry-success, permanent-failure -> -2, full-wave abort, and streak behavior; the full isj pytest suite passes
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Setup
   1.1 Mark TASK-27 In Progress. Current branch claude/ssr-parallel-etc (standing decision).

2. Judger retry (isj/isj_agent/agents/judger.py)
   2.1 JudgeCall gains `retries: int = 0` (attempts beyond the first) — dataclass default keeps existing constructors/tests valid.
   2.2 _judge_one becomes the single-attempt body; a new wrapper loops up to 3 attempts total (initial + 2 retries), re-calling on `error is not None or verdict is None`. Each attempt is a FRESH chat.completions call. The returned JudgeCall is the FINAL attempt's (content/reasoning/usage/duration of that attempt) with `retries` set; prior attempts' errors are summarized into `error` history only if the final attempt ALSO failed (e.g. "attempt 1: ...; attempt 2: ...; attempt 3: ...").
   2.3 No Judger-side aborting or sentinel logic — the Judger keeps surfacing failure as data (its existing contract); policy lives in the controller.

3. Controller policy (isj/isj_agent/controller.py)
   3.1 Module-level sentinel: FAILED_GRADE = -2, FAILED_REASON = "Judger agent failed to assess the relevance."; failed_verdict = Verdict.model_construct(reason=FAILED_REASON, grade=FAILED_GRADE). model_construct BYPASSES pydantic validation, so Verdict's wire schema (Verdict.model_json_schema(), fed verbatim to guided decoding) stays 0-3 — the model never sees -2.
   3.2 Replace the `raise _JudgeFailure` at the per-doc site: on `c.error or c.verdict is None` after retries, emit a `judge_failed` trace event (cp, retries, final error — heavy-trace rule; each attempt's usage is already inside the final llm_call event), use the sentinel verdict, and fall through the NORMAL recording path: judged[cp] = sentinel, RankedEntry(grade=-2, reason=FAILED_REASON, ...), fresh.append -> the Searcher sees the -2 outcome, budget consumed, cp excluded.
   3.3 Streak: -2 does NOT advance the non-relevant streak and does not reset it — add a third arm to the relevant/streak branch (grade < 0 -> no-op). (Flagged in the task description for Mark's review.)
   3.4 Systemic guard: in each judged wave, if EVERY JudgeCall in the wave failed (all carry error/None verdicts after retries), raise _JudgeFailure as today (message notes wave size). _JudgeFailure and the run_error path stay for exactly this case.
   3.5 The `llm_call` judge trace event gains `retries=c.retries`.

4. Downstream tolerance
   4.1 protocol/results.py RankedEntry.grade: confirm plain int (no ge=0); widen only if constrained.
   4.2 run_output writer + cover_results/json paths: confirm -2 passes through (they render grades verbatim); relevant_grade_threshold comparisons are >=, so -2 is simply non-relevant everywhere.
   4.3 scouting/searcher-ab/summarize.py: -2 lands in `judged` but no g1/g2/g3 bucket (already true: g>=1 checks).
   4.4 isj/README.md Judger section: one paragraph on retry + the -2 sentinel.

5. Tests (isj/tests)
   5.1 test_judger.py: a stub client failing once then succeeding -> verdict OK, retries==1; failing 3x -> JudgeCall.error aggregates attempts, verdict None, retries==2.
   5.2 test_controller.py: (a) FakeJudger permanent-fail on ONE doc of a wave -> run completes, that cp appears in the ranked list with grade -2 and the EXACT reason string, cp in exclude for the next query, Searcher's tool result carries the -2; (b) streak: a -2 between two non-relevant docs does not advance/reset the streak (assert stop turn unchanged vs a control); (c) full-wave failure -> intent aborts with partial result exactly as today.
   5.3 Full suite: uv run pytest; bazel //test:all untouched (no C++ change).

6. Finalize
   6.1 Task notes; check ACs; commit on the current branch; push (rides PR #9). Report; the A/B rerun decision stays with Mark (phrase pathology is the other blocker).
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented on claude/ssr-parallel-etc. Judger: up to 2 retries per failed call (fresh completions), retries recorded, errors aggregated across attempts. Controller: still-failed docs are recorded with the grade -2 sentinel and reason 'Judger agent failed to assess the relevance.' via Verdict.model_construct (wire schema untouched at 0-3), consume budget, enter judged/exclude, reach the Searcher; judge_failed trace event; -2 is streak-neutral; only a fully-failed wave aborts. RankedEntry.grade widened internally to include -2. isj suite 138 passed / 1 skipped incl. new tests for every AC. README Judger section documents the policy.
<!-- SECTION:FINAL_SUMMARY:END -->
