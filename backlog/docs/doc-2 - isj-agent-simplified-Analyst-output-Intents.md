---
id: doc-2
title: 'isj-agent: simplified Analyst output (Intents)'
type: specification
created_date: '2026-06-16 20:50'
updated_date: '2026-06-16 20:51'
---
# isj-agent: Simplified Analyst Output (Intents)

## Decision

The INP -> CM -> IP pipeline specified in
docs/agentic-isj-investigation-planner.md is **shelved**, not deleted. It is too
complex to implement now and overfits the six worked examples it was derived
from. The spec is retained as a north star if the simpler approach proves too
thin.

The Analyst instead produces a small, concrete `Intents` artifact:

```python
class Intents(BaseModel):
    question: str               # the verbatim user question
    interpretations: list[str]  # ordered, most-plausible first; >= 1 entry
```

## Rationale

The Analysts essential job is to read a user question and reason about what the
user means. The valuable, implementable primitive is **disambiguation**:
enumerate the distinct interpretations of the question, each written as a
self-contained, search-ready restatement.

- **Interpretations, not goals.** Each interpretation captures the WHAT (what
  the user wants found), not the WHY (their purpose). Question-type / purpose
  tagging from the spec is deferred.
- **A list subsumes the single-translation case.** An unambiguous question
  yields a list of length one; an ambiguous one yields several. There is no
  separate single-output mode.
- **No weights yet.** Rank carries the signal (most-plausible first), and LLMs
  rank more reliably than they calibrate probabilities. Weights are added only
  when a downstream consumer actually uses them.

## Implementation notes

- The Analyst makes a **single LLM call** against a vLLM (OpenAI-compatible)
  endpoint. Structured output uses **guided decoding** via a JSON-schema
  `response_format` generated from `Intents.model_json_schema()`, so the model
  is constrained to emit schema-valid JSON. No parse-and-repair loop is needed.
- The prompt (isj_agent/agents/analyst.md) is self-contained and describes the
  Intents output directly; it does not reference spec section numbers the model
  cannot see.

## Related

- See `doc-1` (isj-agent agent design decisions) for the prompt-as-implementation
  and dependency-injection decisions.
