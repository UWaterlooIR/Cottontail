---
id: TASK-47
title: >-
  Per-query posting-memory budget: admission control (evict-idle ->
  admit-or-reject) to hard-cap shard RAM
status: In Progress
assignee: []
created_date: '2026-07-15 22:37'
updated_date: '2026-07-16 21:00'
labels: []
dependencies:
  - TASK-46
ordinal: 68000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The core memory-safety fix. Replace the lazy SimpleIdx cache cap (large_limit_) as the safety mechanism with a HARD, admission-time posting-memory budget B enforced per shard server. WHY: a single ranked query's working set -- the decompressed posting lists of every term it references -- is pinned by active hoppers (shared_ptr) for the whole query and CANNOT be evicted while it runs, so no cache-cap value can bound it (empirically: 24 GB cap -> 48 GB spike, 4 GB cap -> 64 GB spike on rag2026-2 mt; a bare 'a="health"' rank alone is ~24 GB/shard; an mt tiered program's union of common terms sums to tens of GB). The ONLY safe control is to refuse to START a query whose working set exceeds the budget. MECHANISM (per shard, per ranked query, BEFORE building ranking hoppers): (1) compute W = sum over the query's distinct leaf terms of their decompressed posting bytes, using count_ (a PstRecord header read, simple_idx.cc:412 -- the SAME data atom_counts used, now consumed INTERNALLY, cheap, no materialization); use a conservative bytes/annotation factor so W is never under-estimated. (2) Proactively evict IDLE cache (features not needed by this query; in the ~sequential one-query-per-shard workload nothing else pins them) to make room. (3) Admit iff W <= B -- then load/rank, guaranteed <= B; the transient 'cache floor + incoming term' spike is eliminated because we make room FIRST. (4) Reject iff W > B (too big even with a cold cache) with an informative error naming the largest terms; it bounces through the existing engine-error path (controller.py:328) to the searcher, which reformulates something narrower. This yields a true hard ceiling (admission precedes materialization), unifies the cache cap + a separate query guard into ONE knob B, and fails only genuinely-too-big queries (turning each into a teaching signal). Per-shard B sized so 8xB + base process stays under the box limit and each server stays <= 40 GB (e.g. B ~ 28-30 GB). Depends on / coordinates with TASK-46 (which removes the atom_counts RESPONSE + feedback but must RETAIN cover_leaves + idx->count for this guard).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A per-server posting-memory budget B is configurable via a server flag and enforced; for every ranked query (cover_search, tiered_query_search, multitext) the server computes W = sum of the distinct referenced leaves' decompressed posting bytes from count_ (header reads) BEFORE building any ranking hopper, using a conservative bytes/annotation factor
- [x] #2 Admission control: if W <= B the query runs after evicting idle (non-needed, LRU) cache to make room, and process posting memory stays <= B for the duration; if W > B the query is REJECTED before materializing any of its postings, with an error naming the largest offending term(s)
- [x] #3 The rejection propagates as an engine error through the existing controller bounce (controller.py) to the Searcher, which reformulates a narrower query; searcher.md and mt_tiered_searcher.md advise dropping the broadest terms on an over-budget bounce
- [x] #4 A SimpleIdx reserve/evict entry point evicts idle (LRU, not-in-this-query) cache entries to free room for W and reports infeasibility when W > B even with a fully cold cache; features the query needs are never evicted out from under it
- [x] #5 The standalone lazy large_limit_/large_threshold_ cap is retired (or explicitly demoted to a cache-reuse bound subordinate to B), with the decision documented; there is ONE authoritative memory knob (B)
- [x] #6 Verified end-to-end: rag2026-2 mt completes with per-server RSS bounded under B+base (< 40 GB) -- queries that would have OOM'd are bounced and reformulated rather than crashing a shard; a within-budget gcl run is behavior-unchanged
- [x] #7 Concurrency: budget accounting is process-global (a shared reservation across the --threads workers so concurrent queries' W sum against B) OR documented as an MVP that is safe only because the workload is one-query-per-shard-at-a-time, with the shared-reservation version specified as the hardening follow-up
- [x] #8 Eviction is MINIMAL: reserve() evicts idle entries LRU only until the query fits (idle_remaining <= B - W), retaining the rest of the cache warm for reuse; it never evicts more than necessary and never evicts features the query needs
- [x] #9 The over-budget bounce is a PROPER coaching message (not a bare error): it states the query cannot run (would exceed the per-query memory budget), NAMES the largest-posting-list terms sorted biggest-first (from the count_ data), and instructs the searcher to reduce the number of terms and ESPECIALLY drop/replace high-frequency 'stop-word'-like common terms that dominate the budget; searcher.md and mt_tiered_searcher.md carry matching proactive guidance
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
## Implementation Plan

