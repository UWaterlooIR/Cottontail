---
id: TASK-11
title: 'Heavy, detailed Searcher trace (PoC-parity) + persist the trace on failure'
status: Done
assignee:
  - '@claude'
created_date: '2026-06-26 15:49'
updated_date: '2026-06-26 17:18'
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
- [x] #1 Per-turn LLM detail in the structured trace: each LLM round-trip records the assistant content/reasoning text, the tool_calls AS EMITTED (id, name, raw arguments string), the finish_reason, and token usage (prompt_tokens, completion_tokens, total_tokens from response.usage; vLLM returns it). The prompt_tokens series lets you watch the context grow per turn and pinpoint the turn that overflows.
- [x] #2 Tool observations and payloads are captured in full, nothing truncated (the search event already carries the full results + atom_counts; keep it untruncated; ensure judge and bounce likewise carry their full payloads).
- [x] #3 Request-size visibility: each turn records the size of the request sent (at minimum the message count; prompt_tokens covers the token size). Optionally include the full request message list for total PoC fidelity -- decide and document.
- [x] #4 Persist the trace on failure: a mid-loop exception (an LLM 400 such as context-length, or an engine error) is caught inside Searcher.run, emits a final error event (exception type + message + turn + last-known usage), and Searcher returns the PARTIAL SearcherResult (the judged-so-far RankedList + the full trace ending in error). write_run then writes intent-NN.json + intent-NN.trace.jsonl for it, and the failure is still surfaced in the run summary / errors.log (not silently counted a clean success).
- [x] #5 --verbose renders the new detail live (assistant reasoning, per-turn tokens + finish_reason, tool args, full observations), in the spirit of the PoC live transcript.
- [x] #6 Tests (stub LLM, no network): assert the enriched fields (content, tool args, finish_reason, usage) are captured in the trace; assert a mid-loop raise yields a persisted partial SearcherResult whose trace ends in an error event rather than a dropped trace. uv run --directory isj pytest exits 0.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DECISIONS (user): (1) trace each LLM round-trip by what was ACTUALLY sent/received -- no append-only assumptions; drop n_messages. (2) Each LLM call is a first-class llm_call event with a purpose label + the FULL actual request messages + response + usage. (3) request is captured VERBATIM (cps, what the cp-native agent actually sent); C2 docno-rewrite keeps applying only to the structured search/judge/ranked-list fields, NOT the opaque request bodies.

1. protocol/results.py: SearcherResult gains `error: str | None = None`. (TraceEvent stays extra=allow; no schema change.)
2. agents/searcher.py:
   - Keep the FULL response: response = client...create(...); choice = response.choices[0]; message = choice.message; usage = getattr(response, "usage", None); finish_reason = getattr(choice, "finish_reason", None).
   - Snapshot request = list(msgs) BEFORE the call.
   - RENAME the per-turn event llm_turn -> llm_call; fields: purpose="searcher_turn", turn, request (the snapshot), content (message.content), calls (ALL emitted tool_calls as {id,name,arguments}), finish_reason, prompt_tokens/completion_tokens/total_tokens (getattr off usage, None-tolerant). Keep tool (first name) + tool_calls (count) for back-compat. Track last_usage across turns.
   - Wrap the whole while-loop in try/except. On Exception: emit("error", ..., error_type, message, turn, n_messages_at_fail OK to include the actual len, **last_usage) and set run_error = f"{type}: {exc}"; do NOT propagate. Return SearcherResult(ranked_list=_compile(...), events=events, error=run_error).
3. run_output.py: write_run -- when an outcome is a SearcherResult with .error set, still write intent-NN.json + .trace.jsonl AND append an errors.log line "intent NN (interp): <error>". _event_dict: leave llm_call.request VERBATIM (no cp rewrite); structured search/judge/bounce/search_request rewrite unchanged.
4. cli.py: rename llm_turn->llm_call in _render_event; render purpose, tokens (prompt+completion), finish_reason, assistant content, tool args; render the error event. failed count = RunError outcomes + SearcherResult with .error + run_error; --verbose on_intent renders a SearcherResult .error too.
5. orchestrator.py: backstop try/except -> RunError stays (truly unexpected raises); mid-loop errors now return a partial SearcherResult (no change needed beyond confirming).
6. Tests: enrich StubLLM to attach usage + finish_reason and to script a RAISING turn (e.g. an Exception in the turns list -> _create raises). test_searcher: assert llm_call carries content, calls (with raw args), finish_reason, prompt/completion/total tokens; new test: a mid-loop raise -> run() RETURNS (not raises) a SearcherResult whose .error is set, whose trace ends in an error event, and whose ranked_list holds the pre-failure judgements. Rename llm_turn->llm_call in existing assertions. test_run_output: a SearcherResult with .error -> intent json + trace written AND an errors.log line.
7. README: note the llm_call event (per-call request + response + usage), the error event, and persist-on-failure.

