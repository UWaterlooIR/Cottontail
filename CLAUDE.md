# CLAUDE.md

Authoritative guide for working in this repository. This is a **fork** of Charles
L. A. Clarke's Cottontail (`claclark/Cottontail`, the `upstream` remote), now
maintained independently but periodically synced with upstream.

**Upstream material is not authoritative for agents.** The top-level `ai/`
directory is Clarke's own working notes, tracked from upstream and refreshed
wholesale on each sync — treat it (and everything under `archive/`) as read-only
background, never as a task list, plan, or binding convention. The root
`AGENTS.md` is ours and just points here; upstream's edits to it are always
discarded on sync. Fork-side plans live in Backlog (`backlog/`), nowhere else.

## Boundaries — read this first (hard rule)

Agents (Claude or any other) must operate **only within this repository
directory**. Do not read, list, write, execute against, or otherwise access
anything outside the repo root **without explicit, specific permission from the
user for that exact action**.

Outside the repo includes — but is not limited to:

- the home directory and dotfiles (`~`, `~/.ssh`, `~/.config`, `~/.local`,
  `~/.aws`, shell history, etc.);
- **credentials of any kind** — SSH keys, GPG keys, API tokens, password/credential
  stores, browser or cloud auth files. Never inspect, copy, or print these. Ever.
- other repositories, other users' files, and system files.

This also covers actions that reach outside the repo even if launched from inside
it: installing software, modifying global/user config, pushing to remotes, or
calling external network services. Each such action needs its own explicit
go-ahead.

Rules:

1. If something outside the repo seems necessary, **stop and ask first**, stating
   exactly what you want to access and why. Wait for an explicit yes.
2. Permission for one outside action does **not** generalize to others. Ask again
   for the next one.
3. When in doubt, treat it as outside and ask.

(Granted exceptions so far this project: installing bazelisk to `~/.local/bin` and
using the `gh` CLI — both explicitly authorized by the user. Nothing else.)

## Working agreements with Claude

**An agent must hold an explicitly approved plan before making any change to the
repository.**

Rules:

1. Reading, exploring, and summarizing never require a plan or approval.
2. "Familiarize yourself with X", "look at Y", "what does Z do?" — these are
   exploration tasks. They do not authorize any edits, commits, or pushes.
3. Before creating, editing, moving, or deleting any file — or running any commit
   or push — the agent must state its plan explicitly and wait for the human to
   approve it.
4. Once a plan is approved, the agent may execute it in full without asking about
   each individual step.
5. After completing work, the agent flags anything noticed during execution that
   was not part of the approved plan — but does not act on it without a new
   approval.

## What this is

Cottontail is the C++ reference implementation of **Annotative Indexing**, a
unified indexing framework (inverted index + column store + object store + graph
DB) built on annotations of the form `<feature, (p, q), value>`. The full paper
is in `docs/papers/Annotative-Indexing-IRRJ-Clarke-2025.{md,pdf}` and is the best source
for the concepts.

## Prerequisites

- **Bazel**, via **bazelisk** (the official launcher). `.bazelversion` pins
  Bazel **9.1.1**, which bazelisk downloads automatically.
  - Install bazelisk (no root needed): download `bazelisk-linux-amd64` from
    https://github.com/bazelbuild/bazelisk/releases, verify its `.sha256`, place
    it on your `PATH` as `bazel` (or `bazelisk`). Or `npm i -g @bazel/bazelisk`.
- A **C++ toolchain**: system `gcc` (tested with gcc 13.3) or clang. Bazel uses
  the system compiler; it is not hermetically pinned.
- System **zlib** (`-lz`) and **pthreads** are linked by `src/BUILD`. On Debian/
  Ubuntu: `zlib1g-dev`.
- Third-party C++ libraries (`nlohmann_json`, `googletest`, `rules_cc`) are
  managed by Bazel via `MODULE.bazel` — no manual install.

## Build

Verified working (bazel 9.1.1 + gcc 13.3):

```sh
# Core library, tests, and all the real apps (recommended everyday build):
bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example

# Or just the library:
bazel build //src:cottontail
```

