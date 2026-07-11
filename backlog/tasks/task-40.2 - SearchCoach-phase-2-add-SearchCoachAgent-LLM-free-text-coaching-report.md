---
id: TASK-40.2
title: 'SearchCoach phase 2: add SearchCoachAgent (LLM free-text coaching report)'
status: To Do
assignee: []
created_date: '2026-07-11 21:30'
updated_date: '2026-07-11 21:50'
labels: []
dependencies:
  - TASK-40.1
parent_task_id: TASK-40
ordinal: 56000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add SearchCoachAgent: an LLM agent (client+model+prompt+temp 0 + TASK-37 caps) that writes the v6 free-text coaching report (What's working / hurting / pursue next + verbatim Cited passages). Query-blind and atom-blind context (need + stats + top-25-by-rank + deep high-grade nuggets). No response_format (free text). Tolerant [R#] citation extraction (bracketed OR bare, validated against the input handle set) for logging only -- the report is self-contained. Controller falls back to MechanicalSearchCoach on any coach failure. Trace events purpose=coach and coach_fallback. Config-selected in [coach]. Prompt seeded from isj/scouting/search-coach/prompt-v6.md. See docs/design/search-coach.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 SearchCoachAgent produces the v6 free-text report; config [coach] class selects it; the Searcher receives query echo + stats + atom counts (Cottontail only) + the coach report.
- [ ] #2 On any coach error/timeout the Controller falls back to MechanicalSearchCoach (run never fails); a coach_fallback trace event records it.
- [ ] #3 Citation extraction is tolerant (bracketed or bare handles, validated) and used only for logging referenced docs; a report with no parseable citations is not treated as a failure.
- [ ] #4 The coach LLM call appears as a purpose=coach trace event; tests cover the agent, the fallback, and tolerant extraction; the isj suite passes.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Add the LLM coach behind the phase-1 protocol.

1. SearchCoachAgent in isj_agent/agents/search_coach.py (LLM agent like Judger): __init__(client, model, *, prompt:str|Path|None=None, reasoning_effort='medium', temperature=0.0, max_tokens=8000, timeout_s=120, input_top_k=25, input_min_grade=3). Bundled prompt search_coach.md seeded from isj/scouting/search-coach/prompt-v6.md (What's working / hurting / pursue next + verbatim '## Cited passages').
   coach(ctx): sel = select(ctx.results, input_top_k, input_min_grade); build the passages block with handles R1..Rn (grade, reason, summary excerpt); chat.completions.create WITHOUT response_format (free text) + temp 0 + TASK-37 caps; report = message.content; referenced = tolerant [R#] extraction (regex R\\d+ bracketed OR bare, dedup, keep only handles present in R1..Rn, map to docnos). A report with no parseable citations is NOT a failure.

2. Controller: add a `mechanical` fallback (built from [coach.mechanical]); wrap the coach call try/except -> mechanical + emit coach_fallback trace event. Emit the coach LLM call as a trace event purpose='coach' (with a pre-call await marker for TASK-35 live visibility), carrying usage + referenced.

3. searcher.md: already agnostic from phase 1; verify it reads the markdown report; at most a one-line mention it may be a coach report.

4. Config: [coach].class = SearchCoachAgent selects the LLM coach; build_coach builds it (client/model from [coach].llm) + the mechanical fallback; document in config.example (temp 0 + TASK-37 caps + input_top_k/input_min_grade).

5. Tests: agent returns a report (stub client); fallback fires on a raising client -> mechanical + coach_fallback; tolerant extraction (bracketed + bare, drops non-handles, empty on no citations); purpose='coach' trace present; full isj suite green. Optional live e2e over a burrow + vLLM.

FORWARD-COMPAT (phase 3): the report is the tool-message content -- keep the '## Cited passages' header (v6 does) so phase-3 compaction can structurally drop that section (else it hard-truncates). (phase 4): coach-on=SearchCoachAgent, coach-off=MechanicalSearchCoach -- both exist after this phase.
<!-- SECTION:PLAN:END -->
