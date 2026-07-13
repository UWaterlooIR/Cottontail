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
- `--docno-field` / `--text-field` (default `docid` / `contents`) name the row fields.
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
bazel-bin/apps/cottontail-jsonl-query --burrow corpus.burrow --get 68307   # by cp (integer) from a prior result; reports its docno
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
for `search_text` · `search_gcl` · `cover_search` · `tiered_query_search` ·
`multitext_tiered_search` · `get_document` · `count_matches`. The isj agent drives
`cover_search` (or the tiered/multitext variants) and `get_document`.

```sh
curl http://127.0.0.1:8080/healthz
curl -s -X POST http://127.0.0.1:8080/tools/search_text \
  -H 'Content-Type: application/json' -d '{"query":"climbing rope","top_k":3}'
```

Full contract: [server-spec](cottontail-search-server-spec.md). Concurrency design:
[threadpool-spec](cottontail-server-threadpool-spec.md).

## 4. Run the ISJ Searcher — `isj/`

The maintained agent is the **ISJ Searcher** under [`isj/`](../../../isj/): an Analyst
(four interchangeable Searcher classes — plain cover, JSON tiered, the MultiText-DSL
program searcher, and the Lucindri/Indri searcher — selected in `config.toml`; see the
README) splits the question into interpretations, then a per-intent Searcher drives the
server's **`cover_search`** tool (search → read cover summaries → judge → reformulate),
with a **SearchCoach** shaping the between-query feedback, and the CLI streams a run-output
directory. One-time setup — the `uv` project, `config.toml`, and serving the model with
vLLM — is in **[`isj/README.md`](../../../isj/README.md)** (its single source).

Prerequisites: a **`--stem porter`** burrow (§1 — `cover_search`'s `word*` family
marker needs the stemmed stream), the **server** running over it (§3), and a
**vLLM** OpenAI-compatible endpoint. Point `isj/config.toml` at both (the `[engine]`
section — class + `base_url` [+ `burrow`] — and the `[llm.*]` endpoint). The searcher
class (`[agents.searcher]`, e.g. cover / tiered / MultiText / Lucindri) and the optional
`[coach]` feedback agent (TASK-40) are config too; see [`isj/README.md`](../../../isj/README.md).

```sh
# from the repo root, with the server (§3) and vLLM both up:
uv run --directory isj python -m isj_agent.cli \
  --question "What should I know about black bear attacks while hiking?" \
  --out runs/bear --verbose
```

Flags: exactly one of `--question "<q>"` (runs the built-in Analyst) or
`--analysis-file <report.json>` (a precomputed analysis; see below) is **required**;
`--out <dir>` (required), `--overwrite` (reuse a non-empty dir), `--verbose` (live
per-intent trace), `--burrow <path>` (override the served burrow whose
`docno-cp.sqlite` maps `cp`→`docno`).

### Reusable analysis — `isj analyze` → `--analysis-file` (TASK-41)

For research runs you usually want **one Analyst output per topic**, reused across every
searcher config, so analyst variation is factored out of cross-searcher comparisons. Run the
configured Analyst (`[agents.analyst]`) over a topics TSV once — it needs only the vLLM
endpoint, no server — to produce a directory of per-topic artifacts:

```sh
# id<TAB>question per line; writes <dir>/<topic_id>.json + <dir>/analysis.meta.json
uv run --directory isj python -m isj_agent.analyze \
  --topics topics.dev.tsv --out analysis/dev
```

Then drive each run from a topic's artifact instead of `--question` (the Analyst is skipped
entirely; the artifact carries the question + interpretations):

```sh
uv run --directory isj python -m isj_agent.cli \
  --analysis-file analysis/dev/rag2026-0.json --out runs/rag2026-0 --verbose
```

`isj analyze` flags: `--topics`/`--out` (required), `--config` (default `isj/config.toml`),
`--only <id>` (repeatable), `--limit N`, `--overwrite`. It is **resumable** — a topic whose
`<id>.json` already exists is skipped unless `--overwrite`. Each artifact is
`{topic_id, question, interpretations[], analyst{class,model,reasoning_effort,temperature}}`
(the analyst provenance travels with it); the shape is **analyst-agnostic**, so swapping
`[agents.analyst].class` changes only the contents. Two analysts ship: the default `Analyst`
(disambiguated interpretations) and `ReportAnalyst` (TASK-42), which decomposes the need into the
information components a RAG report must synthesize.

### Batch runs over many topics — `isj run_topics` (TASK-43)

To run several searcher arms over a whole topics file — driven by ONE shared analysis so the
Analyst's variation is out of the comparison — use the in-house batch runner. It runs each arm
via the CLI's `--analysis-file` (never `--question`), and by default **cycles the shard servers
per topic** (bring up → run every arm on that topic → tear down) because Cottontail's posting
cache is unbounded and never evicts (`src/simple_idx.h`), so leaving all shards up across a long
batch would OOM the box:

