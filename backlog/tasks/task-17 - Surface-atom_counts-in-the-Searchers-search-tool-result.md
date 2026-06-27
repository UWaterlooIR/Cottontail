---
id: TASK-17
title: Surface atom_counts in the Searcher's search-tool result
status: Done
assignee: []
created_date: '2026-06-27 21:26'
updated_date: '2026-06-27 21:43'
labels:
  - python
  - isj
  - searcher
dependencies: []
references:
  - isj/isj_agent/controller.py
  - isj/isj_agent/agents/searcher.md
  - isj/isj_agent/protocol/search.py
  - docs/searcher-agent-lessons-June-16-2026.md
priority: medium
ordinal: 31000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why

While documenting the search-tool JSON for TASK-16's `searcher.md`, we found the payload the controller returns to the Searcher (the `_summarize` dict in `isj/isj_agent/controller.py`) does NOT include `atom_counts` — the per-query-leaf corpus occurrence counts. So the Searcher cannot see when one of its atoms matched NOTHING (a typo, a shortened stem like `hik*` instead of `hike*`, or a dead expansion). The croup live runs showed exactly this failure mode go undetected. The searcher-agent lessons doc (`docs/searcher-agent-lessons-June-16-2026.md`) is explicit that a zero-posting atom should be VISIBLE, not silent.

`cover_search` already returns `atom_counts: [{term, count}]` (the engine has them; the controller already emits them in the `search` TRACE event). They just aren't forwarded to the model in the tool result.

## What

Add `atom_counts` to the `_summarize` payload so the Searcher sees, per query leaf, the term as written and its total corpus occurrence count; a count of 0 flags a dead atom to fix. Then teach it in `searcher.md` (Part 2 'what the search tool returns' + Part 3.3 'broaden when dry'): an atom with count 0 is a typo/shortened-stem/dead-expansion — rewrite it.

Notes:
- A query may do several continuation fetches; the atoms (query leaves) and their corpus counts are the same across them, so carry the atom_counts from the query's first/representative search.
- Keep it cp-native and small; this is purely additive to the tool result.

## Where
- `isj/isj_agent/controller.py` — `_descend` (capture `resp.atom_counts`) and `_summarize` (include them).
- `isj/isj_agent/agents/searcher.md` — document and teach the field.
- `isj/tests/test_controller.py` — assert atom_counts appear in the search-tool result.
- Re-sync TASK-16's embedded summarize-payload shape if it enumerates fields.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The search-tool result the Searcher receives (the controller's _summarize payload) includes atom_counts: a list of {term, count} per query leaf, term as written (e.g. hike*), count = total corpus occurrences; count 0 marks a dead atom
- [x] #2 atom_counts carries across a query's continuation fetches (same leaves/counts); the value shown is the query's representative search
- [x] #3 searcher.md documents atom_counts in the returned-JSON section and teaches that a count-0 atom is a typo/shortened-stem/dead-expansion to rewrite
- [x] #4 tests/test_controller.py (FakeEngine + stub) assert atom_counts appear in the tool-result payload
- [x] #5 Change is purely additive to the tool result; cp-native; no engine/server change (cover_search already returns atom_counts)
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented in controller._summarize + _descend: the search-tool result now includes atom_counts (representative first-fetch counts; identical across a query's continuation fetches) ahead of total_matches. searcher.md Part 2 documents the field and Part 3.3 teaches that a count-0 atom is a typo/shortened-stem to rewrite. test_controller asserts atom_counts presence and the exact payload field order. Additive to the tool result; cp-native; no engine/server change (cover_search already returned atom_counts). Landed with the result-field reorder (rank, score, summary, reason, grade) in the same commit.
<!-- SECTION:FINAL_SUMMARY:END -->
