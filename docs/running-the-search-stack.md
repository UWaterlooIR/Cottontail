# Running the JSONL search stack (CLI · server · agent)

This is the **single source for how to run** the JSONL search tools: the index and
query CLIs, the HTTP server, and the example LLM agent. Commands here are
copy-paste runnable. For *why* and the full contract, each section links to its
design spec — keep run instructions here so the README and `CLAUDE.md` can link in
without drifting.

**Prerequisites:** a working build. The toolchain (bazelisk/Bazel, a C++ compiler,
zlib) and the build/test basics are in [`CLAUDE.md`](../CLAUDE.md) (*Prerequisites*
and *Build*).

The pieces fit together in a line:

```
*.jsonl  ──index──▶  corpus.burrow  ──▶  query CLI         (one-off searches)
                                    ──▶  HTTP server  ──▶  LLM agent / your code
```

## 0. Build the binaries

```sh
bazel build -c dbg --cxxopt="-Og" \
  //apps:cottontail-jsonl-index \
  //apps:cottontail-jsonl-query \
  //apps:cottontail-jsonl-server
```

Binaries land in `bazel-bin/apps/`. (These targets build cleanly; they are not
affected by the Boost issue that blocks a bare `//...` build — see `CLAUDE.md`.)

## 1. Index a corpus → a burrow — `cottontail-jsonl-index`

```sh
bazel-bin/apps/cottontail-jsonl-index --input <dir-of-jsonl> --burrow corpus.burrow
```

- `--input <dir>` recurses for `*.jsonl` / `*.jsonl.gz`; **one JSON row = one document**.
- `--docid-field` / `--contents-field` (default `docid` / `contents`) name the row fields.
- `--stem porter` also builds a stemmed stream — required for `--stem` queries later.
- `--tokenizer ascii|utf8` (default `utf8`, Unicode-aware).
- `--overwrite`, `--limit <n>`, `--strict`, `--verbose` for build control.

A `*.burrow` is a local working index and is gitignored. Full options and the
indexing model: [cli-spec §3](cottontail-jsonl-cli-spec.md).

## 2. Query from the command line — `cottontail-jsonl-query`

```sh
# ranked text search (cover-density; no precomputed stats)
bazel-bin/apps/cottontail-jsonl-query --burrow corpus.burrow --text "climbing rope" --top-k 10

# structured GCL search (full operator set: Boolean, phrase, proximity, containment, negation)
bazel-bin/apps/cottontail-jsonl-query --burrow corpus.burrow --gcl '(^ carabiner belay)'

# dry-run term diagnostics (document frequency per term) — cheap, no ranking
bazel-bin/apps/cottontail-jsonl-query --burrow corpus.burrow --explain --text "carabiner belay"

# other actions
bazel-bin/apps/cottontail-jsonl-query --burrow corpus.burrow --count --text "carabiner belay"
bazel-bin/apps/cottontail-jsonl-query --burrow corpus.burrow --get shard_00016_68307
bazel-bin/apps/cottontail-jsonl-query --describe        # LLM tool schema as JSON (no burrow)
```

Options: `--ranker icover|ssr|tiered` (text only), `--top-k N`, `--stem`,
`--full-text`, `--snippet-chars N`, `--format json|jsonl`, `--batch` (one query
object per stdin line → JSONL). Run with `--help` for the authoritative list. Full
options + output schema: [cli-spec §4](cottontail-jsonl-cli-spec.md).

## 3. Run the HTTP server — `cottontail-jsonl-server`

Exposes the same actions over HTTP/JSON, opening the burrow once and reusing it
across requests (a clone-per-thread pool).

```sh
bazel-bin/apps/cottontail-jsonl-server --burrow corpus.burrow
# → cottontail-jsonl-server listening on 127.0.0.1:8080 ...
```

| Flag | Default | Meaning |
|---|---|---|
| `--burrow <path>` | *(required)* | the index to serve |
| `--host <addr>` | `127.0.0.1` | bind address (loopback by default) |
| `--port <n>` | `8080` | listen port |
| `--threads <n>` | `4` | concurrent query handlers |
| `--token <t>` | — | bearer token; prefer the env var below |
| `--no-auth` | — | disable auth (loopback dev only) |

**Auth:** optional on loopback; a non-loopback bind is refused unless you set a
token (`COTTONTAIL_API_TOKEN` env var — preferred — or `--token`) or pass
`--no-auth`.

**Access log (stderr):** every request is logged at intake, **before** it is
handled — `[req] <method> <path> body=<json>` — so a request that crashes the
process mid-handling still leaves its query in the log; each completed request
then logs a summary — `[res] <method> <path> -> <status> (<bytes> bytes)`. The
request body (the query/params) is logged; the `Authorization` header (bearer
token) is not. Lines from concurrent workers are serialized so they don't
interleave.

**Endpoints:** `GET /healthz` (public), `GET /describe`, and `POST /tools/<name>`
for `search_text` · `search_gcl` · `explain` · `get_document` · `count_matches`.

```sh
curl http://127.0.0.1:8080/healthz
curl -s -X POST http://127.0.0.1:8080/tools/search_text \
  -H 'Content-Type: application/json' -d '{"query":"climbing rope","top_k":3}'
```

Full contract: [server-spec](cottontail-search-server-spec.md). Concurrency design:
[threadpool-spec](cottontail-server-threadpool-spec.md).

## 4. Run the example LLM agent — `examples/agent/`

A minimal ReAct loop that lets an LLM drive the search tools via native function
calling. It can talk to a **running server** (`--server-url`) or shell out to the
**query binary** directly (`--burrow`).

The agent has its own complete how-to — Python/`uv` setup, serving the model with
vLLM, and every flag — in **[`examples/agent/README.md`](../examples/agent/README.md)**
(its single source). Minimal run against a running server:

```sh
uv run --project examples/agent python examples/agent/search_agent.py \
  --server-url http://127.0.0.1:8080 \
  --model <served-model-name> --base-url http://127.0.0.1:8000/v1 \
  --question "What is the best rope for climbing?" --verbose
```

Or run directly against a burrow with no server — the agent shells out to the
query binary (§0) for each tool call. Pass `--burrow` (and `--query-bin` if it is
not on your `PATH`) instead of `--server-url`:

```sh
uv run --project examples/agent python examples/agent/search_agent.py \
  --burrow corpus.burrow \
  --query-bin bazel-bin/apps/cottontail-jsonl-query \
  --model <served-model-name> --base-url http://127.0.0.1:8000/v1 \
  --question "What is the best rope for climbing?" --verbose
```

Supply exactly one of `--server-url` (HTTP) or `--burrow` (subprocess).

Useful flags: `--trace` (tool-call summary after the run), `--verbose` (live
transcript: each LLM round-trip with the full request messages and reply payload
plus timing/tokens, assistant text, tool calls, and full observations),
`--max-steps`, `--reasoning low|medium|high`.

Design and rationale: [search-agent-spec](cottontail-search-agent-spec.md). The
forward-looking RISC direction (triage/mine/reformulate): [agentic-gcl-search-spec](agentic-gcl-search-spec.md).