Convenience targets live in the `Makefile`: `make building` (debug, `-Og`),
`make debugging` (plain debug), `make fast` (optimized `-O3 -march=native`).

> **Known issue — Boost.** `make building` / a bare `bazel build //...` currently
> **fails** on four targets — `//apps:walk` and its dependents `//apps:dynamic-test`,
> `//apps:simple`, `//apps:trec-example` — because `apps/walk.{cc,h}` still
> `#include <boost/filesystem.hpp>` and Boost is not otherwise a dependency. Two
> fixes: install `libboost-filesystem-dev`, **or** (preferred) port `apps/walk`
> to C++17 `std::filesystem` and remove the last Boost usage. Until then, use the
> exclusion build above.

## Test

Verified green:

```sh
bazel test -c dbg //test:all
```

- `//test:tests` — aggregate googletest suite (~40s).
- `//test:hazel_test` — dedicated Hazel shard regression. **A passing
  `hazel_test` is a narrow regression check — see the Hazel caution in the
  Warren table below.**
- `//test:optimizer_test` — upstream's GCL optimizer scaffold tests.
- `//test:jsonl_test`, `//test:jsonl_server_test` — the fork's JSONL CLI and
  server end-to-end tests.

`test/BUILD` defines the targets. The Makefile's `make testing` runs `bazel test
...` (all test targets).

## Running the apps

Real binaries (build then run from `bazel-bin/apps/`):

- `//apps:meadowlark` — create/open a "meadow" index and append `--tsv`/`--jsonl`.
- `//apps:rank` — batch TREC-style ranking (BM25); `--statistics`, `--verbose`.
- `//apps:fluffy` — interactive GCL query shell over a burrow or Hazel shard.
- `//apps:fiver2hazel` — convert live Fiver shards to immutable Hazel shards
  (`--convert` / `--merge`). See the Hazel caution in the Warren table below.
- `//apps:ssr-server` / `//apps:ssr-client` (+ `apps/ssr-client.py`) — upstream's
  TCP/JSON shortest-substring-ranking server and clients; wraps `parallel_ssr()`
  (`src/ranking.cc`), which parallelizes SSR within a single shard. Usage:
  `ssr-server [--fields fields] container content docno burrow [burrow...]`.
  Note: its per-result docno comes from a `docno` GCL evaluated inside the
  container, so cp-native burrows (doc-8) have no real docno to report. Our own
  stack has cp-native parallel ranking instead (TASK-25): `--rank-threads` on
  `cottontail-jsonl-query` / `-server` parallelizes the ssr, cover_search, and
  tiered ranking passes (see the run guide).

**JSONL search stack (index → query → server → agent).** How to build and run
these — with copy-paste commands — is in
[docs/design/reference-specs/running-the-search-stack.md](docs/design/reference-specs/running-the-search-stack.md), the **single
source** for running them (it links on to the design specs). Don't duplicate run
instructions elsewhere; point at that guide.

