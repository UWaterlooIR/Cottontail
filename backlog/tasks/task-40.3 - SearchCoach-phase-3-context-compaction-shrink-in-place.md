---
id: TASK-40.3
title: 'SearchCoach phase 3: context compaction (shrink-in-place)'
status: To Do
assignee: []
created_date: '2026-07-11 21:30'
updated_date: '2026-07-11 22:10'
labels: []
dependencies:
  - TASK-40.2
parent_task_id: TASK-40
ordinal: 57000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Bound the Searcher's cumulative context by compacting old feedback in place (the Controller owns the msgs list). Shrink ONLY tool messages. Trigger when the last propose's prompt_tokens reaches compact_trigger (default 0.80) of the model's context limit -- read from the [llm.*] profile's context_limit or vLLM /v1/models max_model_len (NOT hardcoded). Each pass shrinks the oldest 50% of currently-un-shrunk tool messages (halving successively); never shrink the most recent. Shrink = drop the '## Cited passages' section (keep the coaching prose + vocabulary line); if that section is not found, hard-truncate to shrink_truncate_tokens (default ~800). Emit a compact trace event. A rarely-triggering safety net; not tuned. See docs/design/search-coach.md (Bounding the conversation).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The Controller shrinks in place at compact_trigger of the model context limit (from config/vLLM, not hardcoded), shrinking only tool messages, oldest-un-shrunk-first, never the most recent.
- [ ] #2 Shrink drops the ## Cited passages section (regex), falling back to a hard-truncate at shrink_truncate_tokens when that section is absent; message count and tool_call_id pairing are preserved (protocol-safe).
- [ ] #3 A compact trace event records each pass; tests cover the shrink rule, the fallback truncate, and the keep-last invariant; the isj suite passes.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Shrink-in-place context compaction (design: 'Bounding the conversation').

1. Model context limit: add context_limit to the [llm.*] profile config; optionally auto-discover from vLLM GET /v1/models (max_model_len) in config.build_client, with the config value as override/fallback. Pass the searcher's context_limit into the Controller from cli (from [agents.searcher].llm's profile).

2. Controller compaction (operates on self.msgs, which the Controller owns): after appending each turn's tool message, read the last propose's pr.usage['prompt_tokens']; if >= compact_trigger (default 0.80) * context_limit, run a shrink pass BEFORE the next propose. Track shrunk state (a set of already-shrunk tool-message indices). A pass shrinks the oldest 50% of currently-un-shrunk role=='tool' messages, NEVER the most recent tool message; assistant messages untouched; message count + tool_call_id pairing preserved (rewrite content only).
   shrink one message: if its content contains a '## Cited passages' line, drop from that line to end (keep coaching prose + Vocabulary line); else hard-truncate content to shrink_truncate_tokens (default ~800; size via chars~=tokens*4, or the tokenizer if handy).
   degenerate floor: if only the untouchable last tool message is full and still >= trigger, second-pass hard-truncate the already-shrunk ones (or proceed; still under the hard limit). Defensive, not a hot path.

3. Emit a `compact` trace event (tool messages shrunk; prompt_tokens before / estimate after).

4. Config: [loop] compact_trigger=0.80, shrink_truncate_tokens=800; [llm.*] context_limit (or vLLM discovery); config.example.

5. Tests: shrink picks the oldest 50% of un-shrunk tool messages and never the last; drop-'## Cited passages' keeps the prose; hard-truncate fallback when the section is absent; message count + tool_call_ids unchanged; a simulated over-limit conversation converges under the trigger; full isj suite green.

FORWARD-COMPAT: last structural phase; phase 4's long A/B runs rely on this to stay under the limit.
<!-- SECTION:PLAN:END -->
