# isj — Agentic ISJ Investigation Planner

This is the implementation of the agentic ISJ (Interactive Searching and
Judging) system described in
[`docs/agentic-isj-investigation-planner.md`](../docs/agentic-isj-investigation-planner.md).
Read that document first — it is the authoritative specification.

This is a TREC RAG 2026 primary-system deliverable, not an example or demo.

## Project layout

```
isj/
  config.example.toml   Reference config — copy to config.toml and edit
  config.toml           Your local config (git-ignored)
  isj_agent/            Importable Python package
    agents/             LLM-role wrappers (Analyst, …) with bundled prompts
    protocol/           Typed artifacts (Intents, …)
    engine/             Deterministic engine modules (Searcher, Bookkeeper, …)
    config.py           load_class() and build_client() utilities
    cli.py              Entry point
    orchestrator.py     Orchestrator (stub)
  tests/                pytest suite
```

## Prerequisites

- **uv** — Python package manager. Install from https://docs.astral.sh/uv/
- **A running vLLM instance** — the CLI talks to a vLLM OpenAI-compatible
  endpoint. For local use, the default is `http://127.0.0.1:8000/v1`.

## Setup

**1. Install dependencies** (from the repo root):

```sh
uv sync --project isj
```

**2. Create your config file:**

```sh
cp isj/config.example.toml isj/config.toml
```

Edit `isj/config.toml` to match your vLLM instance:

```toml
[llm.default]
base_url = "http://127.0.0.1:8000/v1"
model = "gpt.oss.120b"        # must match --served-model-name on your vLLM instance
# api_key_env = "MY_API_KEY"  # omit for unauthenticated local endpoints
```

**3. Set your API key** (if your vLLM endpoint requires one):

```sh
export MY_API_KEY="your-key-here"
```

If `api_key_env` is not set in `config.toml`, the key defaults to `"EMPTY"`,
which works for unauthenticated local vLLM instances.

## Running the CLI

The CLI runs the Analyst over a set of questions and pretty-prints, for each,
the question and the Analyst's ordered interpretations of what the user is
asking for. From the repo root:

```sh
# Analyze the built-in sample questions:
uv run --directory isj python -m isj_agent.cli

# Or analyze your own questions:
uv run --directory isj python -m isj_agent.cli "your question" "another question"
```

`config.toml` (the CLI's default config path) selects the LLM endpoint and the
Analyst implementation. Output for each question looks like:

```
Q: <the question>
  1. <most likely interpretation>
  2. <an alternate interpretation>
```

## Running tests

```sh
# From the repo root:
uv run --directory isj pytest tests/ -v

# Or from inside isj/:
uv run pytest tests/ -v
```

## Status

The `Analyst` is implemented: `analyze()` makes a single guided-decoding LLM
call and returns an `Intents` object (the question plus an ordered list of
interpretations). The `Orchestrator` is still a stub. The richer INP / CM / IP
pipeline from the design spec is shelved in favor of the simpler `Intents`
output (see the agent design decision docs under `backlog/docs/`).
