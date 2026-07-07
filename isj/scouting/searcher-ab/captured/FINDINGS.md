# Findings — Searcher A/B: cover vs JSON-tiered vs MultiText (TASK-22 AC#7, 2026-07-04)

**Design.** 3 searcher classes × 6 general-web questions through the full isj
pipeline (CLI subprocess), 1M burrow (port 8081, `rank_threads=8`). Fairness =
**docs judged**: `max_judgments=250`/run identical across arms (`max_queries=50`
non-binding backstop). Searchers AND judger at `reasoning_effort=medium`;
judger concurrency 25; Analyst temp 0 (intents still vary across runs —
batched-inference nondeterminism). Engine client timeout 1h (TASK-29); judge
failures record `-2` sentinels (TASK-27). Harness cap 4h/run, recorded not
fatal. Data: `2026-07-04-manifest.jsonl`, `2026-07-04-summary.txt`; raw runs in
`../results*/` (gitignored).

## Headline rollup

| arm | topics done | judged | ≥1 | ≥2 | =3 | ≥2/judged | wall |
|---|---|---|---|---|---|---|---|
| cover | 6/6 | 1573 | 1099 | **399** | **37** | **0.25** | **42 min** |
| multitext | 6/6 | 1559 | **1129** | 325 | 18 | 0.21 | 2.5 h |
| tiered (JSON) | **4/6** | 1100 | 800 | 179 | 5 | 0.16 | 4.0 h + 8 h wasted |

`tiered/invasive` and `tiered/inflation` **DNF at the 4-hour cap** — the
FollowedBy phrase pathology at full strength (its prompt leans hardest on
quoted phrases + `(# N)` windows).

## Per-topic relevant sets (topic level: union over intents, best grade per doc)

| topic | cover ≥2 (≥1) | tiered | multitext | 3-way union ≥2 | Jaccard ≥1 c-t / c-m / t-m |
|---|---|---|---|---|---|
| fasting | 64 (157) | 50 (170) | 71 (216) | 91 | 0.58 / 0.61 / 0.60 |
| solarloss | 16 (92) | 12 (142) | 17 (155) | 27 | 0.15 / 0.25 / 0.28 |
| reading | 34 (169) | 41 (197) | **64** (190) | 112 | 0.23 / 0.14 / 0.27 |
| invasive | **116** (209) | DNF | 63 (185) | 143 | – / 0.22 / – |
| inflation | 19 (101) | DNF | 18 (120) | 27 | – / 0.34 / – |
| vaccines | **98** (233) | 54 (142) | 80 (232) | 173 | 0.11 / 0.17 / 0.12 |

## What we can say

1. **cover is today's best single searcher**: most ≥2 (399) and grade-3 (37)
   docs, 4–6× faster than the others, zero failures. It wins ≥2 on 4/6 topics.
2. **multitext is the best tiered-style searcher and the recall leader**: most
   ≥1 docs overall, only tiered-style arm to finish 6/6, and it *wins* reading
   outright (64 vs 34 ≥2). Costs: ~2× cover's tokens/turns and one habit-level
   weakness — under pressure the model still writes underscore macro names
   (5 compile bounces on invasive; **all self-corrected via the diagnostics
   bounce — the TASK-22 design working as intended**) and occasionally answers
   in content instead of the tool in long conversations (15 no-tool-call turns
   in inflation's 36-turn run; each bounced and recovered).
3. **JSON-tiered is dominated on every axis** by multitext: slower (its two DNFs
   burned 8 h of cap), lower yield, no compile safety net. With multitext
   available there is no reason to prefer it.
4. **The searchers are complementary, not redundant.** Pairwise Jaccard of ≥1
   sets is 0.11–0.61; the 3-way ≥2 union beats the best single arm on every
   topic (e.g. reading 112 vs 64; vaccines 173 vs 98). Fusion of cover +
   multitext would substantially beat either. Caveat: cross-arm grade drift
   exists (same doc, different summary → different grade), so ≥1 overlaps are
   the cleaner retrieval signal; part of ≥2 set difference is judge variance.
5. **Latency is the tiered-style arms' real handicap and it is a known,
   fixable engine cost** (FollowedBy re-drive; TASK-30/31). The A/B should be
   re-scored after those land — multitext's craft advantage (it authored the
   reading win) is currently taxed heavily by phrase grind.
6. Robustness fixes proved out live: ONE judge call failed permanently and
   became a `-2` sentinel instead of killing the run (TASK-27); zero engine
   timeout bounces (TASK-29); the two DNFs were recorded, not fatal.

## Recommendation

Keep **cover as the default** searcher today. Make **multitext the selectable
tiered searcher** (it obsoletes the JSON TieredSearcher). Revisit after
TASK-30/31: if the phrase fix lands, rerun this A/B (same harness) — and
consider a cover+multitext fusion run, which the overlap data says is the real
prize. Prompt touch-ups for multitext worth taking now: strengthen the
no-underscore rule (it is the only recurring compile error) and re-anchor
tool-only output for long conversations.
