---
id: TASK-4
title: Replace INP with Intents and implement Analyst.analyze() LLM call
status: Done
assignee:
  - '@claude'
created_date: '2026-06-16 20:20'
updated_date: '2026-06-16 20:54'
labels: []
dependencies: []
references:
  - docs/agentic-isj-investigation-planner.md
  - isj/isj_agent/protocol/inp.py
  - isj/isj_agent/agents/analyst.py
  - isj/isj_agent/agents/analyst.md
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
We are simplifying the Analyst output, implementing it, and driving it from the CLI.

Background: the INP -> CM -> IP pipeline specified in docs/agentic-isj-investigation-planner.md is too complex to implement now and overfits the six worked examples it was derived from. The Analysts essential job is to read a user question and reason about what the user means.

### Protocol
Replace the INP placeholder with a small, concrete Intents type:

```python
class Intents(BaseModel):
    question: str               # the verbatim user question
    interpretations: list[str]  # ordered, most-plausible first; >= 1 entry
```

Each interpretation is a self-contained, search-ready restatement of one thing the user might mean (the WHAT, not the WHY). Unambiguous question -> one interpretation; ambiguous -> several. No weights yet — rank carries the signal. No purpose / question-type tagging yet.

### Analyst implementation
Implement analyze(question: str) -> Intents as a single LLM call:
- System message: the bundled analyst.md prompt.
- User message: the literal question.
- Structured output: pass a JSON-schema response_format derived from Intents.model_json_schema() so vLLM constrains generation (guided decoding). See the note below.
- Validate the returned content with Intents.model_validate_json() and return it.
- One call; no elaborate retry loop yet (validation errors propagate).

### Prompt
Rewrite analyst.md to be self-contained (no spec section references the model cannot see) and to describe the Intents output: emit the verbatim question plus an ordered list of self-contained, search-ready interpretation restatements; a single interpretation when unambiguous.

### CLI demo
Update isj_agent/cli.py so that, after wiring the Analyst, it calls analyst.analyze(question) for several questions and pretty-prints each result (the question followed by its ordered, numbered interpretations). Questions come from a small built-in sample set chosen to show both an unambiguous question (one interpretation) and an ambiguous one (several); positional command-line arguments override the sample set. Pretty-printing is done by a format_intents(intents: Intents) -> str helper so it can be unit-tested without an LLM. This lets the user watch the Analyst run against a real vLLM endpoint.

### Testing
analyze() is unit-tested with a mocked OpenAI client returning canned JSON; format_intents is unit-tested on a constructed Intents. No automated test contacts a live endpoint. A manual run of the CLI against the configured local vLLM instance confirms end-to-end behaviour.

### Structured-output method (decision for review)
Proposed: response_format = {"type": "json_schema", "json_schema": {"name": "Intents", "schema": Intents.model_json_schema(), "strict": true}}, which vLLM supports as OpenAI-compatible guided decoding. Alternative if that path misbehaves: extra_body = {"guided_json": Intents.model_json_schema()}.

The full INP / CM / IP design is shelved, not deleted — the spec remains a north star if the simple version proves too thin.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 isj_agent/protocol/intents.py defines an Intents pydantic model with question: str and interpretations: list[str]; interpretations is ordered most-plausible-first and must contain at least one entry (min_length=1)
- [x] #2 The old INP type and isj_agent/protocol/inp.py are removed
- [x] #3 Analyst.analyze(self, question: str) -> Intents is implemented as a single LLM call: system message is the bundled analyst.md prompt, user message is the question, structured output is requested via a JSON-schema response_format derived from Intents.model_json_schema(), and the response content is validated with Intents.model_validate_json() and returned
- [x] #4 isj_agent/agents/analyst.md is rewritten to be self-contained: no references to spec section numbers the model cannot see; instructs the model to output the Intents JSON shape (verbatim question plus an ordered list of self-contained, search-ready interpretation restatements); states that an unambiguous question yields a single interpretation
- [x] #5 isj_agent/cli.py calls analyst.analyze(question) for several questions and pretty-prints each result (question followed by its ordered, numbered interpretations); questions come from a built-in sample set covering an unambiguous and an ambiguous question, overridable by positional command-line arguments
- [x] #6 A format_intents(intents: Intents) -> str helper produces the pretty-printed output and is unit-tested on a constructed Intents (no LLM)
- [x] #7 tests/test_analyst.py references Intents instead of INP; one test asserts Intents validates with a question and a non-empty interpretations list; one test drives analyze() with a mocked OpenAI client returning canned JSON and asserts the returned Intents matches; no automated test contacts a live endpoint
- [x] #8 uv run --directory isj pytest tests/ exits 0
- [x] #9 isj/README.md updated so references to INP/CM/IP reflect the simplified Intents output, the Analyst is described as implemented, and the CLI demo run is documented
- [x] #10 A backlog decision document records the simplification: INP/CM/IP shelved in favor of Intents; Analyst outputs an ordered list of interpretation restatements (what not why); no weights until a consumer needs them; structured output via JSON-schema response_format; spec retained as north star
- [x] #11 Manual live run documented in task notes: uv run --directory isj python -m isj_agent.cli against the configured local vLLM endpoint pretty-prints interpretations for the sample questions
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Self-contained plan for a coding agent. Work inside the isj/ uv project (a
top-level, installed-editable package `isj_agent` built with hatchling). Use the
backlog CLI for all task/doc updates; never edit backlog markdown directly. After
code changes, run `uv sync --project isj`.

