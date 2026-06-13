# Example: an LLM search agent over a Cottontail burrow

A minimal ReAct loop that lets an LLM drive `cottontail-jsonl-query` as a set of
tools (search / structured search / explain / read-document / count) via native
function calling. It is a **reference example**, not production — see
`docs/cottontail-search-agent-spec.md` for the design and the eventual server.

Python here is a [**uv**](https://docs.astral.sh/uv/) project (`pyproject.toml` +
`uv.lock`, pinned to Python ≥3.12). `uv sync` creates the `.venv` and installs the
locked deps; `uv run` executes inside it — no manual venv or `pip install`.

```sh
uv sync --project examples/agent      # one-time: build .venv from uv.lock
```

## 1. Build the query binary

```sh
bazel build -c dbg --cxxopt="-Og" //apps:cottontail-jsonl-query
# -> bazel-bin/apps/cottontail-jsonl-query
```

## 2. Index a corpus

```sh
bazel-bin/apps/cottontail-jsonl-index --input <dir-of-jsonl> --burrow corpus.burrow
# add --stem porter for morphological recall, --tokenizer ascii for byte tokens
```

## 3. Serve the LLM with vLLM (validated 2026-06-13 on a 96 GB Blackwell)

```sh
CUDA_VISIBLE_DEVICES=1 CUDA_DEVICE_ORDER=PCI_BUS_ID \
vllm serve openai/gpt-oss-120b --served-model-name gpt-oss-120b \
  --host 127.0.0.1 --port 8000 --download-dir /share/huggingface-models/ \
  --max-model-len 131072 --enable-auto-tool-choice --tool-call-parser openai \
  --gpu-memory-utilization 0.92
```

`--model` passed to the agent must match `--served-model-name`.

## 4. Run the agent

```sh
uv run --project examples/agent python examples/agent/search_agent.py \
  --burrow corpus.burrow \
  --query-bin bazel-bin/apps/cottontail-jsonl-query \
  --model gpt-oss-120b \
  --base-url http://127.0.0.1:8000/v1 \
  --question "Where did elephants disappear from, and when?" \
  --trace
```

(Paths are relative to the repo root; `--project examples/agent` selects the uv
environment.)

It prints the final answer and the cited docids; `--trace` shows the tool calls
on stderr. Other flags: `--max-steps` (tool-call budget), `--reasoning low|medium|high`.

## Test (no GPU / no network)

The loop logic is covered by a stub-LLM harness test:

```sh
uv run --project examples/agent python examples/agent/test_agent.py
```

It stubs both the model and the tool executor, asserting that tool calls run in
order, observations are fed back, citations are harvested, and the loop stops on a
final answer or the step budget. (The C++ regression net for the CLI itself lives
in `//test:jsonl_test`.)
