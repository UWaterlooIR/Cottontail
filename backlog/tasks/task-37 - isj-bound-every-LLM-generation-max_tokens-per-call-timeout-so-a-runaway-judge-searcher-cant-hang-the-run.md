---
id: TASK-37
title: >-
  isj: bound every LLM generation (max_tokens + per-call timeout) so a runaway
  judge/searcher can't hang the run
status: Done
assignee:
  - '@claude'
created_date: '2026-07-10 18:01'
updated_date: '2026-07-10 18:06'
labels: []
dependencies: []
ordinal: 51000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A judge call that falls into gpt-oss-120b's reasoning-loop pathology spews tokens unbounded and HANGS the whole run: guided decoding constrains only the final JSON channel, not the reasoning channel, so the model generates until it fills context or hits the openai client's 600s DEFAULT timeout -- and with RETRIES=2 that is up to ~30 min on one doc. Worse, Judger.judge() does pool.map(), a BARRIER: the controller blocks on the entire wave (concurrency, e.g. 25) until the straggler returns, so one looping doc freezes everything. build_client() sets no timeout and none of the three agents (Analyst/Searcher/Judger) pass max_tokens; the [agents.*] LLM calls are entirely unbounded. Observed live: a cover query judged 24 docs and one judge call sat spewing tokens with the run hung. Fix: bound EVERY LLM generation with a token cap and a per-call timeout, configurable, defaulting ON. A capped/timed-out judge fails its parse -> existing TASK-27 retry -> grade -2 sentinel -> the run continues; a capped searcher truncation -> no valid tool call -> the existing no_query bounce. Relevant code: isj/isj_agent/agents/{judger.py,searcher.py,analyst.py} (each calls self.client.chat.completions.create with no max_tokens/timeout), isj/isj_agent/config.py build_client, cli.py _build_agent wiring, config.example.toml.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The Judger, Searcher, and Analyst each accept a max_tokens (token cap) and timeout_s (per-call timeout) and pass them to chat.completions.create; both default to sane bounded values so protection is ON without any config.
- [x] #2 A judge call that hits the token cap or the timeout fails cleanly and flows through the existing retry -> grade -2 path (does not abort the wave); the run continues past the offending doc.
- [x] #3 max_tokens and timeout_s are configurable per agent via [agents.<role>] and documented in config.example.toml; omitting them uses the bounded defaults.
- [x] #4 Tests verify each agent forwards max_tokens and timeout to the client call and that the defaults are set; the existing isj suite passes.
- [x] #5 A capped/timed-out searcher generation degrades gracefully (incomplete tool call -> the controller's existing no_query bounce), not a crash.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Implemented on the claude/task-36-searcher-feedback branch (owner asked to do the fixes here; the branch PR covers TASK-36 + TASK-37).

1. Judger (judger.py): add max_tokens: int|None = 8000 and timeout_s: float|None = 120.0 to __init__; in _attempt, pass max_tokens + timeout to chat.completions.create (only when not None). A cap/timeout -> empty/partial content -> Verdict parse fails -> existing retry -> grade -2 (TASK-27). Defaults chosen: normal medium-effort judge completions ran ~400-900 tokens live, so 8000 is ~10x headroom; a runaway goes 50k+.

2. Searcher (searcher.py): add max_tokens: int|None = 16000 and timeout_s: float|None = 180.0; pass to create() in propose(). A cap -> finish_reason length / incomplete tool call -> pr.queryable None -> the controller's existing no_query bounce (graceful). Normal searcher completions ran ~1300-2200 live, so 16000 is ~7x headroom.

3. Analyst (analyst.py): add max_tokens: int|None = 8000 and timeout_s: float|None = 120.0; pass to create() in analyze(). (One call per run, but same pathology -> bound it.)

4. cli.py _build_agent: forward max_tokens + timeout_s from [agents.<role>] for all three agents (add to the per-role key lists).

5. config.example.toml: document max_tokens + timeout_s under [agents.analyst/searcher/judger] with the defaults and the rationale (bounded by default; a runaway can't hang the wave).

6. Tests: a fake client capturing create() kwargs asserts each agent forwards max_tokens + timeout; assert the defaults are set on each agent. Full isj suite green.

Note: build_client stays timeout-less at the CLIENT level; the bound is applied PER CALL (per-agent, configurable) which is finer-grained and lets a judge cap differ from a searcher cap.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented on claude/task-36-searcher-feedback. Added max_tokens + timeout_s to Judger (8000/120), Searcher (16000/180), Analyst (8000/120); each builds a  kwargs dict (omitted when None) passed to chat.completions.create. Wired all three from [agents.<role>] in cli.py; documented under each agent in config.example.toml (with a shared header explaining the bound-by-default rationale). A capped/timed-out judge -> no valid Verdict -> existing retry -> grade -2 (TASK-27); a capped searcher -> incomplete tool call -> existing no_query bounce. Tests: 6 new (each agent forwards max_tokens+timeout, defaults set, judger omits when None); full suite 187 passed/1 skipped. Live check against the real vLLM: caps accepted (no 400), a normal judge returned grade 2 in 396 completion tokens / 2.4s -- ~20x under the 8000 cap, so normal judging is not truncated.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Every ISJ LLM call (Analyst/Searcher/Judger) is now bounded by a max_tokens cap and a per-call timeout, ON by default and configurable per [agents.<role>]. Fixes the hang where a gpt-oss-120b judge falling into a reasoning loop spewed tokens unbounded (guided decoding constrains only the final channel) and froze the whole run -- the judge wave is a barrier, so one runaway blocked everything, up to ~30 min (600s client default x retries). Now a runaway is cut off: a judge -> parse fail -> retry -> grade -2 -> run continues; a searcher -> no_query bounce. Defaults: judger/analyst 8000 tok / 120 s, searcher 16000 tok / 180 s. Verified: 187 tests pass; live vLLM check shows caps accepted and a normal judge uses ~400 tokens (well under the cap).
<!-- SECTION:FINAL_SUMMARY:END -->
