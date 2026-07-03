---
id: TASK-25
title: Adopt parallel_ssr in cottontail-jsonl-server/-query (cp-native parallel SSR)
status: Done
assignee:
  - '@claude'
created_date: '2026-07-03 00:47'
updated_date: '2026-07-03 02:37'
labels: []
dependencies:
  - TASK-24
priority: high
ordinal: 39000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Bring Charlie's parallel ranking speedup into OUR search stack — both ranking paths, decided with Mark 2026-07-03:

1. **parallel_ssr swap**: upstream acf9237e added parallel_ssr() to src/ranking.cc — it splits a shard's token span into contiguous ranges (>=1M tokens each, capped by allowed_threads), runs the SSR recurrence per range on a warren->clone() per worker, merges per-range top-k. jsonl_query() in apps/jsonl_core.cc has 5 ssr_ranking call sites (stemmed, gcl, ssr ranker, icover single-term fallback x2 forms); route them through parallel_ssr. Signature-compatible; SimpleWarren implements clone_().

2. **parallel cover_ranking**: the isj agent's actual tools (cover_search, tiered_query_search) do NOT use ssr_ranking — they use fork-owned cover_ranking() (apps/jsonl_core.cc), a single-pass SSR-mirroring walk that also computes total_matches/unjudged_matches as a byproduct. Parallelize it with the same range-split pattern (container assigned to the range holding its cp, exactly like ssr_ranking's start/end semantics — so counts sum exactly and scores are identical): clone per worker, per-worker heap + counters, merge heaps, sum counters. tiered_query_search gets the speedup for free since it calls cover_ranking per tier.

