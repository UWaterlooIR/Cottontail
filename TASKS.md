# Tasks

## Done

### Server concurrency: clone-per-thread pool (`--threads`)

Per `docs/cottontail-server-threadpool-spec.md`. `cottontail-jsonl-server` serves
requests concurrently via a fixed pool of pre-cloned Warrens (no engine or handler
changes).

- [x] `WarrenProvider` → fixed pool of N pre-cloned warrens: checkout/checkin
      under a brief lock, query runs lock-free, RAII check-in, block (backpressure)
      when exhausted. Pre-cloned once at startup.
- [x] `--threads N` flag (default 4); pool built after `open_burrow()`.
- [x] cpp-httplib worker pool sized to match (`new_task_queue` / `ThreadPool`).
- [x] Concurrency test (`JsonlServer.ConcurrentRequests`): 8 client threads x 600
      requests against a 4-handler pool, all correct, no deadlock.
- [x] Full gate green; ThreadSanitizer clean on the concurrency test (run with
      `setarch -R` to satisfy TSan's memory layout in this sandbox).

### Search server: HTTP/JSON over jsonl_core (`cottontail-jsonl-server`)

Per `docs/cottontail-search-server-spec.md`. A long-lived HTTP server (cpp-httplib)
that opens the burrow once and serves the tool actions over the identical JSON
contract as the CLI.

- [x] Factor the JSON serialization into a shared `apps/jsonl_json.{h,cc}` used by
      both the query CLI and the server (no contract drift); CLI tests still green.
- [x] `cottontail-jsonl-server`: `GET /healthz` (public), `GET /describe`, and
      `POST /tools/<name>` for the five actions; thin layer over `jsonl_core`.
- [x] Bearer-token auth (optional on loopback, required on a non-loopback bind;
      fail-safe refuse-to-start), env `COTTONTAIL_API_TOKEN` (or `--token`),
      constant-time compare, no logging of the header. Loopback default; no TLS
      (deployment-layer tunnel/proxy).
- [x] `WarrenProvider`: single shared Warren serialized by a mutex now,
      structured for a clone-per-thread pool later (no handler changes).
- [x] `cpp-httplib` via MODULE.bazel; `cc_binary` //apps:cottontail-jsonl-server.
- [x] e2e test `test/jsonl_server.cc` (auth/search/get/count/malformed/describe)
      — `//test:jsonl_server_test`. Full gate green.
- [x] Example agent HTTP mode (`--server-url`, token via env) — transport swap,
      same contract.

### Search-agent tooling: flesh out the query CLI + an LLM-driven example

Per `docs/cottontail-search-agent-spec.md`. Build the CLI action surface first
(the example agent depends on it), then the Python ReAct agent.

CLI core (C++, `apps/jsonl_core.*` + `cottontail-jsonl-query`):
- [x] `get_document` — `--get <docid>` / `jsonl_get()`: find the `:item` whose
      `:docno` matches the docid (exact-string guard), return the body. found:false
      (exit 0) for unknown docid. (§3.1)
- [x] `count_matches` — `--count` / `jsonl_count()`: count `:item` containers that
      match the query (AND for text, the expr for gcl; honors `--stem`). (§3.3)
- [x] `result_count` + `truncated` (`result_count == top_k`) on search output. (§3.2)
- [x] `--describe`: emit the OpenAI/Anthropic tool schema for search_text /
      search_gcl / explain / get_document / count_matches, GCL cheatsheet embedded. (§3.4/§4)
- [x] Tests: get (found/not-found/subset-guard), count, truncated, --describe shape.
- [x] Keep `bazel test //test:tests //test:hazel_test //test:jsonl_test` green.

Example agent (Python uv project, `examples/agent/`):
- [x] ReAct loop via vLLM OpenAI-compatible endpoint + native tool calling
      (gpt-oss-120b on 127.0.0.1:8000, validated 2026-06-13); loads tools from
      `--describe`; step budget; cites docids. (§5)
- [x] Stub-LLM harness test (deterministic, no GPU) — `test_agent.py`. Manual
      real-model smoke is a human step (see `examples/agent/README.md`). (§5.4)
- [x] uv project: `pyproject.toml` + `uv.lock` (Python ≥3.12); `.venv` gitignored.

### Tokenizer choice: `--tokenizer ascii|utf8` for the index CLI

The indexer can build either an ASCII or a Unicode-aware (`utf8`) index. The query
tool needs no flag — it reconstructs the tokenizer (and any `stemming` wrapper)
from the burrow's dna, so query-time tokenization always matches the index.

- [x] `--tokenizer <ascii|utf8>` on `cottontail-jsonl-index`
      (`IndexOptions.tokenizer`), **default `utf8`**.
- [x] `jsonl_index` builds the inner tokenizer from the choice; an unknown value
      is a reported error.
- [x] `--stem` wraps the **selected** inner tokenizer (all four combos: ascii,
      utf8, ascii+stem, utf8+stem).
- [x] Build summary reports `"tokenizer"`.
- [x] Query tool: no new flag; verified over `utf8` and `stemming(utf8,…)`
      burrows (`JsonlTokenizer.*`).
- [x] Docs: `cli-spec` §3.2/§3.4 updated (and stale "no --stemmer" note fixed);
      `stemming.md §6` non-ASCII caveat relaxed.
- [x] Tests: accented-word whole-token (utf8) vs split (ascii); default-is-utf8;
      utf8+stem recall; unknown-tokenizer error (`JsonlTokenizer.*` in
      `test/jsonl.cc`).
- [x] `bazel test //test:tests //test:hazel_test //test:jsonl_test` green
      (existing ASCII-English fixtures tokenize equivalently under the utf8
      default — suite stayed green).

### Stemming CLI: expose opt-in stemming through the JSONL CLIs

### Stemming CLI: expose opt-in stemming through the JSONL CLIs

Query/index CLI surface for the merged `StemmingTokenizer`
(`src/stemming_tokenizer.*`, in `main` via PR #2), per `docs/stemming.md`.

- [x] `cottontail-jsonl-index --stem <name>`: build with the `stemming`
      tokenizer (wrapping `ascii`/`noxml` + the named stemmer) instead of plain
      `ascii`; report `"stemmer"` in the build summary.
- [x] `cottontail-jsonl-query --stem`: stem query terms into `porter:` GCL atoms
      and rank via `ssr` (cover density). Works for `--text` and `--gcl`;
      unstemmable terms fall back to their exact surface atom.
- [x] Detect a stemmed stream by the burrow's dna tokenizer name (`stemming`);
      `--stem` against a non-stem burrow exits 2 (no silent fallback).
- [x] Search output: add `"stemmed": true|false`. `--explain`: per-leaf
      `"stream"` (`exact`|`stemmed`) and df from that stream.
- [x] Tests: stemmed recall, exact preserved, no-op fallback, missing-stream
      error, over-stem pinned, explain stream labeling (`JsonlStem.*` in
      `test/jsonl.cc`; `--stem` build+query and exit-2 in `test/jsonl_cli.cc`).
- [x] `bazel test //test:tests //test:hazel_test //test:jsonl_test` green.

Mechanism note: the engine only stems inside `icover` (not `ssr`/`--gcl`), so we
stem in `jsonl_core` and target the stemmed stream via GCL atoms — no core change,
no use of `Warren::set_stemmer()` (which persists to dna).