## Context you need
- The Analyst (isj_agent/agents/analyst.py) converts one user question into an
  Intents object. Its prompt is bundled inside the package as
  isj_agent/agents/analyst.md and loaded at import via importlib.resources
  (already in place). The OpenAI client (openai.OpenAI pointed at a vLLM
  endpoint) and the model name are injected into Analyst.__init__(client, model)
  (already in place).
- vLLM exposes an OpenAI-compatible API. We use guided decoding via the
  response_format json_schema parameter (decision: structured output method "c").
- The CLI (isj_agent/cli.py) already reads config.toml, builds the client via
  isj_agent.config.build_client, resolves the Analyst class via
  isj_agent.config.load_class, instantiates it, and injects it into a stub
  Orchestrator (isj_agent/orchestrator.py). This task makes the CLI actually run
  the Analyst and print results.

## Step 1 — Protocol: replace INP with Intents
- Create isj_agent/protocol/intents.py:

    from pydantic import BaseModel, Field

    class Intents(BaseModel):
        """Analyst output: the user question plus inferred interpretations.

        interpretations is ordered most-plausible-first and must be non-empty.
        Each interpretation is a self-contained, search-ready restatement of one
        thing the user might mean (the WHAT, not the WHY). An unambiguous
        question yields a single interpretation.
        """

        question: str
        interpretations: list[str] = Field(min_length=1)

- Delete isj_agent/protocol/inp.py.
- Grep the whole isj/ tree (isj_agent/ and tests/) for INP / inp and fix every
  reference to Intents / intents.

## Step 2 — Analyst.analyze() LLM call
In isj_agent/agents/analyst.py, change the import from the inp module to:

    from isj_agent.protocol.intents import Intents

Replace the body of analyze() (it currently raises NotImplementedError) with:

    def analyze(self, question: str) -> Intents:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": question},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "Intents",
                    "schema": Intents.model_json_schema(),
                },
            },
        )
        content = response.choices[0].message.content
        return Intents.model_validate_json(content)

Keep the existing class-level `prompt` attribute and the __init__(client, model).
Fallback (only if the live run in Step 8 shows the vLLM server rejecting the
response_format form): drop response_format and instead pass
extra_body={"guided_json": Intents.model_json_schema()}. Record in task notes
which form was used.

## Step 3 — Rewrite the prompt (self-contained)
Replace the entire contents of isj_agent/agents/analyst.md. It MUST NOT reference
any spec section numbers (the model never sees the spec). Write a prompt that:
- States the role: you are the Analyst; given one user question, infer what the
  user is actually looking for.
- States the output: a JSON object with two fields — question (the user
  question, verbatim) and interpretations (an ordered list of strings).
- Explains interpretations: each is a self-contained, search-ready restatement of
  one distinct thing the user might mean; order them most-plausible first; if the
  question has only one reasonable reading, output a single interpretation;
  capture WHAT the user wants, not WHY; keep each to about one sentence; do not
  invent specifics the question does not imply.
(The JSON shape is also enforced by guided decoding, but the prompt still
describes the task and what a good interpretation looks like.)

## Step 4 — CLI demo
In isj_agent/cli.py:
- Add a module-level SAMPLE_QUESTIONS list with the six questions verbatim
  (exact text below, including punctuation).
- Add a pretty-printer:

    from isj_agent.protocol.intents import Intents

    def format_intents(intents: Intents) -> str:
        lines = [f"Q: {intents.question}"]
        for i, interp in enumerate(intents.interpretations, start=1):
            lines.append(f"  {i}. {interp}")
        return "\n".join(lines)

- Extend main(): add an argparse positional argument `questions` with nargs="*".
  Set questions = args.questions or SAMPLE_QUESTIONS. Keep the existing config
  read and agent wiring. Print a one-line header showing the endpoint and model,
  then for each question call analyst.analyze(q) and print format_intents(result),
  separated by a blank line. (Call via the constructed analyst, e.g.
  orchestrator.analyst.analyze(q).)

