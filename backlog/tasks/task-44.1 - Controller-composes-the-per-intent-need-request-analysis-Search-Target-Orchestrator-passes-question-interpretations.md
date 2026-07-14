---
id: TASK-44.1
title: >-
  Controller composes the per-intent 'need' (request + analysis + Search
  Target); Orchestrator passes question + interpretations
status: Done
assignee: []
created_date: '2026-07-14 04:44'
updated_date: '2026-07-14 05:09'
labels:
  - isj
  - controller
dependencies: []
parent_task_id: TASK-44
ordinal: 62000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Thread the request + full analysis + target to the agents by composing a single 'need' string in the Controller. No public agent-signature changes except Controller.run. RankedList.intent stays the clean target.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A pure helper compose_need(question, interpretations, target) -> str produces a labeled string: the user's request, the full analysis (all interpretations, target marked), and 'Search Target: <target>'
- [ ] #2 Controller.run gains question + interpretations; it composes the need once and uses it for the searcher seed, judge(need, docs), and CoachContext(intent=need). Judger.judge and CoachContext signatures are unchanged
- [ ] #3 RankedList.intent (and the persisted intent-NN.json) is the CLEAN target interpretation, not the composed need
- [ ] #4 Orchestrator.run_question passes question + interpretations to controller.run; iteration and budget split are otherwise unchanged
- [ ] #5 Tests cover compose_need (contains request, all interpretations, marked target) and that the Controller feeds the need to the agents while keeping RankedList.intent clean; suite green
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
GOAL: Feed the agents the full picture WITHOUT changing Judger/Coach signatures. The CONTROLLER
composes the canonical 'need' (see TASK-44 parent -> CANONICAL need FORMAT) and substitutes it wherever
the bare intent flows today. Land this FIRST; 44.2/44.3/44.4 consume the need format defined here.

KEY CURRENT FACTS (verified against code):
- orchestrator.py run_question loops `for i, interp in enumerate(intents.interpretations):` ->
  `self.controller.run(interp, intent_budget, observer=obs)`. It already holds `intents` (question + all).
- controller.py run(self, intent, intent_budget, observer=None):
    seed msgs=[{system: searcher.system_prompt}, {user: f"Question: {intent}"}]  (line ~168-169)
    outcome = self._descend(intent, pr.queryable, ...)                            (line ~234)
    ctx = CoachContext(intent=intent, stats=..., results=...)                     (line ~259)
    ranked_list=self._compile(intent, recorded)                                   (line ~283)
- _descend(self, intent, ...) uses `intent` ONLY at `self.judger.judge(intent, docs)` (line ~344); it
  builds RankedEntry from hits, NOT from intent. So _descend can safely receive `need`.
- judger.judge(intent, docs) -> _fill replaces {intent}; CoachContext.intent -> replaces {intent} in
  search_coach.md. Both are pure string substitution: a composed need slots in with NO signature change.

STEPS:
1. NEW pure helper compose_need(question, interpretations, target) -> str, EXACTLY the parent's canonical
   format (USER REQUEST / ANALYSIS with the target's numbered item marked '<-- SEARCH TARGET' / SEARCH
   TARGET). Module-level so it is unit-testable in isolation. Location: isj_agent/need.py (new, tiny) OR
   top of controller.py; prefer isj_agent/need.py so tests import it without the Controller.
2. controller.run signature ->
     run(self, intent, intent_budget, *, question, interpretations, observer=None)
   `intent` STAYS the clean target. First line inside: need = compose_need(question, interpretations, intent).
   ROUTING (per parent CONTROLLER ROUTING CONTRACT):
     - searcher seed: {user: f\"Question: {intent}\"} -> {user: need}
     - self._descend(intent, ...) -> self._descend(need, ...)   (its intent arg only feeds judge)
     - CoachContext(intent=intent, ...) -> CoachContext(intent=need, ...)
     - self._compile(intent, recorded) UNCHANGED -> RankedList.intent = clean target
   (Optionally rename _descend's param to `need` for clarity; not required.)
3. orchestrator.run_question: pass through ->
     self.controller.run(interp, intent_budget, question=intents.question,
                         interpretations=intents.interpretations, observer=obs)
   Nothing else changes (iteration + even budget split unchanged).
4. TESTS (isj/tests/):
   - test_need.py: compose_need output contains 'USER REQUEST', 'ANALYSIS', 'SEARCH TARGET', every
     interpretation, and the marked target line; a single-interpretation need still lists 1 item.
   - controller test (stub searcher/judger/coach + FakeEngine): run(target, budget, question=Q,
     interpretations=[...]) -> the searcher-seed user message, the judged intent, and the CoachContext.intent
     all equal/contain the composed need (assert a marker substring), while result.ranked_list.intent == target.
   - update existing controller + orchestrator tests to pass question=/interpretations= (or via the stub
     StubController if the orchestrator test stubs run()).  Run `uv run pytest` -> green.

FORWARD-COMPAT CHECK (needs of 44.2/44.3/44.4): all three prompts are written against the parent's canonical
section labels. compose_need MUST emit exactly USER REQUEST / ANALYSIS / SEARCH TARGET (stable strings) so
the prompt wording matches what the agents receive. Do NOT change these labels without updating the parent
contract + all three prompt tasks. The need appears verbatim in the heavy trace (searcher-turn + judge
requests) -- expected. Judger per-call cost rises (need in every judge call) -- accepted.

GOTCHAS: keep RankedList.intent clean (do not let the need blob into output). intents.json already records
clean targets in order; intent-NN.json must match. _fill uses str.replace, so a need containing literal
braces is safe.
<!-- SECTION:PLAN:END -->