GATE: uv run --directory isj pytest green; no network/model. (Real-LLM confirmation rides along with TASK-10 live run.)
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Reference implementation to mirror: examples/agent/search_agent.py -- _render_json (full untruncated JSON of messages/observations/response), _response_payload (finish_reason + content + tool_calls with raw arguments), _llm_summary (latency, finish_reason, tool-call count, token usage prompt+completion), run_agent (the live per-step transcript). Capture this BEFORE TASK-5.4 retires that agent. isj code to change: isj_agent/agents/searcher.py (keep the full response object; enrich the llm_turn emit; wrap the loop to catch+emit error+return partial), isj_agent/protocol/results.py (TraceEvent fields), isj_agent/run_output.py (currently skips failed intents), isj_agent/cli.py (_render_event), isj_agent/orchestrator.py (RunError path). Overlaps TASK-10: this task owns the trace richness, token-usage visibility, and partial-result-on-failure; TASK-10 keeps the context BUDGETING/trimming so the window is not blown in the first place.

IMPLEMENTED. protocol/results.py: SearcherResult gains error: str|None. agents/searcher.py: keep the full response (usage + choice.finish_reason); snapshot request=list(msgs) before each call; renamed llm_turn -> llm_call carrying purpose="searcher_turn", turn, request (verbatim messages sent), content (assistant reasoning), calls (ALL emitted tool_calls as {id,name,arguments}), finish_reason, prompt/completion/total tokens (None-tolerant), plus tool/tool_calls for back-compat; track last_usage. The create() call is wrapped in try/except -> on failure emit an error event (error_type, message, turn, failing request, last_usage) and return a PARTIAL SearcherResult(error=...) instead of propagating. run_output.py: a SearcherResult with .error still writes intent-NN.json + .trace.jsonl AND appends an errors.log line; _event_dict leaves llm_call.request verbatim (cps -- what the cp-native agent actually sent), structured search/judge/bounce/search_request still docno-rewritten. cli.py: _render_event renders llm_call (tool, finish_reason, prompt+completion tokens, reasoning, tool args) and the error event; failed count includes SearcherResult.error; on_intent notes PARTIAL. Tests: StubLLM now attaches usage + finish_reason and raises a scripted Exception turn; test_searcher asserts llm_call content/calls/finish_reason/usage + the verbatim seed request, and a new test_partial_result_on_llm_failure (a mid-loop raise -> run() returns, not raises; .error set; trace ends in error event; pre-failure judgement kept; error event carries the failing request + last usage 200). test_run_output: a SearcherResult with .error -> json+trace written + errors.log line. README + results.py type comment updated. DESIGN per user: each LLM round-trip is a first-class llm_call event with the ACTUAL request (no n_messages count -- that assumed append-only); forward-compatible with TASK-10 compaction/side-prompts via the purpose label. GATE: uv run pytest = 63 passed, 1 skipped; no network/model.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
The Searcher trace is now heavy and detailed, and it survives failures. Each LLM round-trip is a first-class llm_call event carrying a purpose label, the ACTUAL request messages sent (verbatim, cp-native), the assistant reasoning content, the emitted tool calls with raw arguments, finish_reason, and prompt/completion/total token usage -- captured per call (no append-only n_messages assumption) so it stays faithful under the compaction/side-prompts TASK-10 will add. A mid-loop LLM failure (e.g. a context-length 400) is caught inside run(): it emits an error event (with the failing request + last-known usage) and returns a PARTIAL SearcherResult (.error set, the pre-failure judgements kept) instead of discarding the trace; write_run persists that intent json + trace and lists it in errors.log, and the CLI counts it failed. The cp->docno rewrite stays on the structured search/judge/ranked-list fields; the request snapshot is left verbatim (what the model actually saw). 63 pytest pass, no network/model; README updated. The real-LLM confirmation (intent-01/02 keeping their traces with the prompt_tokens climb) rides along with the TASK-10 live run.
<!-- SECTION:FINAL_SUMMARY:END -->
