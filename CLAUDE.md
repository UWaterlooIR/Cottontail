# CLAUDE.md

Authoritative guide for working in this repository. This is a **fork** of Charles
L. A. Clarke's Cottontail, now maintained independently. The original author's
agent notes and forward plans have been moved under `archive/` and are **not**
authoritative — do not treat them as a task list. The immediate goal of this fork
is to get *this* version building, tested, and running cleanly; it is **not**
continuing Clarke's in-progress Fiver/Hazel integration work.

## What this is

Cottontail is the C++ reference implementation of **Annotative Indexing**, a
unified indexing framework (inverted index + column store + object store + graph
DB) built on annotations of the form `<feature, (p, q), value>`. The full paper
is in `docs/Annotative-Indexing-IRRJ-Clarke-2025.{md,pdf}` and is the best source
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
bazel test -c dbg //test:tests //test:hazel_test
```

- `//test:tests` — aggregate googletest suite (~40s).
- `//test:hazel_test` — dedicated Hazel shard regression.

`test/BUILD` defines the targets. The Makefile's `make testing` runs `bazel test
...` (all test targets).

## Running the apps

Real binaries (build then run from `bazel-bin/apps/`):

- `//apps:meadowlark` — create/open a "meadow" index and append `--tsv`/`--jsonl`.
- `//apps:rank` — batch TREC-style ranking (BM25); `--statistics`, `--verbose`.
- `//apps:fluffy` — interactive GCL query shell over a burrow or Hazel shard.
- `//apps:fiver2hazel` — convert live Fiver shards to immutable Hazel shards
  (`--convert` / `--merge`).

`*.burrow` and `*.meadow` directories are local working indexes and are gitignored.

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
| `Hazel` | Immutable single-file shard built from Fivers (format: `docs/hazel-format.md`). |

`meadowlark/` is a higher-level layer (a "meadow" = Bigwig + UTF-8 tokenizer +
JSON featurizer + zlib/post compression) with pluggable **foragers** (annotation
passes). Ranking lives in `src/ranking.cc` / `src/ranker.cc`.

Directory map:

- `src/` — core library. `meadowlark/` — meadow layer. `apps/` — CLIs and dataset
  drivers. `test/` — googletest suites. `docs/` — the paper + `hazel-format.md`.
  `archive/` — prior author's non-authoritative notes (see `archive/README.md`).

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
