---
id: TASK-40.2
title: 'SearchCoach phase 2: add SearchCoachAgent (LLM free-text coaching report)'
status: To Do
assignee: []
created_date: '2026-07-11 21:30'
updated_date: '2026-07-11 23:42'
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
GOAL: add SearchCoachAgent (the LLM coach) behind the phase-1 SearchCoach protocol, with a mechanical fallback and coach traces. Design: docs/design/search-coach.md ("The coach output", "Implementations", "Observability", "Resilience"). DEPENDS ON 40.1 (SearchCoach protocol, CoachContext/CoachOutput, select(), MechanicalSearchCoach must exist).

READ FIRST:
- isj/isj_agent/agents/judger.py -- MIRROR this LLM-agent pattern. Judger.__init__(client, model, *, reasoning_effort="medium", temperature=0.0, max_tokens=8000, timeout_s=120). Judger._attempt builds `messages`, `extra={"reasoning_effort":...}`, `bound` (max_tokens/timeout, TASK-37), then self.client.chat.completions.create(model, messages, response_format=..., temperature, extra_body=extra, **bound); reads resp.choices[0].message.content, message.reasoning_content, resp.usage. Bundled prompt via importlib.resources.files("isj_agent.agents").joinpath("judger.md").read_text().
- isj/scouting/search-coach/prompt-v6.md -- the CHOSEN coach prompt (copy verbatim to the bundled search_coach.md). It uses {intent} and {passages} placeholders (filled with str.format in the scout; use str.replace to avoid brace issues if the prompt ever gains literal braces).
- isj/scouting/search-coach/run.py _cited() -- the citation extractor to adapt (make it TOLERANT: bracketed [R3] OR bare/bold R3, validated against the input handles).
- isj/isj_agent/controller.py run() (add the coach try/except fallback + the purpose="coach" trace, near the coach call added in 40.1) and its emit()/mark() helpers (TASK-35).
- isj/isj_agent/config.py build_coach (extend the 40.1 dispatch) and cli.py.

STEPS:
1. Bundled prompt: copy isj/scouting/search-coach/prompt-v6.md -> isj/isj_agent/agents/search_coach.md.
2. SearchCoachAgent in isj_agent/agents/search_coach.py: __init__(self, client, model, *, prompt:str|Path|None=None, reasoning_effort="medium", temperature=0.0, max_tokens=8000, timeout_s=120, input_top_k=25, input_min_grade=3). Load the bundled search_coach.md (importlib.resources) unless `prompt` overrides (like Searcher's directable prompt).
   coach(ctx)->CoachOutput:
   - sel = select(ctx.results, self.input_top_k, self.input_min_grade)  (reuse the 40.1 helper)
   - handles = {f"R{i+1}": d for i,d in enumerate(sel)}
   - passages = "\n".join(f"[{h}] grade={d['grade']}\n  reason: {d['reason']}\n  summary: {d['summary']}" for h,d in handles.items())
   - messages=[{"role":"user","content": self.prompt.replace("{intent}",ctx.intent).replace("{passages}",passages)}]
   - extra = {"reasoning_effort": self.reasoning_effort} if set; bound = max_tokens/timeout (copy judger's pattern). resp = self.client.chat.completions.create(model=self.model, messages=messages, temperature=self.temperature, extra_body=extra, **bound)  -- NO response_format (free text).
   - report = resp.choices[0].message.content; reasoning = getattr(message,"reasoning_content",None); usage = resp.usage (as a dict).
   - referenced = tolerant extraction over `report`: regex r"(?<![A-Za-z0-9])R\d+(?![A-Za-z0-9])" (matches [R3], **R3**, bare R3), first-mention dedup, keep only ones in `handles`, map to handles[h]["id"]. Empty is fine (NOT a failure).
   - return CoachOutput(report=report, referenced=referenced) with usage+reasoning carried (extend CoachOutput with optional usage:dict={} and reasoning:str|None=None; MechanicalSearchCoach leaves them default).
   - If create() raises: let it propagate (Controller catches -> fallback). Do NOT swallow.
3. Controller:
   - __init__: ADD mechanical:SearchCoach (the always-works fallback). Keep coach.
   - At the coach call (added in 40.1): mark("await_coach"); t0=time.time(); try: out=self.coach.coach(ctx) except Exception as exc: emit("coach_fallback", time.time(), 0.0, error=f"{type(exc).__name__}: {exc}"); out=self.mechanical.coach(ctx) else: emit("llm_call", t0, (time.time()-t0)*1000, purpose="coach", referenced=out.referenced, content=out.reasoning, **(out.usage or {})). Then compose + _tool as in 40.1.
4. searcher.md: already agnostic (40.1); no change needed (optionally one line noting the summary may be a coach report).
5. Config + cli:
   - config.py build_coach: add branch `if cls is SearchCoachAgent:` -> build it with client=clients[[coach].llm] + model=llm_configs[[coach].llm]["model"] + reasoning_effort/temperature/max_tokens/timeout_s/input_top_k/input_min_grade from [coach]. ALWAYS also build the mechanical fallback from [coach.mechanical]. build_coach returns (coach, mechanical) (or the Controller builds mechanical from a passed config). cli.py: coach, mechanical = build_coach(config); Controller(..., coach=coach, mechanical=mechanical).
   - config.example.toml [coach]: class = isj_agent.agents.search_coach.SearchCoachAgent; llm = "default"; reasoning_effort/temperature (0.0)/max_tokens/timeout_s (TASK-37); input_top_k=25; input_min_grade=3. Keep [coach.mechanical] as the fallback config.
6. Tests: tests/test_search_coach.py -- StubClient (copy test_judger.py StubClient: .calls capture, .chat.completions.create returns a canned SimpleNamespace with choices[0].message.content + usage). Assert: (a) coach() returns the report + tolerant referenced (test [R3] AND **R5** AND bare R7 all extracted; a cited handle not in the input is dropped; no citations -> referenced==[]); (b) Controller falls back to mechanical when coach.coach raises -> a coach_fallback trace event + the mechanical feedback reaches the StubSearcher; (c) a purpose="coach" llm_call trace event carries referenced. Full isj suite green. Optional live e2e: run isj_agent.cli over a small burrow + vLLM with [coach].class=SearchCoachAgent, confirm the coach report reaches the searcher and the run finishes (traceview --purpose coach).

GOTCHAS/DECISIONS: FREE TEXT -- do NOT pass response_format (guided JSON failed; see design "The coach output"). temp 0 + TASK-37 caps (mirror judger, and the caps let a runaway coach time out into the fallback). Tolerant citation regex (bracketed OR bare) validated against handles; a no-citation report is self-contained, not a failure. The mechanical fallback must ALWAYS be constructed (never None).

FORWARD-COMPAT (phase 3 compaction): the coach report is the tool-message content -- prompt-v6 emits a "## Cited passages" section; keep that header so phase-3 compaction can drop that section (else it hard-truncates). (phase 4): coach-off is just [coach].class = MechanicalSearchCoach.
<!-- SECTION:PLAN:END -->
