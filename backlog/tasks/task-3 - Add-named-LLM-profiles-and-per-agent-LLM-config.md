---
id: TASK-3
title: Add named LLM profiles and per-agent LLM config
status: Done
assignee:
  - '@claude'
created_date: '2026-06-16 19:07'
updated_date: '2026-06-16 19:35'
labels: []
dependencies: []
references:
  - isj/config.example.toml
  - isj/isj_agent/agents/analyst.py
  - isj/isj_agent/config.py
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The config structure needs to support named LLM profiles (model+endpoint pairs) that can be assigned per agent. This allows different agents to use different vLLM endpoints and models, while the CLI constructs one OpenAI-compatible client per unique endpoint and injects the right client and model into each agent.

config.example.toml structure:

```toml
[llm.default]
base_url = "http://127.0.0.1:8000/v1"
# model must match --served-model-name on the vLLM instance
model = "gpt.oss.120b"
# api_key_env = "MY_VLLM_API_KEY"
# Name of the environment variable holding the API key for this endpoint.
# If not set, the key defaults to "EMPTY", which works for unauthenticated
# local vLLM instances. If set, the named variable must exist or an error
# is raised at startup.

[agents.analyst]
class = "isj_agent.agents.analyst.Analyst"
llm = "default"
```

The CLI (isj_agent/cli.py):
1. Reads isj/config.toml (or a path passed via --config)
2. Builds an openai.OpenAI client for each referenced [llm.*] entry via build_client()
3. Uses load_class() to get the agent class named in [agents.<role>]
4. Instantiates each agent with its assigned client and model
5. Injects the constructed agents into the Orchestrator

This task delivers the CLI wiring end-to-end so that the full construction chain — config → LLM client → agent class → agent instance → Orchestrator — is visible and runnable, even though analyze() still raises NotImplementedError and the Orchestrator is a stub.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 config.example.toml restructured: [llm.<name>] sections with base_url, model, and optional api_key_env; [agents.<role>] sections with class and llm keys
- [x] #2 config.example.toml uses base_url = "http://127.0.0.1:8000/v1" and model = "gpt.oss.120b"; model has a comment that it must match --served-model-name on the vLLM instance; api_key_env is commented out with a comment explaining the default is "EMPTY" (works for local vLLM) and that if set, the named variable must exist
- [x] #3 Analyst.__init__ accepts client: openai.OpenAI and model: str and stores them as instance attributes
- [x] #4 isj_agent/config.py gains a build_client(llm_config: dict) -> openai.OpenAI function: if api_key_env is present in llm_config, reads that environment variable and raises RuntimeError if it is not set; if api_key_env is absent, uses "EMPTY" as the key
- [x] #5 tests/test_analyst.py updated to construct Analyst with a stub client and model; all tests pass
- [x] #6 uv run --directory isj pytest tests/test_analyst.py exits 0
- [x] #7 isj_agent/cli.py exists with a main() entry point that reads config.toml, constructs the LLM client via build_client, instantiates the Analyst via load_class, and injects it into a stub Orchestrator
- [x] #8 Running the CLI (uv run --directory isj python -m isj_agent.cli --config config.example.toml) prints the resolved agent class and LLM endpoint without error, demonstrating the full wiring
- [x] #9 isj_agent/orchestrator.py exists as a stub that accepts agent instances in __init__ and stores them
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Rewrite isj/config.example.toml with the two-level structure:
   [llm.default] with base_url, model (commented to match --served-model-name),
   and api_key_env commented out with explanation of the "EMPTY" default and
   error-on-missing behaviour. [agents.analyst] with class and llm keys.

2. Update isj_agent/config.py — add build_client(llm_config: dict) -> openai.OpenAI:
   - If "api_key_env" is in llm_config, read that env var; raise RuntimeError if not set.
   - Otherwise use api_key="EMPTY".
   - Construct and return openai.OpenAI(base_url=llm_config["base_url"], api_key=api_key).

3. Update isj_agent/agents/analyst.py — add __init__(self, client: openai.OpenAI, model: str):
   stores both as instance attributes alongside the existing class-level prompt.

4. Add isj_agent/orchestrator.py stub:
   class Orchestrator with __init__(self, *, analyst: Analyst) storing the agent.

5. Add isj_agent/cli.py with main() entry point:
   - Parse --config argument (default: config.toml relative to cli.py).
   - Read TOML with tomllib (stdlib, Python >= 3.11).
   - For each agent in [agents], call build_client on its named [llm.*] entry,
     call load_class on its class value, instantiate with (client=..., model=...).
   - Construct Orchestrator(analyst=analyst).
   - Print resolved wiring: agent class name and base_url.
   - Wire main() as __main__ entry: if __name__ == "__main__": main().

6. Update isj/tests/test_analyst.py:
   - All Analyst() calls gain client=MagicMock() and model="gpt.oss.120b".
   - Add test_analyst_stores_client_and_model asserting both instance attributes.
   - Existing tests (signature, NotImplementedError, prompt, reusable, load_class) updated.

7. Verify:
   uv run --directory isj pytest tests/test_analyst.py -v
   uv run --directory isj python -m isj_agent.cli --config config.example.toml
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
tomllib (stdlib) used for TOML parsing. CLI default config path resolves relative to cli.py so it works from any cwd. build_client raises RuntimeError if api_key_env is set but the named env var is missing. CLI output verified: analyst, endpoint, model all print correctly from config.example.toml.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added named LLM profiles to config.example.toml (base_url, model, optional api_key_env with EMPTY fallback); updated Analyst.__init__ to accept client+model; added build_client() to config.py; added Orchestrator stub and CLI that reads config, wires agents, and prints resolved wiring. 6 tests pass; CLI runs cleanly end-to-end.
<!-- SECTION:FINAL_SUMMARY:END -->
