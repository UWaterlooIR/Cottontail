---
id: TASK-10
title: isj Searcher can exceed the LLM context window on verbose corpora
status: To Do
assignee: []
created_date: '2026-06-26 15:05'
updated_date: '2026-06-26 15:06'
labels:
  - isj
  - bug
dependencies: []
priority: medium
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Found during the TASK-7 live re-run (C3 CLI on the black-bear question over Scrapheap/climbmix-1M-porter.burrow, gpt-oss-120b, 131072-token context). Two of three interpretations failed with:
  BadRequestError 400: Input length (163198) exceeds model's maximum context length (131072)
  BadRequestError 400: Input length (167708) exceeds model's maximum context length (131072)

The Searcher loop (isj_agent/agents/searcher.py) appends every cover_search response into the message history as a tool message (the full SearchResponse: top_k passages with summaries, atom_counts, etc.). Cover responses are large (a single 'bear*' cover_search response was ~97 KB of JSON over the wire). Recall-first means many searches per intent, so the accumulated context grows unbounded and eventually exceeds the model's context window -- then the NEXT chat.completions.create raises a 400 and the whole intent aborts.

Two distinct problems:
1. No context budgeting: the Searcher feeds back full responses indefinitely with no trimming/compaction, so a long recall-first session blows the window.
2. Total loss on overflow: when the 400 escapes Searcher.run, C3 records the whole intent as a RunError and the judged passages already accumulated (a partial RankedList) are discarded -- the run keeps the trace for successful intents only.

This is unrelated to the server crash (TASK-7, fixed); the server served every request (all 2xx). It is an isj Searcher context-management issue.
<!-- SECTION:DESCRIPTION:END -->


## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Discovered in the TASK-7 live gate. Numbers observed: 163198 and 167708 input tokens vs a 131072 max. Relevant code: the loop in isj_agent/agents/searcher.py (msgs.append of tool results), and how C3 (orchestrator.run_question) turns an escaped exception into a RunError (isj_agent/orchestrator.py). Consider: the model knob max_turns already bounds turns, but not token volume; a token/byte budget on retained tool results is the real lever.
<!-- SECTION:NOTES:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Characterize the overflow: with the dev/1M burrow and a real model, identify roughly how many searches / what response sizes drive the message history past the model context window (the live run hit ~163k-168k tokens vs a 131072 limit).
- [ ] #2 The Searcher bounds the context it feeds back so a long recall-first session does not exceed the model window -- e.g. trim/compact older tool results (the judged state is already tracked separately in the judged/recorded structures), cap retained results per response, and/or drop superseded search responses. The chosen approach is documented.
- [ ] #3 Resilience: a context-length 400 (or other mid-loop LLM error) no longer discards the intent accumulated work -- the Searcher returns the partial SearcherResult (the RankedList judged so far + trace) instead of letting the exception abort the whole intent. (Or an explicit, documented decision otherwise.)
- [ ] #4 Tests (no network/model) cover the trimming/compaction logic and the partial-result-on-error path with a stub LLM; uv run --directory isj pytest exits 0.
<!-- AC:END -->