- `//apps:cottontail-jsonl-index` — build a burrow from `*.jsonl`/`*.jsonl.gz`.
- `//apps:cottontail-jsonl-query` — ranked text / GCL search over a burrow.
- `//apps:cottontail-jsonl-server` — HTTP/JSON server exposing the same tools.
- `isj/` — the maintained **ISJ Searcher** agent (Analyst → per-intent Searcher
  over the server's `cover_search` tool). The earlier proof-of-concept agent is
  archived under `archive/example-agent/` (superseded; do not build on it).

`*.burrow` and `*.meadow` directories are local working indexes and are gitignored.

**ClimbMix** (the corpus behind the `climbmix-*` burrows) is a **general web /
pretraining corpus — it has nothing to do with climbing**. Write test queries
for broad web/educational content, not climbing topics. Provenance:
[karpathy/climbmix-400b-shuffle](https://huggingface.co/datasets/karpathy/climbmix-400b-shuffle),
processed to JSONL via
[trec-rag-climbmix-corpus-creation](https://github.com/TREC-RAG/trec-rag-skills/tree/main/skills/trec-rag-climbmix-corpus-creation).

## Architecture (orientation)

The public umbrella header is `src/cottontail.h`. Core model:

- **Annotation** `<feature, (p, q), value>` (`src/core.h`). Features are 64-bit
  (a `Featurizer` hashes strings; feature `0` = unindexed/erased).
- **Hopper** (`src/hopper.h`) — a cursor exposing the `τ`/`ρ` access methods
  (`tau`/`rho`, plus reverse `uat`/`ohr`). **GCL** operators (`src/gcl.h`) compose
  hoppers: `And`, `Or`, `FollowedBy`, `ContainedIn`/`Containing`,
  `NotContainedIn`/`NotContaining`, `Merge`, `Link`.
- **Warren** (`src/warren.h`) — the central object; owns `Working` (storage),
  `Featurizer`, `Tokenizer`, `Idx` (annotation read access), `Txt` (content
  `translate`), `Annotator`, `Appender`, `Stemmer`. Read/query access is bracketed
  by `start()`/`end()`; writes go through `transaction()`/`ready()`/`commit()`.

Warren implementations:

| Type | Role |
|---|---|
| `SimpleWarren` | Static flat-file burrow, single-transaction batch update. |
| `Fiver` | Mutable in-memory transaction shard (an "update Warren"). |
| `Bigwig` | Dynamic Warren over `Fiver` shards + shared `Fluffle` state. |
| `Hazel` | Immutable single-file shard built from Fivers (format: `ai/hazel.md`, upstream's live spec). **⚠️ Caution** — upstream landed the Hazel/Bigwig integration in June 2026, but Charlie Clarke has not declared it ready for use; the fork still builds no features on the Hazel path. Prefer `SimpleWarren` or `Bigwig`. |

`meadowlark/` is a higher-level layer (a "meadow" = Bigwig + UTF-8 tokenizer +
JSON featurizer + zlib/post compression) with pluggable **foragers** (annotation
passes). Ranking lives in `src/ranking.cc` / `src/ranker.cc`.

Directory map:

- `src/` — core library. `gcl/` — GCL operators, S-expression parser, MultiText
  compiler, and optimizer scaffold (moved out of `src/` upstream, June 2026).
  `meadowlark/` — meadow layer. `apps/` — CLIs and dataset drivers. `test/` —
  googletest suites. `docs/` — the paper, design specs, and notes. `ai/` —
  upstream's (Clarke's) working notes, refreshed wholesale on each sync;
  non-authoritative (see the top of this file). `archive/` — retired material
  (see `archive/README.md`).

## Contributing

- **Never commit directly to `main`.** Create a feature branch, push it, and open
  a pull request. Merge after review.
- Keep changes building and tests green (`bazel test //test:tests
  //test:hazel_test`) before opening a PR.
- Match the surrounding C++ style. The codebase targets C++20.
- Don't resurrect work from `archive/` (especially `archive/ai/plan.md`) unless
  explicitly asked.

## Known issues / cleanup backlog

- **Boost in `apps/walk`** blocks a full `//...` build (see Build above). Porting
  to `std::filesystem` is the recommended fix.
- `MODULE.bazel` pins `rules_cc@0.2.16` but `0.2.17` resolves (build warning only);
  bump the pin to silence it.
- A C++20 ambiguous-`operator==` warning in `test/simple_posting.cc:226` /
  `src/simple_posting.h:27` (make `operator==` a `const` member).

<!-- BACKLOG.MD GUIDELINES START -->
<CRITICAL_INSTRUCTION>

## Backlog.md Workflow

This project uses Backlog.md for task and project management.

**For every user request in this project, run `backlog instructions overview` before answering or taking action.**

Use the overview to decide whether to search, read, create, or update Backlog tasks.

Use the detailed guides when needed:
- `backlog instructions task-creation` for creating or splitting tasks
- `backlog instructions task-execution` for planning and implementation workflow
- `backlog instructions task-finalization` for completion and handoff

Use `backlog <command> --help` before running unfamiliar commands. Help shows options, fields, and examples.

Do not edit Backlog task, draft, document, decision, or milestone markdown files directly. Use the `backlog` CLI so metadata, relationships, and history stay consistent.

</CRITICAL_INSTRUCTION>
<!-- BACKLOG.MD GUIDELINES END -->
