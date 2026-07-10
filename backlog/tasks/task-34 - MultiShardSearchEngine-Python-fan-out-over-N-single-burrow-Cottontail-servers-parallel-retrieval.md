---
id: TASK-34
title: >-
  MultiShardSearchEngine: Python fan-out over N single-burrow Cottontail servers
  (parallel retrieval)
status: To Do
assignee: []
created_date: '2026-07-10 03:10'
labels:
  - isj
  - search
  - performance
dependencies: []
ordinal: 48000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add a MultiShardSearchEngine (Python) that runs one query across N single-burrow Cottontail servers in parallel and merges the results -- mirroring how Lucindri builds its index in parts and searches them together via Lucene's MultiReader (Lucindri/scripts/build_full_keepstop.sh). Sharding speeds up BOTH indexing (build N sub-burrows concurrently) and retrieval (each server ranks 1/N of the corpus, in parallel -> wall-clock ~ the slowest shard).

WHY THE MERGE IS EXACT (the enabling property): SimpleWarren burrows are read-only and the cover-density / SSR ranker uses NO collection statistics -- score = sum over covers of 1/(K + q-p) with a FIXED K=42, purely local to the document. So a doc's score is the same on its shard as on the full corpus; cross-shard scores are directly comparable. Take each shard's top_k, merge, keep the global top_k -> the TRUE global top_k. total_matches / unjudged_matches / atom_counts are ADDITIVE across shards (sum). GUARD: this holds ONLY while the ranker stays stats-free. If a BM25/IDF ranker (needs global df) is ever added, per-shard scores stop being mergeable -- document/assert this precondition.

PRECEDENT: Charlie's ssr_server (apps/ssr-server.cc) already does exactly this for SSR -- it opens multiple burrows, spawns one worker thread per collection (parallel_ssr per warren), then merges with stable_sort by score and takes the top. This task does the equivalent for the ISJ agent's cover_search stack, in PYTHON.

WHY PYTHON (Option B, chosen over a multi-burrow C++ server -- Option A): the docno-on-the-wire refactor (TASK-33) already made the Cottontail HttpSearchEngine docno-native to the agent (it owns the per-burrow cp<->docno map). So a multi-shard engine is a thin Python merge layer over N unchanged single-burrow HttpSearchEngines -- ZERO C++ changes -- and it implements the SearchEngine Protocol, so the controller / judger / run-output are UNCHANGED (it is "just another engine"). cp is shard-local (ambiguous across shards), but each shard engine already returns globally-unique docnos, so the merge is docno-keyed and clean. (Option A -- teach the C++ server to open N burrows like ssr_server, one endpoint -- stays a possible future consolidation; not this task.)

OPS: the operator runs N single-burrow servers, e.g. ports 7000, 7001, 7002, ... each over one sub-burrow; the config lists them. A sharded-build script (split the corpus shards into N groups, build N sub-burrows via the cottontail-index front door) is a prerequisite for the live test -- analogous to Lucindri's build_full_keepstop.sh.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 MultiShardSearchEngine implements the SearchEngine Protocol: search() fans out CONCURRENTLY to N single-burrow HttpSearchEngines (full exclude passed to each) and merges the per-shard results by score into the global top_k (re-ranked 1..N); the controller/judger/run-output are unchanged.
- [ ] #2 Counts summed across shards: total_matches / unjudged_matches summed, atom_counts summed by term; omitted when no shard reports them (Q3-consistent).
- [ ] #3 read(docno) routes to the owning shard (memoized from search; fallback tries shards until found). tiered/multitext are fan-and-merged the same way OR explicitly deferred for v1 (documented).
- [ ] #4 Config-selected: an [engine] section selects MultiShardSearchEngine with N shard entries ({base_url, burrow} each, e.g. ports 7000+); build_engine constructs it.
- [ ] #5 The stats-free precondition is documented and guarded: the merge is exact only for the cover-density/SSR ranker (no corpus-stat/IDF ranker); note/assert it.
- [ ] #6 Unit tests (N mocked shard engines): concurrent fan-out, score-merge to the global top_k, exclude fanned to all shards, count summation, read routing.
- [ ] #7 (gated) live: build a small sharded burrow set (~4 sub-burrows), run 4 servers (7000-7003), and confirm a full agent run's top results match a single-burrow run over the same corpus (same docnos/scores) and complete faster.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
IMPLEMENTATION SKETCH (Option B)
- New module isj_agent/engine/multishard.py: MultiShardSearchEngine wraps a list of shard
  HttpSearchEngines (built from per-shard {base_url, burrow}). search(query, top_k, exclude,
  window): a ThreadPoolExecutor fans the SAME (query, top_k, exclude, window) to every shard;
  each returns its shard's docno-keyed top_k; concatenate, STABLE-sort by score desc, take
  top_k, re-rank 1..top_k. Sum the optional counts across shards (atom_counts summed by term;
  total_matches / unjudged_matches summed) -- omit any the shards don't report (Q3-consistent).
  Memoize docno -> shard_index for each surfaced hit (for read routing).
- GLOBAL top_k under exclude: each shard's HttpSearchEngine already over-fetches
  top_k + |its own excluded| and drops them, so its returned top_k are the shard's FRESH
  top_k -> the merged top_k is globally correct and deterministic. Pass the full exclude to
  every shard (each maps only its own docnos, ignores the rest).
- read(docno): use the memoized shard; on a cold miss, try shards until one returns non-None.
- tiered_search / multitext_search: same fan-and-merge is possible (per-shard cascade, then
  merge by score) OR defer for v1 -- document the choice.
- Config: build_engine dispatch adds the MultiShardSearchEngine class; the [engine] section
  carries the shard list, e.g. shards = [{ base_url = "http://127.0.0.1:7000", burrow = "..." },
  { base_url = "http://127.0.0.1:7001", burrow = "..." }, ...].
- Errors: a per-shard EngineError propagates as EngineError (a malformed query fails every
  shard identically -> a single clean bounce to the model).
- RELATED: TASK-32 (within-burrow work-aware range split) is a complementary, finer split;
  sharding by file is coarser -- a slow SHARD can still straggle, bounded by the slowest shard.
- MIRROR: apps/ssr-server.cc (thread-per-collection + stable_sort by score) is the C++ precedent.
- PREREQ for the live AC: a sharded-build script (N sub-burrows over disjoint corpus-shard
  groups, each via cottontail-index so each gets its docno-cp.sqlite).
<!-- SECTION:NOTES:END -->
