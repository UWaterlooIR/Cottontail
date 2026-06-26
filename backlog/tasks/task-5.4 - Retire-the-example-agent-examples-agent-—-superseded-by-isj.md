---
id: TASK-5.4
title: Retire the example agent (examples/agent/) — superseded by isj/
status: Done
assignee:
  - '@claude'
created_date: '2026-06-17 15:51'
updated_date: '2026-06-26 19:47'
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
- [x] #1 examples/agent/ is moved to archive/example-agent/ (or deleted if the user opts), with a note that it is a superseded POC and isj/ is the maintained agent.
- [x] #2 No authoritative doc presents the example agent as the current tool contract: running-the-search-stack.md, README.md, CLAUDE.md, and cottontail-search-agent-spec.md are updated to remove or mark-as-archived the example-agent references.
- [x] #3 The search-stack index/query/server run guidance is preserved; only the example-agent-specific pointers are removed or marked archived.
- [x] #4 bazel test //test:tests //test:hazel_test //test:jsonl_test stays green and no doc cross-links are broken.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DECISIONS (user): archive (not delete); leave the design/history docs (trec-rag-2026-design, agentic-*-spec, TASKS.md, memory/*) as historical records. Done together with TASK-5.10 (shared docs).
1. git mv examples/agent archive/example-agent; prepend an ARCHIVED banner to its README (superseded POC; maintained agent is isj/, contract is cover_search via the isj client).
2. CLAUDE.md: repoint the examples/agent bullet + search-stack section to isj/.
3. docs/cottontail-search-agent-spec.md: top banner = superseded prior agent design; maintained agent is isj/. cottontail-search-server-spec.md:353 path reference -> archive/example-agent/.
4. (shared w/ 5.10) docs/running-the-search-stack.md S4 example-agent run section removed (replaced by the isj path in 5.10).
GATE: bazel test //test:tests //test:hazel_test //test:jsonl_test green; git grep examples/agent shows no runnable/current pointer (history docs excepted).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
DONE. git mv examples/agent -> archive/example-agent (5 tracked files; __pycache__ was gitignored). Prepended an ARCHIVED banner to archive/example-agent/README.md (superseded POC; maintained agent is isj/, contract is cover_search via the isj client). Repointed the authoritative pointers: CLAUDE.md search-stack bullet -> isj/ (note the archived POC); docs/cottontail-search-agent-spec.md top banner = SUPERSEDED historical design; docs/cottontail-search-server-spec.md S10 marked historical + path -> archive/example-agent/. The example-agent run section of docs/running-the-search-stack.md was replaced by the isj path (TASK-5.10). Per user: archived (not deleted); design/history docs (trec-rag-2026-design, agentic-*-spec, TASKS.md, memory/*) left as historical records. The remaining examples/agent refs live only inside the now-superseded agent-spec (under its banner) + those history docs + code comments. GATE: bazel test //test:tests //test:hazel_test //test:jsonl_test green; no broken cross-links.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Retired the proof-of-concept example agent: git mv examples/agent -> archive/example-agent with an ARCHIVED banner pointing to the maintained ISJ Searcher (isj/) and the cover_search contract. Repointed the authoritative docs (CLAUDE.md, the run guide, the agent-spec banner, the server-spec S10) so nothing presents it as the current/runnable contract; the index/query/server guidance is preserved. Archived (not deleted) and the design/history docs left intact, per the user. C++ test gate green.
<!-- SECTION:FINAL_SUMMARY:END -->
