---
id: TASK-5.10
title: >-
  Docs — update run/usage docs for the isj Searcher (reflect example-agent
  archival)
status: Done
assignee:
  - '@claude'
created_date: '2026-06-18 14:19'
updated_date: '2026-06-26 19:47'
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
- [x] #1 docs/running-the-search-stack.md documents the isj Searcher path end to end (index -> server with cover_search -> python -m isj_agent.cli --question/--out), with copy-paste commands, and describes the run-output directory layout (intents.json + intent-NN.json + intent-NN.trace.jsonl + optional errors.log; absence of errors.log == whole run succeeded).
- [x] #2 isj/README.md no longer describes the Analyst-only demo as the CLI; it describes the full per-intent Searcher pipeline and the output layout, linking to running-the-search-stack.md for run commands rather than duplicating them.
- [x] #3 CLAUDE.md 'JSONL search stack' and 'Running the apps' sections point to isj/ as the maintained agent and the cover_search tool path (the example-agent references were archived in TASK-5.4); no doc still presents examples/agent/ as the current example agent.
- [x] #4 A repo grep for 'examples/agent' finds no stale pointer presenting it as a runnable/current path (top-level README and other docs repointed to isj/).
- [x] #5 Run instructions are not duplicated: running-the-search-stack.md remains the single source and other files link to it.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Done together with 5.4. ADD the isj Searcher path on top of 5.4 archival.
1. docs/running-the-search-stack.md: replace S4 "Run the example LLM agent" with "Run the ISJ Searcher" -- build burrow -> server (cover_search) -> python -m isj_agent.cli --question <q> --out <dir> [--overwrite][--verbose] -> run-output layout (intents.json + intent-NN.json + intent-NN.trace.jsonl + optional errors.log; absence of errors.log == success). Copy-paste commands. Single source.
2. isj/README.md: already describes the full pipeline (C3); add a link to running-the-search-stack.md as the single source for run commands; fix the stale status note listing 5.4/5.10 as pending.
3. CLAUDE.md: confirm isj/ is the maintained agent + cover_search path (done in 5.4).
GATE: git grep examples/agent finds no runnable/current pointer (design/history docs left per user).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
DONE (with TASK-5.4). docs/running-the-search-stack.md S4 is now "Run the ISJ Searcher -- isj/": prerequisites (a --stem porter burrow, the server, vLLM), the CLI command (uv run --directory isj python -m isj_agent.cli --question <q> --out <dir> [--overwrite][--verbose]), the flag list, and the run-output layout (intents.json + intent-NN.json + intent-NN.trace.jsonl + errors.log; absence of errors.log == success; exits non-zero iff written). isj/README.md already describes the full pipeline (C3) + links to the run guide for starting the server; fixed its stale "still to come (5.4/5.10)" status note to point at archive/example-agent/ + the run guide. CLAUDE.md points to isj/ as the maintained agent (done in 5.4). Single source preserved: the run guide holds the run commands; isj/README links to it. grep examples/agent shows no runnable/current pointer (only the superseded agent-spec + history docs + code comments).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Updated the run/usage docs for the post-archival world. docs/running-the-search-stack.md S4 now documents the ISJ Searcher path end to end (porter burrow + server + vLLM -> python -m isj_agent.cli --question/--out) with the run-output layout and the errors.log success signal; it stays the single source. isj/README.md (already the full-pipeline description from C3) links to it for run commands and its stale status note was fixed; CLAUDE.md points to isj/ as the maintained agent. No doc presents examples/agent as a runnable/current path.
<!-- SECTION:FINAL_SUMMARY:END -->