```sh
uv run --directory isj python -m isj_agent.run_topics \
  --run UWatMDS-gcl=configs/config-gcl-cover.toml \
  --run UWatMDS-mt=configs/config-multitext-tiered.toml \
  --topics topics.dev.tsv \
  --analyst-config configs/analyst.toml       # runs `isj analyze` up front; OR --analysis <prebuilt-dir>
```

Each `--run NAME=CONFIG` writes `results/<NAME>/<topic>/` (resumable per (arm, topic)) plus a
`results/<NAME>/run_manifest.tsv`; server lifecycle logs to `results/servers.log`. The servers are
torn down on normal exit, Ctrl-C (SIGINT), **and** `kill` (SIGTERM). Useful flags: `--no-cycle`
(servers already up — skip cycling), `--dry-run` (print the per-topic UP→arms→DOWN plan, touch
nothing), `--only ID` / `--limit N` / `--overwrite`, `--shard-ports 7000-7007`, and
`--cottontail <root>` (defaults to this checkout; point it elsewhere to run from another
Cottontail). `--healthz-timeout` / `--teardown-timeout` / `--settle` tune the cycle.

**Alternative backend — Lucindri (a Dirichlet-LM engine; TASK-33).** The engine is
config-selected, so the same agent runs over UWaterloo's Lucindri instead of
Cottontail with no code change. Start a `LucindriServer` (`--index <lucindri index>
--port 9000`) over the same corpus (docnos align), then point the config at it:

```toml
[engine]
class = "isj_agent.engine.lucindri.LucindriSearchEngine"
base_url = "http://127.0.0.1:9000"

[agents.searcher]
class = "isj_agent.agents.lucindri_searcher.LucindriSearcher"
# prompt = "isj/scouting/lucindri-query/lucindri_prompt_v4.txt"  # optional prompt override
```

The LucindriSearcher authors one full Lucindri query per turn (tool `submit_query`);
its bundled prompt teaches the query language self-contained. Lucindri is
docno-native (no burrow, no `docno-cp.sqlite`); the CLI polls its `/healthz` on
startup and fails fast if it is down. (The agent is docno-keyed for every engine —
the Cottontail engine translates `cp`↔`docno` internally.)

**Sharded Cottontail — `MultiShardSearchEngine` (TASK-34).** Split the corpus into N
sub-burrows and query them in parallel, merging by score into the true global top-k
(exact because the cover-density ranker is stats-free). Build the shards and launch one
server per shard, then point `[engine]` at the list:

```sh
scripts/build-test-shards.sh          # 4 sub-burrows over the first 100 shards (example)
scripts/launch-test-shard-servers.sh  # one server per part on ports 7000+
```

```toml
[engine]
class = "isj_agent.engine.multishard.MultiShardSearchEngine"
shards = [
  { base_url = "http://127.0.0.1:7000", burrow = "/share/indexes/climbmix_test_shards/part00.burrow" },
  { base_url = "http://127.0.0.1:7001", burrow = "/share/indexes/climbmix_test_shards/part01.burrow" },
  { base_url = "http://127.0.0.1:7002", burrow = "/share/indexes/climbmix_test_shards/part02.burrow" },
  { base_url = "http://127.0.0.1:7003", burrow = "/share/indexes/climbmix_test_shards/part03.burrow" },
]
```

Any shard error fails the whole search (no silent partial results); every shard's
`/healthz` is checked on startup. Works with every Cottontail searcher (cover / tiered /
multitext).

**Run output** (`<out>/`, written **incrementally** as the run proceeds — TASK-35):

- `activity.log` — human-readable stream of every event as it happens; `tail -f` it
  to watch a run live (or pass `--verbose` to mirror it to stdout). A killed or hung
  run still leaves a partial, inspectable log.
- `intents.json` — the question + the ordered interpretations (from the Analyst, or
  from the `--analysis-file` artifact).
- `intent-NN.json` — interpretation NN's judged, graded ranked list (ids as
  **docno**).
- `intent-NN.trace.jsonl` — interpretation NN's heavy event trace (one JSON object
  per line: per-turn LLM calls with token usage, searches, judgements, coach reports, …).
  Render it human-readably with `isj/scripts/traceview.py` (TASK-39).
- `errors.log` — present **only if something failed**; its **absence means the whole
  run succeeded**. The CLI exits non-zero iff it was written.

Contract and internals: [`isj/README.md`](../../../isj/README.md). (The earlier
proof-of-concept agent has been archived to
[`archive/example-agent/`](../../../archive/example-agent/) and is no longer maintained;
its design notes live in [search-agent-spec](../archive/cottontail-search-agent-spec.md).)
