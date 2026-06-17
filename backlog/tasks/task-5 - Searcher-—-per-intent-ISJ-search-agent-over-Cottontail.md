---
id: TASK-5
title: Searcher — per-intent ISJ search agent over Cottontail
status: To Do
assignee: []
created_date: '2026-06-17 12:47'
labels:
  - searcher
dependencies: []
references:
  - docs/searcher-agent-lessons-June-16-2026.md
  - backlog/docs/doc-3
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Umbrella task for the **Searcher**: the per-intent ISJ (Interactive Searching and
Judging) search agent for the TREC RAG 2026 entry. One interpretation ("intent") of
a question goes in; a ranked, graded passage list comes out. RRF later fuses the
per-intent lists into the question's final ranking.

The design was validated by live scouting against gpt-oss-120b, Qwen3.6-27B, and
gemma-4-31B. The authoritative writeup — the loop, the prompt, the tools, the
controller, the output type, and the evidence behind each — is
docs/searcher-agent-lessons-June-16-2026.md. Background: docs/agentic-isj-investigation-planner.md
(the over-built spec we are deliberately simplifying away from) and
backlog/docs/doc-3 (per-intent retrieval + RRF fusion). A reusable probe lives at
isj/scouting/.

Decomposition (subtasks; A-track and B-track are independent because the Python
agent is mock-tested, C-track converges them):

- A1 Engine: per-atom word* family stemming in GCL queries.
- A2 Engine: search-result enrichment (total_matches, per-atom posting counts,
  exclude_docids, windowed :item passages).
- B1 Searcher contracts + canned engine (SearchEngine Protocol, result types,
  FakeEngine).
- B2 Searcher agent + guardrailed loop controller (tested against the mock).
- C1 HTTP engine client + live end-to-end against Cottontail.
- C2 RRF fusion (pure function).
- C3 Orchestrator wiring (Analyst -> Intents -> Searcher-per-intent -> RRF -> final
  ranked list).
<!-- SECTION:DESCRIPTION:END -->
