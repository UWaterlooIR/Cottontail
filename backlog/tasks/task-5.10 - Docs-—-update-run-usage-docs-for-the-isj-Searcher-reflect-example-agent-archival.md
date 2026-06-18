---
id: TASK-5.10
title: >-
  Docs — update run/usage docs for the isj Searcher (reflect example-agent
  archival)
status: To Do
assignee: []
created_date: '2026-06-18 14:19'
updated_date: '2026-06-18 15:15'
labels:
  - searcher
dependencies:
  - TASK-5.4
  - TASK-5.9
parent_task_id: TASK-5
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

Documentation only — Markdown edits across the repo. NO code, NO new behavior. This task
makes the run/usage docs describe WHAT CAN BE RUN AND HOW, after the example agent is
archived (TASK-5.4) and the isj Searcher CLI ships (TASK-5.9). DEPENDS ON both so the docs
describe the real, final state (the archived agent gone, the new CLI present).

## Context (for an agent new to this project)

The repo is mid-migration: the old example LLM agent under examples/agent/ is being archived
(TASK-5.4) and replaced by the isj/ Searcher pipeline (Analyst -> per-intent Searcher over a
Cottontail burrow via the HTTP server's cover_search tool, persisted to a run-output
directory by the CLI: `python -m isj_agent.cli --question <q> --out <dir>`; see TASK-5.9 for
the CLI and TASK-5.8 for the output layout). The docs still describe the OLD world:

- docs/running-the-search-stack.md is the project's SINGLE SOURCE for how to build and run
  the JSONL search stack (index -> query -> server -> agent). It still points at the example
  agent and says nothing about the isj Searcher path.
- isj/README.md still describes the Analyst-ONLY demo CLI, not the full per-intent Searcher
  pipeline.
- CLAUDE.md ("JSONL search stack" + "Running the apps" sections) lists examples/agent/ as the
  example LLM agent.

## Relationship to TASK-5.4 (no overlap)

TASK-5.4 (a dependency) has ALREADY removed or marked-archived the example-agent pointers at
archival time. This task does NOT redo that archival; its job is to ADD the NEW isj Searcher
path (run commands + output layout) and complete the repointing to isj/. If 5.4 happened to
leave any example-agent pointer live, fix it in passing, but the primary work here is
documenting the new flow.

## Required behavior (the contract)

1. docs/running-the-search-stack.md (KEEP IT THE SINGLE SOURCE): add the isj Searcher path
   end to end — build a burrow (cottontail-jsonl-index), run the server
   (cottontail-jsonl-server) with cover_search, then run the Searcher CLI
   `python -m isj_agent.cli --question <q> --out <dir> [--overwrite] [--verbose]`; describe
   the run-output directory (intents.json + intent-NN.json + intent-NN.trace.jsonl + optional
   errors.log; absence of errors.log == whole run succeeded). Copy-paste commands.
2. isj/README.md: replace the Analyst-only demo description with the full pipeline + the CLI
   flags + the output layout (or, to avoid duplication, summarize and LINK to
   running-the-search-stack.md for the run commands — the single-source rule wins).
3. CLAUDE.md: ensure the "JSONL search stack" and "Running the apps" sections point to isj/
   as the maintained agent and the cover_search tool path (5.4 already marked examples/agent/
   as archived; here just ADD/confirm the isj pointer). Fix any remaining stale pointer.
4. Top-level README.md (if present) and any other lingering examples/agent/ references in
   docs: repoint to isj/. (grep the repo for examples/agent to find them.)
5. Do NOT duplicate run instructions across files: running-the-search-stack.md is the single
   source; other files link to it rather than repeating commands.

## Non-goals

- No code, no CLI behavior, no new tasks of substance — documentation only.
- Do not re-do TASK-5.4's archival (removing/marking the old example-agent pointers); assume
  it is done and ADD the isj flow on top.
- Do not document fusion/RRF/Task-R/RAG (out of scope / dropped).
- Do not resurrect anything from archive/.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 docs/running-the-search-stack.md documents the isj Searcher path end to end (index -> server with cover_search -> python -m isj_agent.cli --question/--out), with copy-paste commands, and describes the run-output directory layout (intents.json + intent-NN.json + intent-NN.trace.jsonl + optional errors.log; absence of errors.log == whole run succeeded).
- [ ] #2 isj/README.md no longer describes the Analyst-only demo as the CLI; it describes the full per-intent Searcher pipeline and the output layout, linking to running-the-search-stack.md for run commands rather than duplicating them.
- [ ] #3 CLAUDE.md 'JSONL search stack' and 'Running the apps' sections point to isj/ as the maintained agent and the cover_search tool path (the example-agent references were archived in TASK-5.4); no doc still presents examples/agent/ as the current example agent.
- [ ] #4 A repo grep for 'examples/agent' finds no stale pointer presenting it as a runnable/current path (top-level README and other docs repointed to isj/).
- [ ] #5 Run instructions are not duplicated: running-the-search-stack.md remains the single source and other files link to it.
<!-- AC:END -->
