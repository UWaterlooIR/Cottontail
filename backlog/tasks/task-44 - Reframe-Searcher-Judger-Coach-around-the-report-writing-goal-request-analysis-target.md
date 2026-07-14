---
id: TASK-44
title: >-
  Reframe Searcher/Judger/Coach around the report-writing goal (request +
  analysis + target)
status: Done
assignee: []
created_date: '2026-07-14 04:43'
updated_date: '2026-07-14 05:26'
labels:
  - isj
  - searcher
  - judger
  - coach
dependencies: []
ordinal: 61000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The ISJ agents were built for disambiguating a possibly-ambiguous request into interpretations, and each agent currently sees only the bare target interpretation string. TREC-RAG requests are long, complex, and ask for a <=1000-word REPORT. The Analyst usefully breaks the request into report components (interpretations), but a component can read oddly out of the context of the request, or be so specific that nothing relevant is found.

Reframe the Searcher, Coach, and Judger so each sees the full picture: (1) the user's original request (the big picture), (2) the analyst's full analysis (all interpretations, showing how the need was broken down), and (3) the specific target interpretation that is this run's goal. Make the overall goal explicit everywhere: we are collecting source documents a generative AI will use to write the requested <=1000-word report.

Same flow as today (Analyst -> per-interpretation Controller loop). Searchers stay STRICTLY on their target (the request+analysis are context to interpret the target correctly, NOT license to drift to sibling components). The Judger uses a report-aware rubric.

Design decisions (locked with the user):
- The CONTROLLER composes a single per-intent 'need' string (request + full analysis with the target marked + 'Search Target: <target>') via a pure helper, and substitutes it wherever the bare intent string flows today (searcher seed, judge(intent,docs), CoachContext(intent=...)). Judger.judge and CoachContext signatures are UNCHANGED. Controller.run gains question + interpretations; RankedList.intent stays the CLEAN target (no post-hoc patching). The Orchestrator keeps its job (iterate interpretations, split budget) and just passes question + interpretations through.
- Judger rubric: 3 = highly relevant to the target, 2 = relevant to the target, 1 = relevant to the report (request/analysis) but NOT the target, 0 = not relevant to the report. Verdict schema stays 0-3.
- relevant_grade_threshold default 1 -> 2 (only target-relevant docs keep the non-relevant streak descending; off-target-but-report-relevant grade-1 docs no longer reset it).

Searchers in scope: the three arms we run -- cover/GCL (searcher.md), MultiText (mt_tiered_searcher.md), Lucindri (lucindri_searcher.md). tiered_searcher.md is out of scope (not run).

Subtasks 44.1 (plumbing), 44.2 (searcher prompts), 44.3 (judger prompt + threshold), 44.4 (coach prompt).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Each of the Searcher, Judger, and Coach receives the request + full analysis + the specific target, framed around collecting information for a generative AI to write the <=1000-word report
- [ ] #2 Flow and public agent signatures unchanged except Controller.run (gains question + interpretations); Judger.judge and CoachContext are untouched
- [ ] #3 Output stays cleanly recorded: intents.json lists the targets in order and intent-NN.json is that target's ranked list with a clean intent field
- [ ] #4 isj test suite green
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
PARENT / SHARED CONTRACT. This plan is the single source of truth the four subtasks agree on;
each subtask plan references it. Sequencing: 44.1 lands first (defines the need format + routing);
44.2/44.3/44.4 then proceed in parallel, all consuming 44.1's canonical need. Branch:
claude/agents-report-context.

