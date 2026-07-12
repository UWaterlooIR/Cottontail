---
id: TASK-40.3
title: 'SearchCoach phase 3: context compaction (shrink-in-place)'
status: Done
assignee: []
created_date: '2026-07-11 21:30'
updated_date: '2026-07-12 00:23'
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
- [x] #1 The Controller shrinks in place at compact_trigger of the model context limit (from config/vLLM, not hardcoded), shrinking only tool messages, oldest-un-shrunk-first, never the most recent.
- [x] #2 Shrink drops the ## Cited passages section (regex), falling back to a hard-truncate at shrink_truncate_tokens when that section is absent; message count and tool_call_id pairing are preserved (protocol-safe).
- [x] #3 A compact trace event records each pass; tests cover the shrink rule, the fallback truncate, and the keep-last invariant; the isj suite passes.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
GOAL: bound the Searcher's cumulative context by compacting old feedback IN PLACE. Design: docs/design/search-coach.md ("Bounding the conversation -- context compaction"). DEPENDS ON 40.2.

READ FIRST:
- isj/isj_agent/controller.py run(): `msgs` is the local chat list ([{role:system},{role:user},{role:assistant,tool_calls},{role:tool,tool_call_id,content},...]); each turn appends the searcher's assistant message and the tool reply via self._tool(...); `pr.usage` is the ProposeResult usage dict and pr.usage["prompt_tokens"] is the EXACT size the server saw for the last request.
- isj/isj_agent/config.py build_client + the [llm.*] profile; cli.py (where the searcher's llm profile is chosen).
- isj/isj_agent/protocol/results.py TraceEvent (add a "compact" event) and how emit() persists events.

FACTS / CONSTRAINTS:
- Tool messages are role=="tool". NEVER delete one: an assistant message with tool_calls MUST be followed by a tool message with the matching tool_call_id, or vLLM/OpenAI 400s. Rewrite content ONLY.
- Use pr.usage["prompt_tokens"] (server truth) as the TRIGGER signal. Use chars (~4 chars/token) only to size the hard-truncate.

STEPS:
1. context_limit:
   - config: add context_limit to the [llm.*] profile (config.example: [llm.default] context_limit = 131072). Optionally auto-discover in config.build_client: GET {base_url}/v1/models, read data[0].max_model_len; config value overrides/falls back. Keep config primary; discovery optional.
   - Pass the SEARCHER's context_limit into the Controller from cli (the [agents.searcher].llm profile's context_limit). Controller.__init__ gains: context_limit:int|None=None, compact_trigger:float=0.80, shrink_truncate_tokens:int=800. Add self._shrunk:set[int]=set() (indices of tool messages already shrunk).
2. Controller.run(): after self._tool(...) each turn, capture last_pt=pr.usage.get("prompt_tokens"); call self._maybe_compact(msgs, last_pt).
3. Controller._maybe_compact(msgs, last_pt):
   - if self.context_limit is None or last_pt is None or last_pt < self.compact_trigger*self.context_limit: return.
   - tool_idx = [i for i,m in enumerate(msgs) if m.get("role")=="tool"]; if len(tool_idx)<=1: return. protected=tool_idx[-1] (the most recent tool msg -- NEVER shrink). candidates=[i for i in tool_idx[:-1] if i not in self._shrunk] (oldest-first).
   - shrink the oldest ceil(len(candidates)/2) of `candidates`: for each i: self._shrink_message(msgs[i]); self._shrunk.add(i).
   - emit("compact", time.time(), 0.0, prompt_tokens=last_pt, shrunk=<n>, tool_messages=len(tool_idx)).
   - degenerate floor (defensive, rarely hit): if candidates was empty (all but the last already shrunk) and still over trigger, optionally second-pass hard-truncate the already-shrunk; else return (still <100% of the hard limit).
