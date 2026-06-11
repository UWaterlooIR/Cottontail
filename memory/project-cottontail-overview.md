---
name: project-cottontail-overview
description: What Cottontail is, where the active work is, and the authoritative docs
metadata:
  type: project
---

Cottontail is the C++20 reference implementation of **Annotative Indexing** (Charles
L. A. Clarke, IRRJ 2025; paper at docs/Annotative-Indexing-IRRJ-Clarke-2025.md).
Bazel build (deps: nlohmann_json, googletest, rules_cc — Boost dependency from the
paper era is gone). Moving from research project toward a usable library + Python
wrapper; "no rush, want a good release."

Core model: annotation = <feature,(p,q),value>; query via τ/ρ hoppers (code:
Hopper::tau/rho + backwards uat/ohr); GCL operators in src/gcl.h mirror paper Figure 2.
Warren groups components; implementations: SimpleWarren (static burrow), Fiver (mutable
transaction shard = paper's "update Warren"), Bigwig (dynamic, Fiver shards + Fluffle
state), Hazel (immutable single-file shard). null_feature=0 means erased/unindexed.

Authoritative/agent docs live in ai/: architecture.md (do NOT edit without permission),
plan.md (next coding step — often a discussion gate, not authorization), notes.md,
log.md, hazel*.md. AGENTS.md rule: agents run compile/build checks only (make building
/ bazel build //...) — no tests, ranking, evals, or benchmarks unless explicitly asked.

Active work (as of 2026-06): a PostingIterator-style raw posting-list path over both
SimplePosting (Fiver) and CacheRecord (Hazel), wired into Bigwig Fiver-only first,
before Hazel joins the live mixed-shard query path. This is the paper's stated
near-term goal of optimizing low-level Hopper ops to close the BM25 gap with Lucene.
See [[user-mark-smucker]].
