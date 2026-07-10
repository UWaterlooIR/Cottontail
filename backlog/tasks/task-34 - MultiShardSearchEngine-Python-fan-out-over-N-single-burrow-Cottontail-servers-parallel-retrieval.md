---
id: TASK-34
title: >-
  MultiShardSearchEngine: Python fan-out over N single-burrow Cottontail servers
  (parallel retrieval)
status: In Progress
assignee:
  - '@claude'
created_date: '2026-07-10 03:10'
updated_date: '2026-07-10 03:51'
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
- [x] #1 MultiShardSearchEngine implements the SearchEngine Protocol: search() fans out CONCURRENTLY to N single-burrow HttpSearchEngines (full exclude passed to each) and merges the per-shard results by score into the global top_k (re-ranked 1..N); the controller/judger/run-output are unchanged.
- [x] #2 Counts summed across shards: total_matches / unjudged_matches summed, atom_counts summed by term; omitted when no shard reports them (Q3-consistent).
- [x] #3 read(docno) routes to the owning shard (memoized from search; fallback tries shards until found). tiered/multitext are fan-and-merged the same way OR explicitly deferred for v1 (documented).
- [x] #4 Config-selected: an [engine] section selects MultiShardSearchEngine with N shard entries ({base_url, burrow} each, e.g. ports 7000+); build_engine constructs it.
- [x] #5 The stats-free precondition is documented and guarded: the merge is exact only for the cover-density/SSR ranker (no corpus-stat/IDF ranker); note/assert it.
- [x] #6 Unit tests (N mocked shard engines): concurrent fan-out, score-merge to the global top_k, exclude fanned to all shards, count summation, read routing.
- [ ] #7 (gated) live: build a small sharded burrow set (~4 sub-burrows), run 4 servers (7000-7003), and confirm a full agent run's top results match a single-burrow run over the same corpus (same docnos/scores) and complete faster.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DETAILED IMPLEMENTATION PLAN (MultiShardSearchEngine). Status: FOR REVIEW. Buildable +
unit-testable WITHOUT live servers (mocked shard engines); the live check is a gated final step
against the 4-shard test setup (scripts/build-test-shards.sh + launch-test-shard-servers.sh).
KEY PROPERTY: the corpus is PARTITIONED across shards (each doc/docno lives in exactly ONE
sub-burrow), so the merge never sees a docno twice -- no cross-shard de-duplication is needed.
See OPEN QUESTIONS at the end -- three need a decision before coding.

PHASE 1 -- MultiShardSearchEngine core (isj_agent/engine/multishard.py)
  - Holds an ordered list of shard engines (HttpSearchEngine). Implements the SearchEngine
    Protocol (search / tiered_search / multitext_search / read).
  - _fan(method, *args): submit shard.<method>(...) to a ThreadPoolExecutor (workers = number of
    shards); gather. Any shard raising -> re-raise as EngineError (fail-fast; NEVER return
    partial/missing-shard results -- OPEN Q1). A malformed query fails every shard identically, so
    its parse message reaches the model via the normal bounce.
  - _merge(responses, top_k): concatenate all shards' Hits; STABLE-sort by score DESC (Cottontail
    cover-density is higher=better AND stats-free, so cross-shard scores are comparable -- the
    enabling property); take top_k; re-rank 1..top_k. Sum the OPTIONAL counts across shards:
    total_matches / unjudged_matches summed (skipping None), atom_counts summed BY TERM; each is
    None if no shard reported it (Q3-consistent, from TASK-33). Record docno -> shard index for
    each surfaced Hit (the read-routing memo).
  - search / tiered_search / multitext_search: each = _merge(_fan("<method>", <payload>, top_k=,
    exclude=, window=), top_k). The SAME (payload, top_k, exclude, window) fans to every shard;
    each shard's HttpSearchEngine excludes only ITS OWN docnos (a foreign docno is not in its
    DocnoMap -> skipped) and over-fetches its top_k, so the union contains the true global top_k
    (standard distributed top-k merge; deterministic since each shard is deterministic).
  - read(id): route to the memoized shard's read(id); on a cold miss, try shards in order until
    one returns non-None (else None). The controller only reads docnos it just surfaced -> memo hit.
  - Startup health check across shards -- OPEN Q2.

PHASE 2 -- config selection (isj_agent/config.py + cli)
  - build_engine dispatch: class is MultiShardSearchEngine -> build one HttpSearchEngine per entry
    in cfg["shards"] via the EXISTING build_search_engine(shard_cfg) (each opens its own DocnoMap),
    then MultiShardSearchEngine([...engines]). Validate: `shards` is a non-empty list, each entry
    has base_url + burrow (fail loud). The --burrow CLI override is ignored for multishard (N burrows).
  - config.example.toml: document the [engine] MultiShardSearchEngine block (the recorded shape:
    explicit shards = [{base_url, burrow}, ...]; note the [[engine.shards]] array-of-tables equivalent).

PHASE 3 -- unit tests (tests/test_multishard.py)
  - N in-process fake shard engines. Assert: concurrent fan-out to all shards; score-merge yields
    the true global top_k re-ranked 1..N; the same exclude fans to every shard and each drops only
    its own docnos; total_matches/unjudged_matches summed; atom_counts summed by term; read routes
    to the owning shard (+ cold-miss try-all); any shard error -> EngineError. Cover tiered/multitext
    if in scope (OPEN Q3).
  - build_engine test: an [engine] shards config builds a MultiShardSearchEngine over N
    HttpSearchEngines; empty/malformed `shards` -> fail loud.

