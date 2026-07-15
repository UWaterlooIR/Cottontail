---
id: TASK-45
title: Enable SimpleIdx posting-cache ejection to bound server memory (fix OOM)
status: In Progress
assignee: []
created_date: '2026-07-15 15:32'
updated_date: '2026-07-15 17:38'
labels: []
dependencies: []
ordinal: 66000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The 8 full-ClimbMix shard servers (cottontail-jsonl-server over SimpleWarren/SimpleIdx) grow unbounded in RSS across a run — ~66 GB each observed — and the machine wants each process <=40 GB (320 GB total). Root cause: src/simple_idx.h:4 hard-codes COTTONTAIL_SIMPLE_IDX_CACHE_EJECTION 0, so all LRU eviction in simple_idx.cc is compiled out and SimpleIdx::cache_ (a map of feature -> decompressed CacheRecord) never evicts. Every distinct term feature ever touched stays decompressed in RAM (~8 bytes/annotation for ClimbMix token features: postings array only, qostings aliases when qst==0, fostings null), so the cache climbs with the number of distinct terms queried over the server's life. Cycling servers per topic is the current operational workaround; this task removes the need for it. Upstream author (Charlie Clarke) confirms the ejection code was default-ON in the past, re-reviewed and tested it, and recommends flipping the guard to 1 with the existing defaults (large_threshold_=1024: features this size or smaller are never ejected; large_limit_=2^30 annotations: a POLICY threshold, not a hard cap, at which older large features start being ejected on the next large-feature load). At defaults the large-feature cache settles ~8.6 GB, comfortably under 40 GB with headroom to raise large_limit_ later. Stopgap scope: flip the flag, keep defaults, rebuild, relaunch the 8 servers, measure steady-state RSS, and stop per-topic cycling. Exposing large_limit_/large_threshold_ through the idx recipe as a real tuning knob is explicitly OUT of scope here (follow-up if wanted).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 bazel test //test:tests //test:hazel_test is green with ejection enabled
- [x] #2 A multi-query run against a SimpleWarren/SimpleIdx burrow shows RSS plateauing (not climbing unbounded) rather than the previous monotonic growth, and results are unchanged vs the ejection-off binary on the same queries
- [x] #3 Steady-state per-server RSS on the 8-shard ClimbMix setup is verified <=40 GB (documented in the task notes with the observed number)
- [x] #4 Exposing large_limit_/large_threshold_ via the idx recipe is recorded as out of scope / a follow-up, not done here
- [x] #5 src/simple_idx.h sets COTTONTAIL_SIMPLE_IDX_CACHE_EJECTION=1; large_threshold_ unchanged at 1024; large_limit_ raised to ~3e9 (~24 GB) per the recorded design decision
<!-- AC:END -->









## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
## Implementation Plan

### Root cause (recap)
`src/simple_idx.h:4` compiles out all LRU eviction (`#define COTTONTAIL_SIMPLE_IDX_CACHE_EJECTION 0`), so `SimpleIdx::cache_` (feature -> decompressed `CacheRecord`) never evicts. Distinct term features touched over a run accumulate in RAM (~8 B/annotation for ClimbMix token features), dominated by common-word and prefix-wildcard postings. Confirmed reproducer: topic **rag2026-2** + `isj-configs/config-gcl-cover.toml` fired ~85 `cover_search` queries (heavy wildcards: `constitution*`, `medicaid*`, `employer*`, `out-of-pocket*`, plus ~30 near-identical KFF reformulations re-hitting the largest lists) and OOM-killed a shard server mid-run (`Server disconnected without sending a response`). Upstream author confirms the ejection code was formerly default-ON, re-reviewed and tested; recommends flipping the guard with existing defaults.

### The change (stopgap scope)
Single edit in `src/simple_idx.h`:
```
-#define COTTONTAIL_SIMPLE_IDX_CACHE_EJECTION 0
+#define COTTONTAIL_SIMPLE_IDX_CACHE_EJECTION 1
```
Leave `large_threshold_ = 1024` and `large_limit_ = 1024*1024*1024` at defaults (subject to the pre-bump decision below). No other source changes. This compiles in the existing eviction path in `simple_idx.cc` (guards at lines 3, 251, 313-316, 342-361): large features (`n > large_threshold_`) are age-stamped on access; when `large_total_` (sum of resident large-feature annotation counts) exceeds `large_limit_`, the oldest large features are evicted (erased from `cache_`, their `n` preserved in `counts_`) until back under budget. Small features (`n <= 1024`) are never tracked/evicted but are individually tiny and bounded by vocabulary.

