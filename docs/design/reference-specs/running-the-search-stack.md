# Running the JSONL search stack (CLI · server · agent)

This is the **single source for how to run** the JSONL search tools: the index and
query CLIs, the HTTP server, and the example LLM agent. Commands here are
copy-paste runnable. For *why* and the full contract, each section links to its
design spec — keep run instructions here so the README and `CLAUDE.md` can link in
without drifting.

**Prerequisites:** a working build. The toolchain (bazelisk/Bazel, a C++ compiler,
zlib) and the build/test basics are in [`CLAUDE.md`](../../../CLAUDE.md) (*Prerequisites*
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

# other actions
bazel-bin/apps/cottontail-jsonl-query --burrow corpus.burrow --count --text "carabiner belay"
bazel-bin/apps/cottontail-jsonl-query --burrow corpus.burrow --get shard_00016_68307
bazel-bin/apps/cottontail-jsonl-query --describe        # LLM tool schema as JSON (no burrow)
```

Options: `--ranker icover|ssr|tiered` (text only), `--top-k N`, `--stem`,
`--full-text`, `--snippet-chars N`, `--format json|jsonl`, `--batch` (one query
object per stdin line → JSONL), `--rank-threads N` (threads inside one ranking
pass; default `0` = all allowed hardware threads — this CLI runs one query at a
time, so nothing multiplies). Run with `--help` for the authoritative list. Full
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
| `--rank-threads <n>` | `0` (auto) | threads inside ONE ranking pass (TASK-25) |
| `--token <t>` | — | bearer token; prefer the env var below |
| `--no-auth` | — | disable auth (loopback dev only) |

**Ranking parallelism (`--rank-threads`, TASK-25):** the ssr, cover_search, and
tiered_query_search ranking passes split the shard's token span across worker
threads (each range at least ~1M tokens; results and match counts are exactly
the sequential pass's). The two thread knobs multiply — `--threads` concurrent
handlers can each run a `--rank-threads`-wide ranking — so the default `0`
auto-budgets: `allowed hardware threads / --threads` (logged at startup, e.g.
`rank_threads=16 (auto)`). Set it explicitly only when you know the concurrency
profile. Workers share the process's single posting cache, so extra rank
threads add no memory or I/O, just CPU. It is a server-level setting: requests
cannot change it.

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
for `search_text` · `search_gcl` · `get_document` · `count_matches`.

```sh
curl http://127.0.0.1:8080/healthz
curl -s -X POST http://127.0.0.1:8080/tools/search_text \
  -H 'Content-Type: application/json' -d '{"query":"climbing rope","top_k":3}'
```

Full contract: [server-spec](cottontail-search-server-spec.md). Concurrency design:
[threadpool-spec](cottontail-server-threadpool-spec.md).

## 4. Run the ISJ Searcher — `isj/`

The maintained agent is the **ISJ Searcher** under [`isj/`](../../../isj/): an Analyst
(three interchangeable Searcher classes — plain cover, JSON tiered, and the
MultiText-DSL program searcher — selected in `config.toml`; see the README)
splits the question into interpretations, then a per-intent Searcher drives the
server's **`cover_search`** tool (search → read cover summaries → judge →
reformulate) and the CLI writes a run-output directory. One-time setup — the `uv`
project, `config.toml`, and serving the model with vLLM — is in
**[`isj/README.md`](../../../isj/README.md)** (its single source).

Prerequisites: a **`--stem porter`** burrow (§1 — `cover_search`'s `word*` family
marker needs the stemmed stream), the **server** running over it (§3), and a
**vLLM** OpenAI-compatible endpoint. Point `isj/config.toml` at both (the
`[cottontail_http_json_server]` base_url and the `[llm.*]` endpoint).

```sh
# from the repo root, with the server (§3) and vLLM both up:
uv run --directory isj python -m isj_agent.cli \
  --question "What should I know about black bear attacks while hiking?" \
  --out runs/bear --verbose
```

Flags: `--question` (required), `--out <dir>` (required), `--overwrite` (reuse a
non-empty dir), `--verbose` (live per-intent trace), `--burrow <path>` (override
the served burrow whose `docno-cp.sqlite` maps `cp`→`docno`).

**Run output** (`<out>/`):

- `intents.json` — the question + the Analyst's ordered interpretations.
- `intent-NN.json` — interpretation NN's judged, graded ranked list (ids as
  **docno**).
- `intent-NN.trace.jsonl` — interpretation NN's heavy event trace (one JSON object
  per line: per-turn LLM calls with token usage, searches, judgements, …).
- `errors.log` — present **only if something failed**; its **absence means the whole
  run succeeded**. The CLI exits non-zero iff it was written.

Contract and internals: [`isj/README.md`](../../../isj/README.md). (The earlier
proof-of-concept agent has been archived to
[`archive/example-agent/`](../../../archive/example-agent/) and is no longer maintained;
its design notes live in [search-agent-spec](../archive/cottontail-search-agent-spec.md).)