4. Controller._shrink_message(m): c=m["content"]; if isinstance(c,str) and "## Cited passages" in c: m["content"]=c[:c.index("## Cited passages")].rstrip()  # keep the coaching prose + Vocabulary line; else: keep=self.shrink_truncate_tokens*4; if len(c)>keep: m["content"]=c[:keep].rstrip()+"\n...[older feedback truncated]".
5. Config: [loop] compact_trigger=0.80, shrink_truncate_tokens=800; [llm.*] context_limit (or vLLM discovery). config.example.toml with comments (context_limit is the model limit; trigger is a fraction of it).
6. Tests: tests/test_compaction.py (or extend test_controller.py). Build a Controller with a small context_limit and a hand-made msgs list with several tool messages of known content; call _maybe_compact with a prompt_tokens over/under the trigger. Assert: under trigger -> no change; over -> shrinks the oldest 50% of un-shrunk tool messages, NEVER the last tool message, NEVER an assistant/system/user message; message COUNT and every tool_call_id unchanged. A tool message containing "## Cited passages" -> content becomes the prose before that header; one without -> hard-truncated to ~shrink_truncate_tokens. Repeated triggers halve the remaining un-shrunk (K->K/2->...). A compact trace event is emitted with the counts. Full isj suite green.

GOTCHAS/DECISIONS: rewrite content only, never delete a tool message (tool_call_id pairing); shrink ONLY tool messages; keep the last tool message intact; TRIGGER on server prompt_tokens (not a local estimate); chars/4 only sizes the truncate. This is a rarely-triggering SAFETY NET -- not tuned; if it never fires in a run, that is expected.

FORWARD-COMPAT: last structural phase (phase 4 only relies on long runs staying under the limit).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented on branch claude/task-40-searchcoach-tasks (follows 40.2).

Files:
- isj/isj_agent/controller.py -- Controller.__init__ gained context_limit:int|None=None, compact_trigger:float=0.80, shrink_truncate_tokens:int=800. run() keeps a per-run `shrunk:set[int]` and calls self._maybe_compact(msgs, pr.usage.get("prompt_tokens"), shrunk, emit) after each turn's tool append (both coach and bounce paths). New methods:
  * _maybe_compact: no-op unless context_limit and last_pt are set and last_pt >= compact_trigger*context_limit; collects tool-message indices, protects the LAST one, shrinks the oldest ceil(half) of the still-un-shrunk candidates (K->K/2->K/4...), emits a "compact" trace event (prompt_tokens/shrunk/tool_messages). Degenerate floor: if all-but-last are already shrunk and still over trigger, hard-truncate them (pass_="floor").
  * _shrink_message: drops the "## Cited passages" section (keeps coaching prose + Vocabulary line) via a fixed-header index; hard-truncates when the header is absent.
  * _hard_truncate: trims to shrink_truncate_tokens*4 chars + "...[older feedback truncated]"; idempotent (returns whether it changed anything).
  Content is rewritten IN PLACE only -- no message is ever deleted, so assistant tool-call <-> tool_call_id pairing is preserved.
- isj/isj_agent/config.py -- resolve_context_limit(llm_config, client): config context_limit primary; else best-effort vLLM /v1/models max_model_len discovery; any failure -> None (compaction disabled, safe). Never hardcoded.
- isj/isj_agent/cli.py -- resolves the SEARCHER profile's context_limit (that is the conversation being bounded) and passes context_limit/compact_trigger/shrink_truncate_tokens (from [loop]) into the Controller.
- isj/config.example.toml -- documented context_limit on [llm.*] and compact_trigger/shrink_truncate_tokens under [loop].
- isj/tests/test_compaction.py (NEW, 9 tests): no-op guards (no context_limit / under trigger / None prompt_tokens / <=1 tool msg); over-trigger shrinks oldest-half, never the last tool msg, never assistant/system/user, message count + role/tool_call_id shape invariant, compact event emitted; header-drop keeps prose+vocab; no-header hard-truncate; repeated triggers halve remaining (4,2,1,1 for 8 candidates) then a floor pass; floor hard-truncate.

Suite: 208 passed, 1 skipped. resolve_context_limit smoke-verified (config / none / discovery / discovery-fail).

DEVIATION (minor): AC#2 says "regex" for the section drop; I used a fixed-substring index on the literal "## Cited passages" header (simpler and more robust than a regex for a constant header). Behavior is identical.

NATURE: rarely-triggering safety net, not tuned. Won't fire in a normal max_queries run (needs ~105k accumulated feedback). If it never triggers, that is expected.
<!-- SECTION:NOTES:END -->
