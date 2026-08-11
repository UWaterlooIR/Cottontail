# TASK-47 budget-overshoot investigation

**Date:** 2026-07-18
**Branch:** `claude/excise-diagnostic-counts` (PR #25, held from merge pending the fix below)
**Author:** Claude (Opus 4.8) with Mark Smucker
**Status:** Root cause found and proven by A/B. Fix proposed (not yet applied).

## The incident

During a 32 GB-per-shard cycled `test-topics` run, one shard server spiked to
**~56 GB RSS** against a `--posting-budget-gb 32` budget, with **zero
`OVER BUDGET` bounces**. The admission control (TASK-47) is supposed to keep a
query's decompressed working set under the budget or bounce it, so both the
overshoot *and* the absence of a bounce were unexpected.

The culprit query was `rag2026-13` intent-01: a large MultiText tiered program
whose big cost terms are common English stop-words (`and`, `to`, `of`, `a`),
each carrying a 6–8 GB decompressed posting list on a single shard. The program
is saved as [`coo-program.mt.txt`](coo-program.mt.txt).

## Hypotheses going in

- **H1 — transient decompression overhead.** During materialization a feature's
  compressed blob is co-resident with its decompressed form; peak RSS could
  exceed the accounted decompressed bytes by the sum of in-flight compressed
  blobs.
- **H2 — admission under-count.** The admission estimate `W_est` (from
  `posting_bytes`/`PstRecord` headers) systematically under-counts the true
  resident footprint, so a query admitted at `W_est ≤ B` actually needs `> B`.
- **H3 — lazy backstop.** The `load_cache` byte backstop
  (`simple_idx.cc`, `evict_idle_locked(target, {})`) evicts cache entries with an
  **empty protect set**, so it can evict features the running query still holds.

## Experiment

One shard (`part00.burrow`), instrumented server (temporary `[EXP]` hooks,
reverted after the run — see "Instrumentation" below). Three quantities were
captured at admit-time and post-rank, plus external `/proc/<pid>/status` RSS
sampling at ~0.4 s cadence:

- `W_est` — admission's decompressed-bytes estimate.
- `large_bytes_` — the cache's own running decompressed-byte accounting.
- `VmHWM` — peak process RSS (never decreases).
- compressed-in-flight peak — sum of compressed blobs co-resident during decode.

The same query A was run under three conditions. The **only** variable that
changed the outcome was the budget (which gates whether the backstop fires) and
the `EXP_NO_BACKSTOP` toggle.

| Run | Budget | Backstop | Backstop firings | `W_est` | final `large_bytes_` | **peak `VmHWM`** |
|-----|-------:|----------|-----------------:|--------:|---------------------:|-----------------:|
| A   | 100 GB | on (never triggers: 31 ≪ 100) | 0  | 31.37 GB | 32.47 GB | **34.73 GB** |
| B   | 32 GB  | on        | 88               | 31.37 GB | 31.82 GB | **97.61 GB** |
| C   | 32 GB  | **off** (`EXP_NO_BACKSTOP=1`) | 0 | 31.37 GB | 32.47 GB | **34.73 GB** |

Raw `[EXP]` stderr traces and RSS samples for each run are under
[`data/`](data/) (`runA.exp.log`, `runB.exp.log`, `runC.exp.log`, and the
matching `.rss` files).

## Result: H3 is the cause

Runs A and C are **identical** (34.73 GB peak) and differ from B only in whether
the backstop is allowed to run. Turning the backstop off at the *same* 32 GB
budget collapses the peak from **97.6 GB → 34.7 GB**. The backstop is the sole
cause of the overshoot.

- **H2 refuted as a large effect.** `W_est` (31.37) predicts the clean peak
  (34.73) within ~11%. The gap is ~1.1 GB of uncounted *small* features
  (`n ≤ large_threshold_`, never budgeted) plus ~2.2 GB transient/allocator.
- **H1 confirmed but small.** Compressed-in-flight peaked at ~4 GB and is fully
  released post-rank (`comp_now = 0`). It explains the ~2 GB of the A/C overshoot,
  not the explosion.
- **H3 confirmed as primary.** Run B logged 88 `backstop evicting PINNED feature`
  events with `use_count = 2,3,4` — i.e. the backstop evicted features the
  running query was actively using.

### Mechanism (why evicting a pinned feature *inflates* RSS)

This corrects an earlier hand-wave ("evicting a pinned feature can't increase
RSS, it just fails to free"). It increases RSS by **duplication**:

1. As the 49 needed features materialize one by one, `large_bytes_` climbs toward
   the budget. Because the true footprint (32.47) exceeds `W_est` (31.37) and the
   budget (32), near the end `load_cache`'s guard
   `large_bytes_ + feat_bytes > budget_bytes_` trips.
2. The guard calls `evict_idle_locked(target, {})` with an **empty** protect set.
   `evict_idle_locked` walks `ages_` oldest-first and erases entries from `cache_`
   — including big stop-word features the current query still holds a
   `shared_ptr` to (`use_count > 1`).
3. Erasing a **pinned** entry does **not** free its memory (the hopper still
   references it) but it **does** decrement `large_bytes_`. The accounting now
   *under*-counts resident memory.
4. Because `large_bytes_` dropped, the budget looks like it has room, so when the
   next tier (t1/t2 of the tiered program) requests that same big feature,
   `load_cache` misses in `cache_` and **decompresses a fresh second copy**.
5. Repeat across tiers and features → several duplicate 6–8 GB copies pile up →
   **97.6 GB peak**. The duplicates are released only when the query ends and the
   hoppers drop, which is why current RSS returns to ~32 GB afterward while the
   high-water mark stays at 97.6.

At budget = 100 the guard never trips (`large_bytes_` 31 ≪ 100), so no eviction,
no duplication, clean 34.7 GB. Mark's instinct — that with one query at a time we
should never be evicting the postings the current query is using — was exactly
right; the backstop violates precisely that invariant.

### Not the cause: cross-query accumulation

Run B also fired a second, **disjoint** big query (B, stop-words `the/in/for/is`
— [`coo-program-B.mt.txt`](coo-program-B.mt.txt)) back-to-back on the warm
server. After query B, `large_bytes_ = 31.0 GB`, **not** ~62 GB — so `reserve()`
correctly evicted query A's working set before admitting B. The explosion is
entirely *within* a single query, not accumulation across queries.

## Fix (applied — commit `39a080d`)

The primary fix was applied: **the lazy backstop's eviction was removed from
`load_cache`; only the LRU accounting (`large_bytes_`, `ages_`) remains.**
Eviction now lives solely in `reserve()` (admission control), which protects the
needed set and runs between queries — serialized by the ranking mutex — when
nothing is pinned, so it can never evict a pinned feature. Re-running the exact
scenario after the fix: peak VmHWM **39.65 GB** at budget 32 / `--rank-threads 4`
(query A + a disjoint query B, both correct); the 97.6 GB → 39.65 GB collapse
confirms the backstop was the sole cause. All four test suites pass.

The two defects the analysis identified, in priority order:

1. **The lazy backstop must never evict a pinned (in-use) feature.** This is the
   bug. Preferred: **remove the lazy backstop in `load_cache` entirely** — every
   materializing endpoint already goes through `reserve()` admission control
   (TASK-47), so the "belt and suspenders" backstop for non-reserving callers is
   both unnecessary on the real paths and actively harmful. If a backstop is kept
   for safety, `evict_idle_locked` must skip any entry with `use_count() > 1`
   regardless of the protect set (never evict what someone is holding), and the
   accounting must not be decremented for an entry whose memory wasn't actually
   freed.

2. **Admission slightly under-estimates the true footprint** (`W_est` 31.37 vs
   real `large_bytes_` 32.47, ~3.5%). Because the guard compares against the exact
   budget, an admitted query can still sit just over budget. Give admission a
   small headroom margin, or count small-feature and tier-atom bytes, so an
   admitted query's real resident set stays under `B`. Lower priority — on its
   own this causes only a few-percent overshoot, not the explosion.

With fix (1) alone, the worst case for this query on this shard is the intrinsic
~35 GB working set (the four stop-word lists). If a hard 32 GB ceiling is
required, admission should bounce this query (its true set is ~32.5 GB) — i.e.
the `OVER BUDGET` message telling the searcher to drop high-frequency common
words is the right behaviour, and the margin in fix (2) makes it fire.

## Production validation (full 119-topic run, 2026-07-19 → 07-24)

The fix was validated on the real 8-shard ClimbMix stack under the ISJ Searcher,
budget **36 GB/server**, with a standalone RSS guard armed to abort any server at
48 GB. A full **119-topic gcl run** (`config-gcl-cover.toml`) completed over ~5
days:

- **No OOM, no crash, no guard abort.** Peak busiest server **42.7 GB** — under
  the 44 GB warning and the 48 GB abort — across ~90k RSS samples. Peak all-8
  total 339 GB (box is 503 GB).
- **All 119 topics completed** with output and a `DONE` marker; no `errors.log`,
  no engine timeouts, no tracebacks. ~1,540 judged passages/topic (median),
  174,754 total.
- **The admission guard worked exactly as designed:** exactly **2 `OVER BUDGET`
  bounces** in the whole run (both on rag2026-13's / rag2026-89's stop-word-heavy
  programs, e.g. `the`=14.8, `to`=7.5, `of`=7.5, `a`=6.4 GB), each returning the
  drop-stop-words coaching; both topics still completed. No other query breached.
- Notably, **rag2026-13 — the topic whose COO program produced the original field
  breach — completed cleanly** on the fixed build.

The bounded ~few-GB overshoot over `B` (fix 2, un-budgeted small features +
transient decompression scratch) showed up as the 42.7 GB peak against the 36 GB
budget; the operator accepted it as out of scope. Memory behaviour is now
production-validated: admission bounds the working set, the budget prevents OOM,
and full topic runs complete.

## Instrumentation (temporary, reverted)

The `[EXP]`-tagged hooks used to produce this data — a `debug_log_exp` method on
`Idx`/`SimpleIdx`, compressed-in-flight atomics, a `/proc` reader, the
`EXP_NO_BACKSTOP` env toggle, and the pinned-eviction log — were reverted with
`git restore` immediately after the run. They are described here only so the
experiment can be reproduced; they are **not** in the tree. To reproduce, re-add a
peak-RSS log at admit/post-rank and an `EXP_NO_BACKSTOP` gate on the
`load_cache` backstop, then replay `coo-program.mt.txt` against one shard at
`--posting-budget-gb 32` vs `100`.
