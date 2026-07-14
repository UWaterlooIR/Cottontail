---
id: TASK-42
title: 'Add ReportAnalyst (report-component decomposition, v3 report prompt)'
status: Done
assignee:
  - '@claude'
created_date: '2026-07-13 17:46'
updated_date: '2026-07-14 03:35'
labels:
  - analyst
  - isj
dependencies: []
ordinal: 59000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A new Analyst type that decomposes an information need into the information COMPONENTS a RAG report must synthesize (the scouting prompt-report-v3), rather than disambiguating interpretations. Produces the same {question, interpretations[]} contract so downstream is unchanged.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 ReportAnalyst(Analyst) bundles report_analyst.md (= scouting prompt-report-v3.md) and is selectable via [agents.analyst].class. It fills interpretations[] with report components and validates as Intents.
- [x] #2 The Intents schema docstring is neutralized (e.g. 'each is a self-contained, search-ready statement of one distinct thing to find') so it fits both interpretations and components without the json_schema description fighting the report prompt.
- [x] #3 isj analyze with the ReportAnalyst config produces per-topic artifacts whose analyst.class/prompt record the ReportAnalyst provenance; tests cover the class + a sample decomposition shape; isj suite green.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
GOAL: Add ReportAnalyst -- an Analyst variant that decomposes an information need into the
information COMPONENTS a RAG report must synthesize (the scouting prompt-report-v3), instead of
disambiguating interpretations. Produces the SAME Intents{question, interpretations[]} contract,
so nothing downstream (Controller, artifact, run_output) changes. Work on branch
claude/analyst-report-scout. DEPENDS ON TASK-41 (build_analyst + the analysis artifact).

KEY CURRENT FACTS (verified):
- Analyst.analyze (isj/isj_agent/agents/analyst.py) builds messages=[{system: self.prompt},{user: question}]
  and response_format json_schema from Intents.model_json_schema(); returns Intents.model_validate_json(content).
  So overriding the class attribute `prompt` is the ONLY change needed for a variant; __init__ is inherited
  (client, model, *, reasoning_effort='medium', temperature=0.0, max_tokens=8000, timeout_s=120.0).
- The bundled-prompt pattern to mirror: SearchCoachAgent (search_coach.py) does
  files('isj_agent.agents').joinpath('search_coach.md').read_text(encoding='utf-8').
- Intents docstring (protocol/intents.py) is sent to vLLM as the json_schema description and says
  'each is a distinct reading ... one thing the user might mean' -- this fights the report-component
  framing and must be neutralized.
- The chosen prompt is isj/scouting/analyst/prompt-report-v3.md (already ends with an Output section
  instructing JSON {question, interpretations}). It is the working/versioned scout copy.

STEPS:
1. BUNDLE the prompt: copy isj/scouting/analyst/prompt-report-v3.md ->
   isj/isj_agent/agents/report_analyst.md  (a shipped copy; the scout's prompt-report-v3.md stays the
   working/versioned source, same relationship as search_coach.md <- scouting prompt-v10).

2. NEW isj/isj_agent/agents/report_analyst.py:
     from importlib.resources import files
     from isj_agent.agents.analyst import Analyst
     class ReportAnalyst(Analyst):
         '''Analyst variant: decompose the need into the information COMPONENTS a RAG report must
         synthesize (report_analyst.md), not disambiguating interpretations. Same Intents{question,
         interpretations[]} contract -> pipeline downstream unchanged.'''
         prompt: str = files('isj_agent.agents').joinpath('report_analyst.md').read_text(encoding='utf-8')
   (analyze() inherited; it reads self.prompt, so the overridden class attr is sufficient.)

3. NEUTRALIZE the Intents docstring (isj/isj_agent/protocol/intents.py) so the json_schema description
   fits BOTH interpretations and report components. Replace the current docstring body with e.g.:
     'interpretations must be non-empty. Each is a self-contained, search-ready statement of one
     distinct thing to find for this question -- a reading the user might mean, or a component of the
     answer -- capturing WHAT to find, not WHY. A simple need may yield a single item.'
   (Truthful for the shipped Analyst too; do NOT rename the field -- keep `interpretations`.)

4. config.example.toml -- document the [agents.analyst] class choices:
     # class = 'isj_agent.agents.analyst.Analyst'                    # default: interpretations
     # class = 'isj_agent.agents.report_analyst.ReportAnalyst'       # RAG report components (prompt-report-v3)
   (build_analyst from TASK-41 resolves whichever class is set.)

5. TESTS (isj/tests/test_report_analyst.py):
   - ReportAnalyst.prompt contains a distinctive phrase from the report prompt
     (e.g. 'components the report will be built from').
   - analyze() parses a stubbed response into Intents: mirror the existing Analyst test style -- a stub
     openai client whose chat.completions.create returns a SimpleNamespace with
     choices[0].message.content = json.dumps({'question':'q','interpretations':['c1','c2']}); assert
     ReportAnalyst(stub,'m').analyze('q') == Intents(question='q', interpretations=['c1','c2']).
   - build_analyst with config {'agents':{'analyst':{'class':'isj_agent.agents.report_analyst.ReportAnalyst',
     'llm':'default'}}, 'llm':{'default':{'model':'m','base_url':...}}} returns a ReportAnalyst.
   Run `uv run pytest` -> green.

GOTCHAS:
- report_analyst.md is a shipped COPY of prompt-report-v3.md; note the divergence in the commit msg
  (same as search_coach.md vs scouting prompt-vN). If v3 changes later, re-copy.
- The neutralized Intents docstring is SHARED by both analysts (Analyst + ReportAnalyst) -- confirm the
  shipped Analyst's dev-topic output isn't harmed (it should not be; the wording stays true for
  interpretations). Optionally re-run isj/scouting/analyst/run.py --prompt (default) to sanity-check.
- Keep the field name `interpretations` (renaming would ripple through Intents/Orchestrator/Controller/
  run_output). The report components simply populate that list.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented on branch claude/analyst-report-scout (isj/), depends on TASK-41:
- isj_agent/agents/report_analyst.md: shipped COPY of scouting/analyst/prompt-report-v3.md (same relationship as search_coach.md <- scouting prompt). If v3 changes later, re-copy.
- isj_agent/agents/report_analyst.py: ReportAnalyst(Analyst) overriding only the bundled `prompt` (analyze() inherited).
- protocol/intents.py: neutralized the Intents docstring (the shared json_schema description sent to vLLM) so it fits both interpretations and report components.
- tests/test_report_analyst.py (5): subclass, prompt bundling, load_class, analyze()->Intents, build_analyst->ReportAnalyst. Full isj suite green: 226 passed, 1 skipped.

Docs updated:
- config.example.toml: [agents.analyst] documents the two class choices.
- isj/README.md, docs/design/reference-specs/running-the-search-stack.md, docs/design/agent-architecture.txt: the 'analyst-agnostic' passages now name ReportAnalyst as the concrete shipped variant (report-component decomposition) alongside the default Analyst.

Notes:
- AC#3 provenance: analyst_meta records analyst.class (+ model/reasoning/temperature), which fixes the prompt via class identity; the raw prompt text is intentionally NOT stored (same decision as TASK-41).
- End-to-end `isj analyze` with the ReportAnalyst config and the docstring sanity-check (shipped Analyst dev-topic output unharmed) need a live vLLM endpoint; verified at the unit level, live run by hand.
<!-- SECTION:NOTES:END -->