### Prereq / sequencing
Land **TASK-46** first (it removes the atom_counts RESPONSE + feedback but RETAINS `cover_leaves` + `idx->count`, which this guard consumes internally). Build TASK-47 on a fresh branch off main after TASK-46 merges.

### Exact W is computable from the header (no estimate needed)
`count_` already reads a full `PstRecord` (n + the compressed segment sizes pst/qst/fst; simple_idx.cc:412). The DECOMPRESSED byte cost of a feature is therefore known exactly from the header:
  bytes(feature) = n*8 (postings)  + (qst>0 ? n*8 : 0) (qostings)  + (fst>0 ? n*8 : 0) (fostings)
(addr/fval are 8 B; qostings aliases postings when qst==0, so a plain token feature is n*8.) Add a small fixed margin per feature for the transient compressed-blob + decompression scratch. So W is EXACT, not estimated.

### New SimpleIdx capability
- `addr posting_bytes(addr feature)` -- read the header, return the exact decompressed byte cost above (0 if absent).
- Track cache occupancy in BYTES (add `cache_bytes_` alongside / replacing the annotation-count `large_total_`).
- `bool reserve(const std::set<addr>& needed, addr W_bytes, addr B_bytes, std::string* error)` under `cache_lock_`:
  - if `W_bytes > B_bytes` -> false (infeasible even cold; error names the largest needed feature).
  - else evict IDLE entries (in `cache_`, NOT in `needed`, LRU by `ages_`) until `cache_bytes_of_idle_remaining + W_bytes <= B_bytes` (i.e. make room). Needed features are never evicted. Returns true.
- Concurrency: `reserve` holds `cache_lock_`; for the hardened multi-query case, keep a process-global `reserved_bytes_` so concurrent queries' W sum against B (a query waits on a condition variable or is rejected if it cannot fit). MVP (one query per shard at a time) = the single reserve check; wire the global accounting but note the CV/wait path as the hardening.

