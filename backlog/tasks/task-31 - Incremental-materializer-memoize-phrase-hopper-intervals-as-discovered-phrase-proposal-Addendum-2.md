---
id: TASK-31
title: >-
  Incremental materializer: memoize phrase-hopper intervals as discovered
  (phrase proposal Addendum 2)
status: To Do
assignee: []
created_date: '2026-07-03 14:53'
labels: []
dependencies:
  - TASK-30
priority: high
ordinal: 45000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The primary fix for the phrase re-drive pathology (docs/design/phrase-search-performance-and-proposal.md, Addendum 2 — Option D matured into Option B). A cover re-drives a phrase hopper 328-4000x (the measured 651s/806s cases); eager materialization was scouted at 100M and REJECTED (TASK-28: full-shard build per rank-worker regresses ordinary queries 7-32x). The incremental design keeps streaming's first-pass cost and memoizes what the stream discovers, so re-drives — the entire pathology — become array gallops.

Design: a new wrapper Hopper (fork-owned file, e.g. gcl/memo_hopper.{h,cc}; upstream's gcl/materialize.{h,cc} stays untouched):
- A growing SORTED memo of discovered (p,q,v) intervals + KNOWN-RANGE bookkeeping ("positions [a,b) are fully enumerated"). A probe inside a known range answers from the memo (binary search / gallop); a probe outside streams the wrapped hopper, records what it finds, and extends the known range.
- Bidirectional probing is the hard part (the gprof profile shows heavy uat/ohr traffic): per-direction frontiers or a small interval-set of known ranges — decide during implementation; start with the simplest correct structure and measure.
- Never worse than streaming by construction. Optional memory cap: stop growing the memo and stream past it (a cap on MEMORY only; no time-based gate needed — this is what makes unconditional wrapping safe, unlike TASK-28's eager wrap).
- Thread model: hoppers are single-threaded cursors (one per rank-worker), so the memo needs no locking; each worker memoizes only the slice it walks — cost proportional to work done, unlike eager's full-shard-per-worker.

Insertion (Addendum 2's revised answer to Open Question 1): the phrase expander in gcl/parse.cc wraps its generated (>> (# N) (... ...)) in the memo hopper UNCONDITIONALLY (safe because it cannot lose). Bare user-written (... a b) and the MultiText <> output can be wrapped too — decide during implementation, document. This is a small diff in an upstream file plus one new fork file; keep it upstreamable (this + the proposal is the package for Charlie).

Ordering: independent of TASK-30 but complementary (A makes costs predictable and fixes order-asymmetry; this kills the re-drive). Implement after TASK-30 so validation isolates each effect.

Validation (proposal Part IV, plus the TASK-28 scout as the regression suite):
- Identical total_matches and top-k on ALL Part I/III queries (5,765 for the tiers) — non-negotiable.
- tier2 ~713s -> within ~2x of tier1 (~20-40s); the I.5 trigger table flattens ("camp placement" 651s and "selection campsite" 806s to near the 9.8s floor).
- NO regression on the TASK-28 scout's broad query (4.0s must stay ~4s — the case eager wrapping broke) nor on dense fast phrases ("site selection", "campsite selection").
- The A/B killer request (captured repro) completes fast enough that the TASK-22 A/B can be rerun.
- bazel //test:all + isj suite green; new unit tests for the memo hopper (forward/backward probes, known-range merging, cap fallback, parity vs unwrapped on a small fixture).
<!-- SECTION:DESCRIPTION:END -->
