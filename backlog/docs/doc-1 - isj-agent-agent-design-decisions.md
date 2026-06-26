---
id: doc-1
title: isj-agent agent design decisions
type: specification
created_date: '2026-06-16 18:49'
updated_date: '2026-06-16 18:50'
---
# isj-agent Agent Design Decisions

These decisions were settled during TASK-1 and TASK-2 review and apply to all
agent implementations in the isj-agent system.

## Decision 1 — The prompt is agent implementation, not configuration

Each agent class owns its prompt internally. The prompt is loaded at
class-definition time via `importlib.resources` from a companion `.md` file
inside the `isj_agent` package (e.g. `isj_agent/agents/analyst.md`).

**Rationale:** A prompt is code — it determines the agent behaviour just as
a function body does. Swapping a prompt without changing and re-testing the
agent is not a valid operation. If you need different behaviour, implement a
different class and test it separately.

**Consequences:**
- Agent `__init__` methods do not accept a prompt argument.
- Prompt files live inside the `isj_agent` package tree, not in a top-level `prompts/` directory.
- `pyproject.toml` declares `artifacts = ["isj_agent/**/*.md"]` so prompt files are bundled into the installed package.

## Decision 2 — Agents are injected into the Orchestrator

The Orchestrator receives fully-constructed agent instances; it does not
construct them. This is standard dependency injection.

**Rationale:** Keeps the Orchestrator decoupled from agent construction
details (which class, which config). Makes the Orchestrator testable with
stub agents.

**Consequences:**
- The Orchestrator constructor accepts agent instances as arguments.
- The CLI is responsible for constructing agents and passing them in.

## Decision 3 — CLI config selects which agent class to instantiate

`isj/config.toml` (git-ignored; copy from `config.example.toml`) specifies
each agent role as a fully-qualified Python class path:

```toml
[agents]
analyst = "isj_agent.agents.analyst.Analyst"
```

The CLI uses `isj_agent.config.load_class(dotted_path)` to resolve each class
at startup, instantiates it, and injects it into the Orchestrator.

**Rationale:** Swapping agent implementations is a class-level concern, not a
prompt-level concern. Config controls which tested implementation to run.

**Consequences:**
- Prompt selection is not a runtime concern; it is resolved at class-definition time (see Decision 1).
- Alternative agent implementations (e.g. `AnalystV2`) are separate classes with their own prompts and their own tests.
