---
name: project-cottontail-overview
description: What Cottontail is, how to build/test it, and the authoritative docs for this fork
metadata:
  type: project
---

Cottontail is the C++20 reference implementation of **Annotative Indexing** (paper:
docs/papers/Annotative-Indexing-IRRJ-Clarke-2025.{md,pdf}). This is a **fork** of Charles
L. A. Clarke's repo (`claclark/Cottontail` = the `upstream` remote), owned by the
user (see [[user-mark-smucker]]) and periodically synced with upstream (last:
2026-07-03, see [[upstream-sync-claclark]]).

**Authoritative doc is `/CLAUDE.md`** (build, test, contribute, architecture). The
top-level `AGENTS.md` is ours and just points to it; upstream's AGENTS.md edits
are discarded on every sync. The top-level `ai/` dir is Clarke's live working
notes, refreshed wholesale from upstream on each sync — **non-authoritative**,
never a task list (same for `archive/`). The Hazel format spec is upstream's
`ai/hazel.md`.

Build/test (verified 2026-07-03, bazel 9.1.1 via bazelisk + gcc 13.3;
`.bazelversion` pins 9.1.1; deps nlohmann_json/googletest/rules_cc via MODULE.bazel;
system zlib `-lz` + pthreads):
- Build (excludes Boost targets): `bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example`
- Test (green, 5 targets): `bazel test -c dbg //test:all`
- **Boost wrinkle:** a bare `//...` / `make building` fails only on `apps/walk.{cc,h}`
  (last `boost/filesystem` use) + its 3 dependents. Fix = port walk to
  std::filesystem (preferred) or install libboost-filesystem-dev.

Core model: annotation `<feature,(p,q),value>`; query via τ/ρ hoppers
(Hopper::tau/rho + reverse uat/ohr); GCL operators and the S-expression parser
live in the top-level `gcl/` package (moved out of `src/` upstream, June 2026;
`//src:cottontail` still re-exports them). Warren groups components;
implementations: SimpleWarren (static burrow), Fiver (mutable txn shard), Bigwig
(dynamic, Fiver + Hazel shards + Fluffle), Hazel (immutable single-file shard —
**not declared ready**, see [[hazel-not-ready]]). null_feature=0 =
erased/unindexed. meadowlark/ = higher-level "meadow" layer; ranking in
src/ranking.cc + src/ranker.cc, incl. `parallel_ssr()` (upstream, June 2026).

Workflow: **feature branches + PRs, never commit directly to main** (the user
endorsed this; an earlier memory/.claude commit went to main before the rule was
set — fine, going forward we branch). See [[memory-location]] for where memory lives.