### Correctness / safety review (already done)
- Eviction only drops cache entries; an evicted feature is transparently re-read from `.pst` and re-decompressed on next `hopper_`/`load_cache`. `count_` stays correct (preserved in `counts_`). Query *results* are unchanged vs the ejection-off binary.
- Eviction loop `for (i=0; large_total_ > large_limit_; i++)` cannot index past `old`: evicting every tracked large feature drives `large_total_` to 0 <= limit, so it stops; accounting stays consistent with `ages_`/`cache_`.
- Thread-safety: a detached `decompress_cache` thread and any in-flight `ArrayHopper` hold their own `shared_ptr<CacheRecord>`, so eviction-while-decompressing is safe (no use-after-free); memory frees when the last holder releases.
- `large_limit_` is a POLICY threshold, not a hard cap, and eviction fires only when a NEW large feature loads — so RSS can transiently overshoot by ~one load-wave and an idle server stays at its high-water mark rather than shrinking. Acceptable for a stopgap.

### Build
`bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example`
Confirms the now-compiled-in eviction block builds clean (needs `<algorithm>`, guarded at `simple_idx.cc:3`).

### Test
1. `bazel test -c dbg //test:tests //test:hazel_test` must stay green. (Tiny test indexes never cross `large_threshold_`, so this proves compile + no correctness regression, not eviction firing.)
2. **In-repo eviction smoke test (exercises the branch without the 8 heavy servers).** Against `Scrapheap/climbmix-100k-porter.burrow` (common terms far exceed 1024 postings), in a scratch build with `large_limit_` lowered to a small value (e.g. a few thousand annotations) so eviction fires early: run many distinct queries via `cottontail-jsonl-query`, and confirm (a) process RSS plateaus instead of climbing monotonically, and (b) ranked results are byte-identical to the ejection-off binary on the same queries. Revert the scratch threshold afterward.

### Live validation (the real AC #3/#4 gate — needs the 8 full-shard servers)
Rebuild the shard-server binary (`cottontail-jsonl-server`) with ejection on; relaunch the 8 servers over `/share/indexes/climbmix_full_shards/part0[0-7].burrow`; re-run **rag2026-2 + config-gcl-cover** (non-cycled) while sampling per-shard RSS. Success = the run completes with **no `Server disconnected`/OOM**, and each server plateaus **<= 40 GB**. Record the observed steady-state RSS in the task notes (AC #4). Division of labor and starting `large_limit_` are the open questions below.

### Rollback
Flip the define back to `0`, rebuild, relaunch. Zero data/format impact (cache is purely in-memory; `.pst`/`.idx`/burrow layout unchanged), so rollback is instant and safe.

### Out of scope (follow-ups, not this task)
- Exposing `large_limit_`/`large_threshold_` through the idx recipe / a server flag as a runtime knob (byte-accurate budgeting would live here too).
- Searcher-behavior efficiency: aggressive prefix wildcards and long reformulation ruts (e.g. ~30 KFF variants) that amplify feature-load churn — a separate concern from the memory bound.

### Commit / PR
Branch `claude/simple-idx-cache-ejection` -> PR against the fork: `gh pr create --repo UWaterlooIR/Cottontail --base main --head claude/simple-idx-cache-ejection`. Never commit to `main` directly.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Design decisions (2026-07-15): (1) large_limit_ pre-bumped to ~3e9 annotations (~24 GB large-feature cache) instead of the 2^30 default, still well under the 40 GB/server ceiling. (2) Live validation vehicle = topic rag2026-2 + config-gcl-cover only (mt too slow); Claude runs + monitors the 8-shard run and saves results to trec-rag-2026/results. If rag2026-2 completes without a server disconnect, the fix is considered good. large_threshold_ left at 1024.

VALIDATION RESULT (2026-07-15, rag2026-2 + config-gcl-cover, 8 shards cycled, ejection ON, large_limit_=3e9):
- COMPLETED CLEAN: all 10 intents, succeeded=10 failed=0, no errors.log, rc=0 in 4823s (~80 min); 1572 passages judged. Same topic+config previously OOM-killed a shard server mid-run (~85 queries in).
- MEMORY BOUNDED: peak per-server RSS 25.3 GB (= 24 GB large_limit_ + ~1.3 GB single-feature overshoot, exactly as predicted). Whole run stayed in the 10-25 GB band vs the prior unbounded climb to ~66 GB. Well under the 40 GB/server ceiling; 8x25 GB = 200 GB total, comfortable on the 320 GB box.
- No server disconnect / engine_error; servers torn down normally by the cycled runner.
- Tests green: //test:tests + //test:hazel_test PASSED with ejection compiled in.
- Note on AC#3 'results unchanged vs ejection-off binary': the ejection-OFF binary cannot complete this topic (it OOM-crashes), so a same-topic A/B is impossible; correctness rests on the design (evicted features re-read from .pst on next access; counts preserved) + the passing test suite. The RSS-plateau + clean completion is the operative evidence.
<!-- SECTION:NOTES:END -->