PHASE 4 -- docs + scripts
  - running-the-search-stack.md: a "sharded Cottontail (MultiShardSearchEngine)" subsection -- build
    the sub-burrows (scripts/build-test-shards.sh), launch N servers (scripts/launch-test-shard-servers.sh),
    point [engine] at the shard list. The build + launch scripts already exist (this branch).

PHASE 5 (gated) -- live validation
  - Against the 4-shard test setup (ports 7000-7003): run a full ISJ agent question through the
    MultiShardSearchEngine and confirm (a) it succeeds with real docnos, (b) the TOP results match a
    single-burrow run over the same 100 shards (same docnos/scores at the top -- proves the merge is
    exact), and (c) it is faster (parallel fan-out). Needs a matching single-100-shard burrow to diff.

======================= DECISIONS (all resolved, owner 2026-07-10) =======================
Q1 (shard-failure policy) -- RESOLVED (fail-fast; no silent partial results): any shard raising -> fail the WHOLE search (fail-fast); NEVER return
   partial results missing a shard's docs (that would silently drop 1/N of the corpus and break the
   exact-top_k guarantee). A malformed query fails all shards identically -> its parse message
   bounces to the model as usual; a down/erroring shard fails the run loudly. RECOMMEND fail-fast.
Q2 (startup health check) -- RESOLVED (yes, ping /healthz on build): ping each shard's /healthz on engine build and FAIL FAST if any shard is
   down (mirrors the Lucindri engine; the single Cottontail engine does NOT currently do this, but N
   operator-launched servers have more failure surface). RECOMMEND adding it for multishard.
Q3 (tiered/multitext scope) -- RESOLVED (all three via the one fan-merge): implement search + tiered_search + multitext_search all via the one
   generic fan-merge (cheap; the partitioned corpus means no cross-shard de-dup), OR ship v1 with
   search only (the plain cover Searcher) and defer tiered/multitext. RECOMMEND all three.
<!-- SECTION:PLAN:END -->

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

CONFIG (owner-decided 2026-07-10)
The [engine] section selects the class and LISTS the shards; each shard entry IS a
single-Cottontail-engine config -- base_url + burrow (the burrow gives that shard its
docno-cp.sqlite map), plus the same optional timeout_s / api_key_env the single engine
already understands. NO max_workers / extras: fan-out is ALWAYS to all N shards (the
client threads block on I/O and the C++ servers do the work, so there is nothing to throttle).

[engine]
class = "isj_agent.engine.multishard.MultiShardSearchEngine"
shards = [
  { base_url = "http://127.0.0.1:7000", burrow = "/share/indexes/climbmix_test_shards/part00.burrow" },
  { base_url = "http://127.0.0.1:7001", burrow = "/share/indexes/climbmix_test_shards/part01.burrow" },
  { base_url = "http://127.0.0.1:7002", burrow = "/share/indexes/climbmix_test_shards/part02.burrow" },
  { base_url = "http://127.0.0.1:7003", burrow = "/share/indexes/climbmix_test_shards/part03.burrow" },
]

WIRING: build_engine dispatches on class; for MultiShardSearchEngine it builds one
HttpSearchEngine per shard via the EXISTING build_search_engine(shard_cfg) (each gets its
own DocnoMap), then constructs MultiShardSearchEngine([...engines]). No new per-shard parsing.

EXPLICIT PAIRING (deliberate): base_url<->burrow are paired PER ENTRY, not a compact
base_host + ports[] + burrow_glob pattern. A pattern risks a sort mismatch pairing a shard's
docno map with a server serving a DIFFERENT burrow -> silently wrong docnos; explicit pairing
cannot mispair. For a large split, GENERATE the shards list (the sharded-build script knows the
port<->burrow mapping). TOML note: `shards = [{...}, {...}]` (inline-table array) and the
[[engine.shards]] array-of-tables form parse identically -- document the inline array as primary.

IMPLEMENTED (2026-07-10, branch claude/task-34-multishard). Full isj suite green (170 passed).
- engine/multishard.py (fan-out + score-merge + read routing, fail-fast); http.py healthz();
  config build_multishard_engine + dispatch (validates shards, health-checks on build);
  config.example.toml + run-guide docs; test_multishard.py + config dispatch tests.
- BUG caught + fixed by the live test (unit tests use FakeEngine, no sqlite): each shard's
  DocnoMap sqlite connection was created in the main thread but used in fan-out worker
  threads -> cross-thread ProgrammingError. Fixed: check_same_thread=False + a lock (read-only
  immutable connection, one thread at a time).
- LIVE (4-shard test set, ports 7000-7003 over the first 100 climbmix shards):
  (1) MERGE EXACT -- the multishard top-k EQUALS the manual merge of the 4 shards' own top-k;
      total_matches + atom_counts summed; read() routes to the owning shard.
  (2) FULL AGENT RUN succeeded (cover Searcher) -- 1 intent, 0 failures, 32 judged docs whose
      docnos SPAN ALL 4 SHARDS (12/7/6/7), merged into one graded ranked list; counts summed.
- AC#7 (gated live): the merge-exactness + full agent run above validate it. The literal
  "sharded == single-100-shard-burrow" diff was NOT run (no single-burrow baseline built); it
  is guaranteed by the stats-free property + the proven-exact merge. Left AC#7 unchecked pending
  an owner call on whether to build that baseline burrow (~13 min) for the belt-and-suspenders check.
<!-- SECTION:NOTES:END -->