**Threads knob (--rank-threads, distinct from the server's existing --threads = HTTP handler pool):**
- cottontail-jsonl-query: --rank-threads N, default 0 = allowed_threads(0) (auto; one query per process).
- cottontail-jsonl-server: --rank-threads N, default 0 = AUTO-BUDGET = max(1, allowed_threads(0) / handler --threads) — 64/4 = 16 on the 32-core dev box. Caps worst-case busy threads at allowed_threads regardless of concurrent agent intents. Server-level setting only; NOT exposed on the wire or in the agent tool schema.
- Key facts (verified): SimpleWarren clones share one SimpleIdx and its posting cache — rank threads add NO redundant posting loads or RAM; hoppers are cursors over shared decompressed arrays. allowed_threads(0) = 2x hardware.

**Out of scope (flagged, not done):** icover_ranking and tiered_ranking internals (upstream src code — no parallel variants upstream; keep src/ aligned); per-request rank_threads on the HTTP protocol; posting-cache bounding (separate concern, see memory/upstream-sync-claclark and the 400b cache analysis: unbounded cache + stopword postings = 100s of GiB on the full collection).

Parity caveat: parallel and sequential score identical containers identically; only equal-score ties at the top-k boundary may differ — compare (cp,score) multisets in validation.

Validation burrows: Scrapheap/climbmix-1M-porter.burrow and /share/indexes/climbmix-100M-porter.burrow (outside-repo path pre-approved, read-only). 100M latency measurements via the CLI — do NOT restart the running dev jsonl-server (leave-dev-server-running agreement); it picks up the feature whenever Mark chooses to restart it.

Depends on TASK-24 (merged as PR #8). Branch: claude/ssr-parallel-etc.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 cottontail-jsonl-query and cottontail-jsonl-server expose --rank-threads (query CLI default 0 = allowed_threads(0); server default 0 = auto-budget allowed_threads(0)/handler-threads, min 1, logged at startup); the knob is server-level only — the HTTP protocol and agent tool schema are unchanged
- [x] #2 All 5 ssr_ranking call sites in jsonl_query() route through parallel_ssr(); cover_ranking() is parallelized with the same range-split pattern (per-worker clone + heap + counters, exact counter sums), and cover_search + tiered_query_search use it
- [x] #3 Parity: on Scrapheap/climbmix-1M-porter.burrow, rank-threads=1 vs parallel return identical (cp, score) result multisets and identical total/unjudged match counts for a fixed query set covering --text ssr, --gcl, cover_search, and tiered_query_search
- [x] #4 A unit test exercises the multi-range parallel cover_ranking merge on a small fixture (range minimum parameterized so tests do not need a >=2M-token index); bazel test //test:all and the isj Python suite stay green
- [x] #5 Measured latency for a fixed query set on Scrapheap/climbmix-1M-porter.burrow and /share/indexes/climbmix-100M-porter.burrow, rank-threads=1 vs auto, recorded in task notes (via the CLI; the running dev server is not restarted)
- [x] #6 running-the-search-stack.md documents --rank-threads for both binaries incl. the server auto-budget rule; CLAUDE.md's ssr-apps note updated (TASK-25 no longer pending); PR opened from claude/ssr-parallel-etc to main
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Setup
   1.1 Mark TASK-25 In Progress, assign @claude. Work on the existing branch claude/ssr-parallel-etc (already on merged main).

2. Parallel cover_ranking (apps/jsonl_core.cc) — the core new code
   2.1 Add [start,end) range parameters to the existing sequential cover_ranking() (defaults minfinity/maxfinity), mirroring ssr_ranking's semantics exactly: chopper->tau(start) to find the first container with cp >= start, main loop also guarded by cp < end. A container is scored by exactly the range holding its cp — this is what makes parallel results and counter sums exact.
   2.2 Add parallel_cover_ranking(warren, query, depth, exclude, ranked, total, unjudged, error, threads, min_range_tokens = 1'000'000): compute the container span (first tau / last ohr on :item, as parallel_ranking does in src/ranking.cc); threads = min(allowed_threads(threads), span/min_range_tokens, >=1); threads <= 1 -> call sequential directly (bit-identical today's behavior). Otherwise: contiguous ranges by the same arithmetic as parallel_ranking; one warren->clone() per worker (clones share the SimpleIdx posting cache — no redundant loads); per-worker ranked vector + total/unjudged counters over the SHARED read-only exclude set; join; merge = concatenate, stable sort by score desc, truncate to depth; totals = sums. Propagate the first worker error; any error -> return false.
   2.3 min_range_tokens is a parameter (not a constant) solely so the unit test can exercise the multi-range merge on a tiny fixture; production call sites use the 1M default.

3. Route the SSR call sites (apps/jsonl_core.cc)
   3.1 QuerySpec, CoverSpec, TieredSpec each gain size_t rank_threads = 0 (0 = resolve at the binary's default policy; specs built from HTTP JSON NEVER read it from the request — server-level only).
   3.2 jsonl_query(): replace all 5 ssr_ranking(warren, q, container, spec.top_k) sites with parallel_ssr(warren, q, container, spec.top_k, spec.rank_threads) via the existing inline overload. parallel_ssr(threads<=1) falls back to the sequential recurrence, so rank_threads=1 preserves today's behavior exactly. icover_ranking and tiered_ranking calls untouched (upstream src internals — flagged out of scope).
   3.3 jsonl_cover_search() and jsonl_tiered_query_search(): their cover_ranking() calls (lines ~868, ~1018, ~1044) become parallel_cover_ranking(..., spec.rank_threads). The atom_counts / cover_leaves loops stay sequential (cheap, count-only).

4. CLI (apps/cottontail-jsonl-query.cc)
   4.1 --rank-threads N flag; default 0 -> allowed_threads(0) at spec-build time. Applies to --text/--gcl/--cover/tiered and --batch (per query). Update usage text. Do NOT add it to --describe's agent tool schema.

5. Server (apps/cottontail-jsonl-server.cc)
   5.1 --rank-threads N flag; default 0 -> auto-budget: max(1, allowed_threads(0) / handler_threads) computed once at startup (handler_threads = the existing --threads after its min-1 clamp). Explicit N is passed through allowed_threads(N) capping. Stamp the resolved value into every spec built from a request; log it in the startup line (e.g. "rank_threads=16 (auto)"). Usage text distinguishes the two knobs.

6. Tests (test/jsonl.cc, test/jsonl_cli.cc, test/jsonl_server.cc)
   6.1 Parity unit test: on the existing small fixture, run cover_ranking sequential vs parallel_cover_ranking with min_range_tokens tiny (e.g. 8) and threads 3 — identical (cp,score) sequences and identical totals; repeat with a non-empty exclude set. Same-fixture check that parallel_ssr-routed jsonl_query (rank_threads 0/1/4) returns identical hits (falls back to sequential below 1M tokens — that IS the expected behavior, assert it holds).
   6.2 CLI test: --rank-threads parses; bad value dies cleanly. Server test: flag accepted; startup log shows resolved value.
   6.3 Full: bazel test //test:all + isj uv run pytest (no isj changes expected — protocol unchanged).

7. Validation on real burrows (read-only; CLI only — the running dev server is left alone)
   7.1 Parity (AC3): fixed query set (>=6 queries: multi-term text ssr, --gcl incl. a quoted phrase, cover_search-style w/ exclude, tiered) on climbmix-1M-porter: --rank-threads 1 vs 0; compare (cp,score) multisets + match counts. Ties at the top-k boundary are the only allowed difference; if seen, verify they are genuine score ties and note them.
   7.2 Latency (AC5): same query set, warm (run twice, report second), rank-threads 1 vs auto, on 1M and 100M burrows; record a small table in task notes. If parallel is NOT faster on the 100M shard, report the numbers and stop for discussion before tuning further (no silent scope growth).

8. Docs
   8.1 docs/design/reference-specs/running-the-search-stack.md: --rank-threads for both binaries, the server auto-budget rule and its interaction with --threads, and the guidance that rank-threads shares one posting cache (no RAM multiplier).
   8.2 CLAUDE.md: update the ssr-apps bullet (cp-native parallel SSR now in our server; TASK-25 reference resolved).

9. Finalize
   9.1 Task notes (parity results, latency table, anything off-plan observed but not acted on), check ACs, push branch, open PR to main. backlog instructions task-finalization.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implementation committed (dc6470b). One design wrinkle vs plan: cover_ranking's sequential result order gained a deterministic cp tiebreak (score desc, cp asc) so sequential and parallel agree exactly even on score ties — same result multiset as before. parallel_cover_ranking is exported from jsonl_core.h (needed external linkage anyway; the first build failed with the definition inside the file's anonymous namespace — moved out). All 5 bazel test targets + isj (118 pass/1 skip) green.

Validation (read-only; dev server untouched, temp servers on ports 18081/18082 since stopped). PARITY on climbmix-1M: rank-threads 1 vs 0 identical full JSON (elapsed_ms stripped) for text-ssr x2, gcl x2 (incl. quoted phrase), cover x3 (incl. 2-cp exclude), icover, and via temp servers search_text/cover_search/tiered_query_search. Initial run had ONE boundary mismatch: rank-10 score tie (0.523810 both) chose different cps — fixed properly by making the sequential bounded heap use the same (score desc, cp asc) order as the parallel merge (cover_order), so parity is now exact even at tied boundaries; no caveat needed. LATENCY (warm, seq vs auto): 1M burrow — single queries already ~0.13s (no headroom), tiered 1.26s -> 0.29s (4.3x). 100M shard (auto-budget resolved to rank_threads=16 with 4 handlers, as designed): search_text/ssr 1.1s -> 0.2s (4.7x); cover_search 0.4 -> 0.2s (1.7x); cover_search with phrase 1.3 -> 0.2s (5.4x); tiered_query_search 100s -> 6.7s (14.9x). Cold numbers improve similarly (tiered 100.6 -> 7.6s).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented cp-native parallel ranking for the JSONL stack; PR #9 (https://github.com/UWaterlooIR/Cottontail/pull/9). New parallel_cover_ranking (range-split by container cp, clone-per-worker, exact counter sums, deterministic score/cp ordering incl. the sequential heap) powers cover_search and tiered_query_search; jsonl_query's five ssr_ranking sites route through upstream parallel_ssr. --rank-threads on both binaries: CLI default auto, server default auto-budget (allowed_threads / handlers = 16 on this box), server-level only, wire protocol unchanged. Verified: exact parity (rank-threads 1 vs auto) on climbmix-1M across all query modes incl. score-tie boundaries; 100M-shard warm speedups 1.7-14.9x with tiered_query_search 100s -> 6.7s; multi-range unit tests via parameterized range minimum; bazel 5/5 + isj 118/1skip green; dev server untouched.
<!-- SECTION:FINAL_SUMMARY:END -->
