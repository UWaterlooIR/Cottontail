---
id: TASK-2
title: Internalize prompt into Analyst; document agent design decisions
status: Done
assignee:
  - '@claude'
created_date: '2026-06-16 18:17'
updated_date: '2026-06-16 18:51'
labels: []
dependencies: []
references:
  - docs/agentic-isj-investigation-planner.md
  - isj/isj_agent/agents/analyst.py
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
During TASK-1 review, three design decisions were settled that need to land in the codebase:

1. The prompt is the agent implementation — not config, not an injected argument. Each agent class owns its prompt internally, loaded via importlib.resources from a companion file inside the isj_agent package. You would never swap a prompt independently of the agent; you would use a different agent class (tested separately). So Analyst.__init__ takes no prompt argument.

2. Agents are injected into the Orchestrator. The Orchestrator does not construct agents; it receives fully-built agents and calls them. Dependency injection.

3. The CLI config controls which agent class to instantiate — e.g. isj_agent.agents.analyst.Analyst — not which prompt to use. Prompt selection is not a runtime concern; it is resolved at class-definition time.

This task applies decision (1) to the existing Analyst stub: removes the hacky Path(__file__) default, moves prompts/analyst.md inside the isj_agent package, and loads it via importlib.resources. It also records all three decisions as a backlog decision document so follow-on tasks (CLI, Orchestrator, remaining agents) have a shared contract to build against.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Analyst.__init__ takes no prompt argument — the prompt is owned internally by the class, not injected
- [x] #2 prompts/analyst.md is moved from isj/prompts/ into the isj_agent package (e.g. isj_agent/agents/analyst.md); the top-level isj/prompts/ directory is removed
- [x] #3 analyst.py loads its prompt via importlib.resources (e.g. importlib.resources.files("isj_agent.agents").joinpath("analyst.md")); no Path(__file__) traversal anywhere in the agent
- [x] #4 isj/pyproject.toml is updated so the prompt file is included as package data and survives uv build
- [x] #5 tests/test_analyst.py updated — Analyst() constructed with no arguments; a test asserts the prompt is a non-empty string accessible on the instance
- [x] #6 uv run --directory isj pytest tests/test_analyst.py exits 0
- [x] #7 A backlog decision document records: (1) prompt is agent implementation owned internally via importlib.resources — not injected config; (2) agents are injected into the Orchestrator; (3) CLI config selects which agent class to instantiate, not which prompt to use
- [x] #8 isj/config.example.toml is checked in with a header comment instructing the user to copy it to isj/config.toml, and each key is annotated explaining its purpose and valid values
- [x] #9 isj/config.toml is listed in .gitignore and is not tracked by git
- [x] #10 isj_agent/config.py provides a load_class(dotted_path: str) function that imports and returns a class by its fully-qualified dotted path
- [x] #11 A test asserts that load_class("isj_agent.agents.analyst.Analyst") returns the Analyst class
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Move prompt file into the package.
   git mv isj/prompts/analyst.md isj/isj_agent/agents/analyst.md
   Remove the now-empty isj/prompts/ directory.

2. Update isj/pyproject.toml to bundle prompt files as package data.
   Add to [tool.hatch.build.targets.wheel]:
     artifacts = ["isj_agent/**/*.md"]

3. Rewrite isj/isj_agent/agents/analyst.py.
   - Remove Path, _DEFAULT_PROMPT, and __init__.
   - Load prompt at class-definition time via importlib.resources:
       _PROMPT = files("isj_agent.agents").joinpath("analyst.md").read_text(encoding="utf-8")
   - prompt as a class attribute (all instances share the same implementation).
   - analyze(self, question: str) -> INP still raises NotImplementedError.

4. Add isj/isj_agent/config.py — class-loader utility.
   A load_class(dotted_path: str) function that splits on the last ".",
   imports the module, and returns the named attribute. The CLI uses this
   to instantiate agents from the config file.

5. Create isj/config.example.toml.
   Checked in. Contains instructions at the top telling the user to copy
   it to isj/config.toml (which is git-ignored). Each config key is
   annotated with a comment explaining what it does and what values are valid.
   Minimum contents:
     [agents]
     analyst = "isj_agent.agents.analyst.Analyst"  # dotted path to Analyst class

6. Add isj/config.toml to .gitignore.
   Check whether the repo root .gitignore or a new isj/.gitignore is the
   right place; add "config.toml" there.

7. Update isj/tests/test_analyst.py.
   - Remove test_analyst_prompt_path_exists.
   - Add test_analyst_has_prompt: asserts Analyst.prompt is a non-empty str.
   - Add test_load_class: asserts load_class("isj_agent.agents.analyst.Analyst")
     returns the Analyst class.
   - Existing tests (analyze signature, NotImplementedError, reusable) pass
     unchanged since Analyst() still takes no arguments.

8. Create the backlog decision document via backlog doc create.
   Records all three decisions: (1) prompt is agent implementation owned
   internally via importlib.resources; (2) agents injected into Orchestrator;
   (3) CLI reads config.toml, uses load_class to instantiate agent classes,
   no prompt selection at runtime.

9. Verify.
   uv run --directory isj pytest tests/test_analyst.py -v  (all pass)
   uv run --project isj python -c "from isj_agent.agents.analyst import Analyst; print(len(Analyst.prompt))"
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
prompt loads via importlib.resources at class-definition time — 3642 chars. load_class tested and working. config.example.toml checked in; /isj/config.toml added to .gitignore. Decision doc at backlog/docs/doc-1.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Internalized analyst prompt into isj_agent/agents/analyst.md (loaded via importlib.resources); removed Path(__file__) hack; added isj_agent/config.py with load_class(); created config.example.toml with annotated keys; gitignored config.toml; wrote agent design decision doc (doc-1). 5 tests pass.
<!-- SECTION:FINAL_SUMMARY:END -->
