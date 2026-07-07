---
id: TASK-26
title: >-
  Pre-scouting for TASK-22: tool-call program emission, stem* in MultiText,
  multi-turn librarian prompt
status: Done
assignee:
  - '@claude'
created_date: '2026-07-03 03:12'
updated_date: '2026-07-03 03:42'
labels: []
dependencies: []
priority: high
ordinal: 40000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Three scouts that de-risk TASK-22 (MultiTextTieredSearcher), requested by Mark 2026-07-03. Harness: isj/scouting/multitext-dsl-2/ (style of multitext-dsl/), vLLM gpt.oss.120b at 127.0.0.1:8000, temperature 0, reasoning_effort medium (the validated combo), //apps:mt-compile as the validity oracle, live 1M dev server (port 8081) for end-to-end checks. NOTE: the original multitext-dsl scout defined a submit_tiered_query tool but never passed it — all captured results were content-mode extraction; Mark reports earlier attempts at tool-call emission failed.

S1 — program as a tool call: same 10 TREC-4 topics, clean librarian prompt, but tools=[submit_tiered_query] + tool_choice=required, non-streaming — mirroring BaseSearcher.propose exactly. Record tool-call presence, JSON args parse, newline survival, compile rate vs the 10/10 content-mode baseline; classify failures.

S2 — stem*: (a) no-LLM pre-check that starred quoted tokens ("bear*", incl. inside <> and < [N]) compile through Mt and desugar through cover_rewrite end-to-end (jsonl-query --cover on the compiled tier against the 1M burrow; family atoms visible in atom_counts); (b) prompt extended with the word* rule, re-run the 10 topics, check sensible usage + compile.

S3 — multi-turn: adapt the librarian prompt to a turn loop (tiered_searcher.md-style feedback sections; keep the anti-loop properties: no markup, output-only, medium effort). 3 turns per need over ~4 hand-written GENERAL-WEB needs (ClimbMix is a general web corpus — NOT climbing) against the live 1M server: compile + run tiers via tiered_query_search, append the real tool response as feedback, next turn. Measure per-turn validity, reasoning-size stability, and whether programs adapt rather than repeat.

Output: captured JSONL per run + FINDINGS.md with go/no-go per item and prompt deltas. If S1 fails hard, that is a design input for TASK-22 (content-mode emission variant), not a blocker for S2/S3.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 S1 run captured: tool-call emission rate, args-parse rate, and compile rate over the 10 baseline topics, with failure classification
- [x] #2 S2 pre-check documented (starred tokens through mt-compile AND cover_rewrite end-to-end), and the stem* prompt run captured with usage + compile results
- [x] #3 S3 captured: >=4 general-web needs x 3 turns against the live server, with per-turn compile validity, reasoning sizes, and an adapt-vs-repeat assessment
- [x] #4 FINDINGS.md summarizes all three with go/no-go verdicts and the prompt deltas; results reported to Mark
- [x] #5 TASK-22 depends on this task and its references are refreshed (src/mt.cc -> gcl/mt.cc)
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
All three scouts GO (isj/scouting/multitext-dsl-2/captured/FINDINGS.md). S1: 10/10 tool-call emission AND compile through the real BaseSearcher path once macro names are constrained (new discovery: Mt's lexer rejects underscores in identifiers — a one-line prompt rule). S2: stem* composes end-to-end (Mt passes starred quoted tokens; cover_rewrite desugars to the family; LLM used stars on 38% of tokens with 0 bad placements, 10/10 compile); numeric proximity operands leak into atom_counts (handler should filter). S3: multi-turn loop stable over 17 turns (16 clean; reasoning flat at 1-2K chars; programs adapt with 5-25 new terms/turn; exclusion honored) and the compile-error bounce self-repairs in one retry 2/3 (worst case two). BONUS: the live-tier sweep exposed and fixed a TASK-25 data race (vector<bool> worker-status bitfield); dev servers restarted on the fixed binary. Carry into TASK-22: no-underscore rule, word* rule + example, numeric-leaf filter, proximity-join idiom example, >=2 bounce retries.
<!-- SECTION:FINAL_SUMMARY:END -->
