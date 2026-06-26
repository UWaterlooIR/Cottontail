---
id: TASK-11
title: 'Heavy, detailed Searcher trace (PoC-parity) + persist the trace on failure'
status: To Do
assignee: []
created_date: '2026-06-26 15:49'
labels:
  - isj
  - observability
dependencies: []
priority: high
ordinal: 25000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Searcher trace is too thin, and it is discarded entirely when an intent fails. In the TASK-7 live re-run, intents 01 and 02 blew the LLM context window (163198 / 167708 tokens vs a 131072 limit) but their traces DO NOT EXIST: write_run skips failed (RunError) intents. Even surviving traces omit the model reasoning, the raw tool-call arguments, the finish_reason, and per-turn token usage, so you cannot see why a query was formed or why the window filled.

The PoC example agent (examples/agent/search_agent.py) already had the verbose trace we want and it is the BAR TO MATCH. Capture it now, because that agent is slated for retirement (TASK-5.4). Per LLM round-trip the PoC emitted, with nothing truncated: the full request (model + message count + the entire message list via _render_json), an LLM-response summary (round-trip latency, finish_reason, tool-call count, token usage prompt+completion via _llm_summary), the full response payload (finish_reason, assistant content, tool_calls with id/name/raw arguments via _response_payload), the assistant reasoning text, and for each tool call the name+args plus the FULL tool observation (untruncated). See run_agent in that file.

Goal: bring that richness into the isj STRUCTURED trace (TraceEvent -> intent-NN.trace.jsonl), not just a stderr stream, AND render it in --verbose, AND keep the trace when an intent fails. This is the heavy detailed trace the user asked for; it also makes the TASK-10 context-window overflow diagnosable (the prompt_tokens series is the smoking gun) and recoverable (partial result on error).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Per-turn LLM detail in the structured trace: each LLM round-trip records the assistant content/reasoning text, the tool_calls AS EMITTED (id, name, raw arguments string), the finish_reason, and token usage (prompt_tokens, completion_tokens, total_tokens from response.usage; vLLM returns it). The prompt_tokens series lets you watch the context grow per turn and pinpoint the turn that overflows.
- [ ] #2 Tool observations and payloads are captured in full, nothing truncated (the search event already carries the full results + atom_counts; keep it untruncated; ensure judge and bounce likewise carry their full payloads).
- [ ] #3 Request-size visibility: each turn records the size of the request sent (at minimum the message count; prompt_tokens covers the token size). Optionally include the full request message list for total PoC fidelity -- decide and document.
- [ ] #4 Persist the trace on failure: a mid-loop exception (an LLM 400 such as context-length, or an engine error) is caught inside Searcher.run, emits a final error event (exception type + message + turn + last-known usage), and Searcher returns the PARTIAL SearcherResult (the judged-so-far RankedList + the full trace ending in error). write_run then writes intent-NN.json + intent-NN.trace.jsonl for it, and the failure is still surfaced in the run summary / errors.log (not silently counted a clean success).
- [ ] #5 --verbose renders the new detail live (assistant reasoning, per-turn tokens + finish_reason, tool args, full observations), in the spirit of the PoC live transcript.
- [ ] #6 Tests (stub LLM, no network): assert the enriched fields (content, tool args, finish_reason, usage) are captured in the trace; assert a mid-loop raise yields a persisted partial SearcherResult whose trace ends in an error event rather than a dropped trace. uv run --directory isj pytest exits 0.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Reference implementation to mirror: examples/agent/search_agent.py -- _render_json (full untruncated JSON of messages/observations/response), _response_payload (finish_reason + content + tool_calls with raw arguments), _llm_summary (latency, finish_reason, tool-call count, token usage prompt+completion), run_agent (the live per-step transcript). Capture this BEFORE TASK-5.4 retires that agent. isj code to change: isj_agent/agents/searcher.py (keep the full response object; enrich the llm_turn emit; wrap the loop to catch+emit error+return partial), isj_agent/protocol/results.py (TraceEvent fields), isj_agent/run_output.py (currently skips failed intents), isj_agent/cli.py (_render_event), isj_agent/orchestrator.py (RunError path). Overlaps TASK-10: this task owns the trace richness, token-usage visibility, and partial-result-on-failure; TASK-10 keeps the context BUDGETING/trimming so the window is not blown in the first place.
<!-- SECTION:NOTES:END -->
