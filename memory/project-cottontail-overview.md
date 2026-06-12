---
name: project-cottontail-overview
description: What Cottontail is, how to build/test it, and the authoritative docs for this fork
metadata:
  type: project
---

Cottontail is the C++20 reference implementation of **Annotative Indexing** (paper:
docs/Annotative-Indexing-IRRJ-Clarke-2025.{md,pdf}). This is a **fork** of Charles
L. A. Clarke's repo, now owned by the user (see [[user-mark-smucker]]). Goal: get
*this* version building/tested/running cleanly — **not** continuing Clarke's
in-progress Fiver/Hazel `PostingIterator` integration.

**Authoritative doc is `/CLAUDE.md`** (build, test, contribute, architecture). The
top-level `AGENTS.md` is just a pointer to it. Clarke's old agent material
(his `AGENTS.md`, the whole `ai/` dir: architecture/plan/log/notes/hazel-* /
improvements) was moved to `archive/` and is **non-authoritative** — do not treat
`archive/ai/plan.md` as a task list. The one kept technical reference is the Hazel
on-disk format spec at `docs/hazel-format.md`.

Build/test (verified 2026-06-11, bazel 9.1.1 via bazelisk + gcc 13.3;
`.bazelversion` pins 9.1.1; deps nlohmann_json/googletest/rules_cc via MODULE.bazel;
system zlib `-lz` + pthreads):
- Build (excludes Boost targets): `bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example`
- Test (green): `bazel test -c dbg //test:tests //test:hazel_test`
- **Boost wrinkle:** a bare `//...` / `make building` fails only on `apps/walk.{cc,h}`
  (last `boost/filesystem` use) + its 3 dependents. Fix = port walk to
  std::filesystem (preferred) or install libboost-filesystem-dev.

Core model: annotation `<feature,(p,q),value>`; query via τ/ρ hoppers
(Hopper::tau/rho + reverse uat/ohr); GCL operators in src/gcl.h. Warren groups
components; implementations: SimpleWarren (static burrow), Fiver (mutable txn
shard), Bigwig (dynamic, Fiver shards + Fluffle), Hazel (immutable single-file
shard — **WIP, not ready for use**, see [[hazel-not-ready]]). null_feature=0 = erased/unindexed. meadowlark/ = higher-level "meadow"
layer; ranking in src/ranking.cc + src/ranker.cc.

Workflow: **feature branches + PRs, never commit directly to main** (the user
endorsed this; an earlier memory/.claude commit went to main before the rule was
set — fine, going forward we branch). See [[memory-location]] for where memory lives.
