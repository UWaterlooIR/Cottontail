---
name: trace-must-be-heavy-detailed
description: User wants heavy, detailed Searcher traces (model reasoning + token usage) and the trace must survive a failed intent
metadata:
  type: feedback
---

The user has asked twice for a "heavy detailed trace" of the Searcher and found
the delivered trace inadequate. The B2 trace captured structured events
(`llm_turn`/`search`/`judge`/`bounce`/`stop`) but OMITTED: the model's own
reasoning content, the raw tool-call arguments as emitted, the finish_reason, and
per-turn token usage. Worse, `write_run` discards a failed intent's trace
entirely (it skips RunError outcomes), so when an intent blew the LLM context
window the very trace needed to debug it did not exist.

**Why:** the trace is the primary research artifact. Without the model's reasoning
and `usage.prompt_tokens` per turn you cannot explain why a query was formed or
why the context window overflowed; and discarding failed-intent traces hides
exactly the failures most in need of debugging.

**How to apply:** in the Searcher loop, capture per turn the assistant
content/reasoning, the tool-call name+arguments as emitted, the finish_reason, and
`response.usage` (prompt/completion/total tokens — vLLM returns it). Persist the
partial trace even when an intent errors: catch the mid-loop exception, emit an
`error` event, and return a partial `SearcherResult` (trace + judged-so-far)
instead of letting the exception abort the intent and drop the trace. Default to
MORE detail in agent traces, not less. Related: [[pr-jsonl-cli]].