============================================================================
CANONICAL need FORMAT  (implemented by 44.1's compose_need; consumed by 44.2/44.3/44.4)
============================================================================
compose_need(question: str, interpretations: list[str], target: str) -> str produces EXACTLY these
three labeled sections (self-describing, so it reads correctly inside any prompt slot):

    The user has asked for a report (up to ~1000 words) answering the request below. We are
    collecting source documents a generative AI will use to write that report; we are not writing
    the report ourselves.

    USER REQUEST (the big picture):
    <question>

    ANALYSIS (the request was broken into these information components):
      1. <interpretation 1>
      2. <interpretation 2>
      ...
      k. <interpretation k>      <-- SEARCH TARGET
      ...

    SEARCH TARGET (the one component to find information for now):
    <target>

Notes: `target` is one OF the interpretations (the current loop item), so it appears BOTH marked in
the ANALYSIS list AND isolated in SEARCH TARGET (intentional: shows where it sits among siblings and
states it unambiguously). The section LABELS (USER REQUEST / ANALYSIS / SEARCH TARGET) are the stable
contract; the three prompts refer to them by name. Keep the intro sentence about the report goal.

============================================================================
CONTROLLER ROUTING CONTRACT (44.1): which call site gets need vs the clean target
============================================================================
Inside Controller.run: `intent` (the incoming arg) = the CLEAN target interpretation; compute
`need = compose_need(question, interpretations, intent)`. Then:
  - searcher seed message        <- need   (replaces {user:"Question: {intent}"})
  - _descend(...) -> judge(...)   <- need   (_descend uses its intent arg ONLY for judger.judge;
                                             pass need in; nothing output-related uses it)
  - CoachContext(intent=...)      <- need
  - _compile(...) / RankedList.intent  <- intent (CLEAN target)   <-- keeps output clean, no patching
This is why Judger.judge and CoachContext keep their signatures: the composed need just fills the
existing {intent} string slot everywhere it already flows.

============================================================================
PROMPT CONTRACT (44.2 searcher system prompts, 44.3 judger.md, 44.4 search_coach.md)
============================================================================
Every rewritten prompt is authored KNOWING its {intent}/need input contains the three labeled
sections above. Shared framing to state in all three: the goal is collecting source documents for a
generative AI to write the <=1000-word report; the SEARCH TARGET is the one component to collect now;
the USER REQUEST + ANALYSIS are context (the big picture + how it was decomposed).
  - 44.2 searchers: search STRICTLY for the SEARCH TARGET; request+analysis are context to interpret
    it, NOT license to drift to sibling components.
  - 44.3 judger: rubric 3=highly target-relevant, 2=target-relevant, 1=report-relevant-not-target,
    0=not-report. REPLACE the current 0-3 legend in judger.md.
  - 44.4 coach: coach toward the SEARCH TARGET; UPDATE the grade legend inside search_coach.md
    (currently "1 = marginal, 2 = relevant") to the new rubric, and reframe "find EVERY document
    relevant to an information need" -> relevant to the SEARCH TARGET for the report. Explicitly tell
    the searcher that grade-1 (report-relevant, off-target) material is another searcher's job.

============================================================================
RUBRIC / THRESHOLD COHERENCE (44.3)
============================================================================
- Verdict schema stays Literal[0,1,2,3] (NO code change). -2 failure sentinel stays controller-side.
- relevant_grade_threshold default 1 -> 2 in ALL of: controller.py __init__ (line ~99), cli.py
  loop_cfg.get default (line ~114), config.example.toml [loop] comment (line ~116, with the new rubric
  meaning). _relevant(grade)=grade>=threshold drives (a) the non-relevant streak and (b) stats["relevant"]
  fed to the coach. With threshold 2, only target-relevant (>=2) keeps a query descending / counts as
  "relevant"; grade-1 (off-target) neither resets the streak nor inflates the coach's relevant count.
- The mechanical/LLM coach SHOW-selection knobs (min_show_grade / input_min_grade, default 3) are
  SEPARATE from the streak threshold and are NOT changed here.

============================================================================
OPEN DESIGN ITEM (surface to the user; default = leave as-is)
============================================================================
Retain-all records EVERY judged doc in the target's RankedList, so grade-1 (report-relevant, off-target)
docs will appear in intent-NN.json ranked BELOW the target-relevant (2/3) docs. Options: (a) keep
retain-all and let the submission builder filter by grade>=2 for target-only lists (RECOMMENDED, no
behavior change here); (b) exclude grade-1 from the per-target ranked list. Not changing it in TASK-44
unless the user asks; flagged so the per-target output semantics are a deliberate choice.

============================================================================
TEST STRATEGY (per subtask; whole isj suite green at each)
============================================================================
- 44.1: compose_need contains USER REQUEST/ANALYSIS/SEARCH TARGET + all interps + marked target;
  controller test asserts searcher-seed + judge + coach inputs carry the need while RankedList.intent
  stays the clean target; update controller/orchestrator tests for run()'s new kwargs.
- 44.2/44.3/44.4: prompt files contain the new framing markers; existing stub-based agent tests stay
  green. 44.3 also: controller streak test with threshold=2 (grade-1 does NOT reset the streak; grade-2
  does); Verdict still validates 0-3.

DEEP-READ CONCLUSION: the four subtasks compose. The only shared coupling is the canonical need format
(above) + the two grade legends (judger.md AND search_coach.md) + the single threshold default; each is
pinned here so the prompt tasks and the plumbing task cannot drift. See each subtask plan for detail.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
SEMANTIC DEEP-READ of the four subtask plans (do they compose?). Conclusion: YES -- the couplings are
identified and pinned so the plumbing and the three prompts cannot drift. Verified points:

1. Single coupling = the canonical need format (USER REQUEST / ANALYSIS / SEARCH TARGET). Defined once
   (this parent), implemented in 44.1, consumed by 44.2/44.3/44.4 by stable label. 44.1 forbids changing
   the labels without updating the parent + all three prompt tasks.
2. Routing verified against code: _descend uses its `intent` arg ONLY for judger.judge, so 44.1 routes
   need -> (searcher seed, judge, CoachContext) and the clean target -> (_compile / RankedList.intent).
   => Judger.judge and CoachContext signatures need NO change; only Controller.run grows two kwargs.
3. TWO grade legends must agree (easy to miss): judger.md (44.3) AND search_coach.md (44.4) both carry a
   0-3 legend. Both are pinned to the same rubric (grade 1 = report-relevant-not-target); each plan says
   'must match the other'.
4. Threshold 1->2 touches 3 code spots + config (44.3); it drives the non-relevant streak AND
   stats['relevant'] shown to the coach; 44.4 aligns the coach's 'relevant' to >=2. No existing test pins
   the old default of 1 (verified) -> safe change.
5. Strictly-on-target is reinforced consistently: 44.2 (search only the target), 44.3 (reward only 2/3),
   44.4 (coach steers back; grade-1 = drift to a sibling = another searcher's job).
6. VERIFIED against code: context compaction (_maybe_compact) shrinks TOOL messages only and never the
   user/system/assistant messages -> the composed need (the searcher's user seed, carrying the SEARCH
   TARGET) survives the ENTIRE run even under compaction. No change needed.
7. Test coupling: the Orchestrator test's StubController.run must accept the new question=/interpretations=
   kwargs (noted in 44.1) or the orchestrator call breaks.

RESOLVED (was 'open design item'): the per-target ranked list is ALL judged docs, ordered desc by relevance
grade with ties broken by desc retrieval score -- exactly the existing _compile behavior
(sorted key=(-grade, -score), retain-all). Grade-1/0/-2 docs stay in the list and simply sort below the
2/3s. NO change to the ranked-list contents or ordering in TASK-44; the prompt/threshold changes only affect
grades and the streak, not what gets recorded.
<!-- SECTION:NOTES:END -->
