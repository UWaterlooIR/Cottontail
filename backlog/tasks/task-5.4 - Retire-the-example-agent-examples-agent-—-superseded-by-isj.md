---
id: TASK-5.4
title: Retire the example agent (examples/agent/) — superseded by isj/
status: To Do
assignee: []
created_date: '2026-06-17 15:51'
updated_date: '2026-06-18 15:15'
labels:
  - cleanup
  - docs
  - searcher
dependencies: []
references:
  - examples/agent
  - docs/running-the-search-stack.md
  - docs/cottontail-search-agent-spec.md
  - README.md
  - archive/README.md
parent_task_id: TASK-5
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Goal

Retire the proof-of-concept example agent at `examples/agent/`. It was a POC built
against an earlier, looser tool contract (it leaned on the whole-query `--stem` flag and
treated `search_gcl` as a general search tool). The going-forward agent is the ISJ agent
under `isj/`, and the tool surface is being reshaped to its needs (A1/A2 + the B/C tasks).
Keeping the old example around invites confusion about which is the real contract.

## What to do

- Move `examples/agent/` to `archive/example-agent/` (the repo keeps non-authoritative,
  superseded material under `archive/`; see archive/README.md), OR delete it if the user
  prefers — default to archiving so the history/example is still readable.
- Add a one-line note in `archive/example-agent/README` (or the archive README) saying it
  is a superseded POC; the maintained agent is `isj/` and the tool contract is the
  cover_search tool (A1/A2) reached via the isj client.
- Update references so nothing authoritative points at it as the contract:
  `docs/running-the-search-stack.md`, the top-level `README.md`, `CLAUDE.md`, and any
  mention in `docs/cottontail-search-agent-spec.md`. Either remove the example-agent
  sections or clearly mark them as archived/superseded. (REMOVE/MARK only — do NOT write the
  new isj run instructions here; adding the isj Searcher path is TASK-5.10's job.)
- Confirm the build/test gate is unaffected (the example agent is a uv project, not in
  the Bazel build; just make sure no doc/test references break).

## Boundary with TASK-5.10 (no double-editing)

This task and TASK-5.10 both touch the same docs (`running-the-search-stack.md`, `README.md`,
`CLAUDE.md`, `cottontail-search-agent-spec.md`), so split the work cleanly:
- 5.4 (this task, runs at archival): REMOVE or MARK-AS-ARCHIVED the OLD example-agent
  pointers so nothing presents it as the current contract. It does NOT add isj content.
- TASK-5.10 (depends on 5.4 + the C3 CLI): ADD the new isj Searcher path (run commands +
  output layout) and the final repointing to `isj/`.

## Non-goals

- Do NOT touch the C++ tool layer or the isj/ package here (that is the A1/A2 engine work
  and the B/C agent work).
- Do NOT remove the search-stack docs themselves — only the example-agent-specific
  pointers; the index/query/server guidance stays.
- Do NOT add the new isj Searcher run instructions / the isj path to the docs — that is
  TASK-5.10. 5.4 only removes or marks-archived the old example-agent pointers.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 examples/agent/ is moved to archive/example-agent/ (or deleted if the user opts), with a note that it is a superseded POC and isj/ is the maintained agent.
- [ ] #2 No authoritative doc presents the example agent as the current tool contract: running-the-search-stack.md, README.md, CLAUDE.md, and cottontail-search-agent-spec.md are updated to remove or mark-as-archived the example-agent references.
- [ ] #3 The search-stack index/query/server run guidance is preserved; only the example-agent-specific pointers are removed or marked archived.
- [ ] #4 bazel test //test:tests //test:hazel_test //test:jsonl_test stays green and no doc cross-links are broken.
<!-- AC:END -->