### Server flag + wiring
- New flag on `cottontail-jsonl-server`: `--posting-budget-gb` (default sized so 8xB + base < box; ~28-30 GB/server keeps each <= 40 GB). Stamp into the search Spec like `rank_threads`.
- In `jsonl_cover_search` and `jsonl_tiered_query_search` (multitext delegates), BEFORE building ranking hoppers:
  1. `needed = { featurize(leaf) for leaf in cover_leaves(query-or-union-of-tiers) }`.
  2. `W = sum(posting_bytes(f) for f in needed)`.  (Union of all tiers' leaves = conservative peak.)
  3. `if (!idx->reserve(needed, W, B, &error)) return <over-budget error naming the biggest term(s)>;`
  4. proceed -- the subsequent `load_cache` calls fit within B by construction.
- The over-budget error returns like a malformed-query error so it bounces via EngineError -> controller.py:328 -> Searcher.

### Retire the lazy cap
`reserve` supersedes the `large_limit_` lazy per-load eviction as the SAFETY mechanism. Options (pick in the task): remove the `COTTONTAIL_SIMPLE_IDX_CACHE_EJECTION`/`large_limit_` lazy path entirely (B is the only knob), OR keep `large_threshold_` (never track/evict tiny features) as an optimization but drop `large_limit_` (B bounds the cache). Document the decision. `ejection`=1 and `large_limit_`=3e9 on main become dead once B lands.

### Prompts
- `searcher.md`, `mt_tiered_searcher.md`: add a short "if you get an OVER-BUDGET bounce, your query pulls in too many/too-broad terms -- drop the broadest (highest-frequency) term or split the facets across separate queries."

### Tests
- Unit: `posting_bytes` header math; `reserve` evicts idle / preserves needed / rejects when W>B (a fake or small SimpleIdx with tiny B).
- Integration (C++ jsonl_server test): a query whose leaves exceed a tiny configured B returns the over-budget error and materializes nothing; a within-budget query runs normally.
- Python: the over-budget error bounces to the Searcher (controller/searcher test).

### Verify (end-to-end, the AC)
Re-run rag2026-2 mt with a realistic B, RSS guard armed as a backstop: over-budget tiered programs / bare-common-term ranks get bounced and reformulated; per-server RSS stays under B+base (< 40 GB); the topic completes. Compare a gcl run for no behavior regression.

### Out of scope
The multi-query process-global CV/wait hardening MAY ship as a follow-up if the MVP per-query reserve is sufficient for the current sequential workload (AC #7 documents which was done).

### Commit / PR
Fresh branch off main -> PR against the fork (UWaterlooIR/Cottontail). Never commit to main.

### CLARIFICATION -- evict the MINIMUM; keep the cache warm
reserve() must evict idle entries LRU (oldest-first) ONLY until the new query fits: stop as soon as `idle_remaining_bytes <= B - W` (free just enough headroom for W). Do NOT evict all idle cache -- retain the warmest (most-recently-used) idle features for cross-query reuse.
- W < B: keep (B - W) worth of the warmest idle cache resident; evict just the coldest overflow.
- W == B: all idle must go (unavoidable -- the query needs the whole budget).
- W > B: reject (would not fit even with a fully cold cache).
The "cold cache" in the reject test (W > B) is a FEASIBILITY hypothetical, not what we do on admit. On admit we evict the minimum.

### INVARIANT -- never evict a feature the query needs (can't evict X to make room for X)
The eviction pool is STRICTLY `cache_ \ needed` -- cached features NOT referenced by this query. A needed feature is NEVER an eviction candidate, including:
- one that is already cached (it counts toward W and stays), and
- protecting each needed feature as ranking incrementally loads the rest -- a LATER needed load must never evict an EARLIER needed one.
Feasibility is judged only on W = sum over `needed`: if evicting the ENTIRE idle pool (`cache_ \ needed`) still cannot free room for W, then W > B and we REJECT -- we do NOT start evicting needed features to appear to fit. So `reserve(needed, W, B)` = (a) if W > B reject; else (b) evict from the idle pool only, LRU, the minimum to fit. Practically it runs UP FRONT over the full `needed` set, marking/pinning those features for the query's duration so the lazy per-load path never evicts a needed feature mid-query.

### Bounce message on reject (W > B) -- proper, actionable coaching
The rejection is NOT a bare error. Because reserve() already has each needed term's posting size (from count_), the message names the offenders and tells the searcher how to fix it. Shape:

  This query can't run: it would load ~<W> GB of posting lists, over the <B> GB per-query
  memory budget. The largest contributors are: <term1>=<n1>, <term2>=<n2>, <term3>=<n3> ...
  To fix:
   1. Reduce the NUMBER of terms in the query.
   2. Especially drop or replace high-frequency "stop-word"-like common words -- a few very
      common terms (the, and, of, plus broad words like health/care/states) have enormous
      posting lists that dominate the budget. Prefer distinctive, specific terms.
   3. If you need broad coverage, split the facets across SEPARATE narrower queries rather
      than one wide program.

Sort the named terms by posting size (largest first) and list the top few so the searcher knows exactly what to cut. It bounces via the existing EngineError -> controller.py:328 path (same as a malformed-query bounce), so the searcher reformulates and retries.

Prompt updates (proactive, not just reactive): searcher.md and mt_tiered_searcher.md gain a short note that each query has a memory budget, so avoid packing in many terms and avoid bare high-frequency/stop-word terms; on an OVER-BUDGET bounce, cut the named terms.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented on branch claude/excise-diagnostic-counts (commit ddb94c2), stacked on TASK-46. Idx interface gains posting_bytes/posting_budget/set_posting_budget/reserve (no-op defaults). SimpleIdx: byte-based cache accounting (large_bytes_) + budget (budget_bytes_, default ~24 GB) replaces the annotation-count large_total_/large_limit_ lazy cap; the COTTONTAIL_SIMPLE_IDX_CACHE_EJECTION compile guard is retired (unconditional). W is EXACT from the PstRecord header (n + qst/fst), not a conservative factor. reserve() evicts idle LARGE features LRU, protecting , down to needed_cached + (B - W) -- minimal eviction, never a needed feature; load_cache keeps a lazy byte backstop for non-reserving paths. Server flag --posting-budget-gb (default 24; 0 = off). Handlers (cover_search + tiered/multitext) call posting_budget_admit before ranking (tiered sizes the UNION of all tiers' leaves); over-budget -> OVER BUDGET bounce naming biggest terms (adaptive GB/MB). Prompts updated. Concurrency = per-query MVP (safe for the one-query-per-shard workload); process-global reservation is the documented hardening follow-up. Tests: //test:all 5/5 incl. new JsonlCover.PostingMemoryBudgetGuard (tight rejects / generous admits / 0 disables); Python isj 242 passed. End-to-end verified on Scrapheap/climbmix-100k-porter.burrow with a 0.5 MB budget: multi-term query rejected naming time/people/data, rare term admitted. AC#6 (full 8-shard rag2026-2 mt completing < 40 GB) is the remaining OPERATOR validation -- the guard mechanism is verified e2e here, but the heavy 8-server run is not runnable in this session.

CONCURRENCY (AC#7) hardened beyond the MVP (commit 1f24c22): added a server-level g_ranking_mutex (semaphore of 1) held around every materializing endpoint (search_text/gcl, cover_search, tiered_query_search, multitext_tiered_search, count_matches), so at most ONE ranked query materializes at a time and the per-query budget holds even under concurrent clients; get_document/healthz are NOT serialized (reads + health checks stay concurrent). The working set is released (local hoppers destroyed) by the time provider.with returns and the lock drops -- no deadlock (verified: 3 concurrent cover_search serialize + return 200 while a mid-flight healthz answers in <1 ms). The finer byte-level global reservation (allow overlap up to B via a shared reserved_bytes_ + condition_variable) remains an optional future refinement; the semaphore is a complete correctness solution for the one-materializing-query-at-a-time invariant.

AC#6 VALIDATED on the real 8-shard ClimbMix stack (2026-07-16). rag2026-2 mt -- the exact topic that previously OOM'd at 48-64 GB/server -- was run cycled at two budgets. (24 GB, short observation) the guard fired correctly: a query at 26.4 GB was bounced OVER BUDGET naming bare stop words (and=8.0, to=7.5, of=7.5 GB) with the drop-stop-words coaching; no OOM (RSS flat ~10 GB base). (30 GB, full run) COMPLETED CLEAN: all 10 intents, done ran=1 failed=0, no errors.log, 1596 passages judged (~160/intent), 62 queries. Peak per-server RSS = 30.2 GB (mostly 20-30 GB band) -- UNDER the 40 GB ceiling, vs the prior OOM. 0 OVER BUDGET bounces at 30 GB (more headroom). The only non-memory issues were searcher-side and orthogonal to this task: 2 proximity-heavy queries hit the 1 h engine timeout (pre-existing mt ranking-speed, TASK-32) and 42 MultiText compile-error bounces (searcher self-corrects). Memory work (TASK-46+47) is fully validated end-to-end: admission bounds the working set, the budget prevents OOM, and the topic completes.
<!-- SECTION:NOTES:END -->