SAMPLE_QUESTIONS verbatim:
1. Will wearing an ankle brace help heal achilles tendonitis?
2. What language and cultural differences impede the integration of foreign minorities in Germany?
3. What security measures are in effect or are proposed to go into effect in airports?
4. Find ways of measuring creativity.
5. I'm hoping to grasp the intricacies of different healthcare systems, particularly what drives their accessibility, cost, and the fundamental debate around healthcare as a right versus a privilege. Can you explain the main factors affecting healthcare delivery, equity, and expenses, and suggest ways to improve health outcomes for everyone?
6. I'm a college student who has seen articles about Geoffrey Hinton and his resignation from Google, with warnings of AI's impacts, but I don't fully understand the context of these warnings. Since I'm interested in the future of AI and how it might affect jobs or safety, I'd like a report that breaks down the story and why Hinton's warnings matter. I want something that helps me follow this issue more clearly without needing a tech background.

## Step 5 — Tests (no network in any automated test)
tests/test_analyst.py:
- Replace the INP import with Intents.
- Update test_analyst_analyze_signature: assert the return annotation is Intents.
- Remove test_analyst_analyze_raises (analyze no longer raises).
- Keep test_analyst_has_prompt, test_analyst_stores_client_and_model,
  test_load_class_returns_analyst.
- Add test_intents_requires_nonempty: Intents(question="q", interpretations=["a"])
  succeeds; Intents(question="q", interpretations=[]) raises pydantic
  ValidationError (import ValidationError from pydantic; use pytest.raises).
- Add test_analyze_with_mocked_client:
  - Build client = MagicMock().
  - Set client.chat.completions.create.return_value to a MagicMock whose
    .choices[0].message.content is the JSON string
    {"question": "Q", "interpretations": ["one", "two"]}.
  - a = Analyst(client=client, model="gpt.oss.120b"); result = a.analyze("Q").
  - assert result == Intents(question="Q", interpretations=["one", "two"]).
  - assert client.chat.completions.create.call_count == 1 and the call kwargs
    include model="gpt.oss.120b" and a response_format whose
    ["json_schema"]["name"] == "Intents".

tests/test_cli.py (new):
- test_format_intents: construct Intents(question="What is X?",
  interpretations=["first", "second"]); assert the formatted string contains the
  question text and both numbered interpretations.

## Step 6 — README
Update isj/README.md:
- Replace protocol references (INP, CM, IP) with Intents.
- State the Analyst is implemented as a single guided-decoding LLM call returning
  Intents.
- Document the demo command: `uv run --directory isj python -m isj_agent.cli`
  (no args uses the six sample questions) and the override form
  `uv run --directory isj python -m isj_agent.cli "your question" "another"`.

## Step 7 — Decision document
Create and fill a backlog decision doc:
- backlog doc create "isj-agent: simplified Analyst output (Intents)" -t specification
- backlog doc update <doc-id> --content "..." recording:
  - INP/CM/IP from docs/agentic-isj-investigation-planner.md are shelved (too
    complex to implement now; overfit to the six worked examples). Retained as a
    north star.
  - Analyst outputs Intents: the verbatim question plus an ordered list of
    interpretation restatements (WHAT not WHY); unambiguous question -> single
    interpretation.
  - No weights until a downstream consumer uses them (rank carries the signal).
  - Structured output via JSON-schema response_format (guided decoding),
    schema generated from Intents.model_json_schema().

## Step 8 — Verify
- uv sync --project isj
- uv run --directory isj pytest tests/ -v   (all pass; confirm no test hits the
  network)
- Live demo: requires the configured vLLM endpoint to be up; this is an external
  network call, so obtain explicit user go-ahead before running it. Command:
      uv run --directory isj python -m isj_agent.cli
  Capture the printed output and append it to the task:
      backlog task edit 4 --append-notes "<captured output + which structured-output form worked>"

## Step 9 — Finalize
- Check each acceptance criterion with: backlog task edit 4 --check-ac N
- backlog task edit 4 --final-summary "..." and set status Done.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Live smoke test passed: 'uv run --directory isj python -m isj_agent.cli' run against the configured local vLLM endpoint pretty-printed interpretations for the six sample questions. The response_format json_schema (guided decoding) path worked; the extra_body/guided_json fallback was not needed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Replaced INP placeholder with a concrete Intents type (question + ordered, non-empty interpretations). Implemented Analyst.analyze() as a single guided-decoding LLM call (JSON-schema response_format from Intents.model_json_schema(), validated via model_validate_json). Rewrote analyst.md self-contained. CLI now runs the Analyst over a built-in 6-question sample set (overridable by positional args) and pretty-prints via format_intents. 7 automated tests pass with no network; live smoke test passed against local vLLM. README updated; decision recorded in doc-2.
<!-- SECTION:FINAL_SUMMARY:END -->
