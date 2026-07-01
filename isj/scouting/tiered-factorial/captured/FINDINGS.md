# Findings — tiered-query 2×2×2 factorial (2026-07-01)

**Question:** why does the shipped `TieredSearcher` over-enumerate / run away, when the earlier
scouting produced usable tiers? The shipped live run differed from scouting on three axes at
once (prompt, query style, tool), so this factorial crosses all three to isolate the cause.

**Design:** `prompt`{scout, task20} × `query`{trec, keyword} × `tool`{list, faceted}, 4 needs per
cell. Model gpt-oss-120b via vLLM, `reasoning_effort=high`, `temperature=0`, **one generation per
cell** (query authoring, not the multi-turn loop). Primary response = `max_terms_per_facet`
(operands in the fattest `(+ …)` group), computed statically from the emitted GCL.

**Needs (TREC-4 topics, excluding the prompts' own worked examples 201/202/250):**
207 `quebec_independence` (entity-anchored), 214 `self_hypnosis`, 224 `blood_pressure`,
249 `rainforest_weather`.

**Run status (important):** the full grid was **aborted mid-run** — all 16 `scout` cells
completed under the original client (600 s timeout, 2 retries); the `task20` half was then re-run
**fail-fast** (120 s timeout, 0 retries). Numbers below use the 16 clean `scout` cells + the 16
fail-fast `task20` cells.

## Results

```
prompt query   tool      done/tot  timeout  meanTerms  maxTerms
scout  keyword faceted      4/4        0       18.2       20
scout  keyword list         4/4        0       15.2       24
scout  trec    faceted      4/4        0       18.2       25
scout  trec    list         4/4        0       17.5       23
task20 keyword faceted      3/4        1       15.7       29
task20 keyword list         3/4        1       12.3       22
task20 trec    faceted      4/4        0       22.8       36
task20 trec    list         1/4        3       15.0       15

PROMPT   scout    16/16 done, 0 timeouts, mean 17.3, max 25
         task20   11/16 done, 5 timeouts, mean 17.3, max 36
PROMPT×TOOL  scout·list     0/8 timeout, mean 16.4, max 24
             scout·faceted  0/8 timeout, mean 18.2, max 25
             task20·list    4/8 timeout, mean 13.0, max 22   <- runaway corner
             task20·faceted 1/8 timeout, mean 19.7, max 36
ENTITY-DROP  scout 4/4, task20 4/4 (the quebec need dropped the entity in a transferable tier)
```

## Findings

1. **It is NOT average bloat.** Among *completed* cells both prompts enumerate the same
   (mean **17.3** terms/facet). `scout` is not "clean" — it over-enumerates too (up to 24 terms /
   ~10 quoted phrases per facet).

2. **The regression is runaway INSTABILITY, and it's a prompt×tool interaction.** `task20` timed
   out **5/16**; `scout` **0/16**. The runaways concentrate in the **bare `list`** tool:
   `task20·list` **4/8** timeouts vs `task20·faceted` 1/8 vs `scout·(either)` 0/8.

3. **Mechanism.** The `task20` prompt over-enumerates, and the unstructured `list` tool gives the
   generation no bound → it keeps decoding → **runaway → timeout** (this is the original 30-min
   hang). Tellingly, `task20·list`'s *completed* cells look lean (mean 13) — survivorship: the
   bloated generations time out and never get counted. The **`faceted`** tool (required `facets` +
   labeled tier objects) gives a hard structure so it terminates (1/8) — but still bloats (max 36).
   `scout` enumerates less aggressively, so it is stable under both tools with a tighter tail (max 25).

4. **Heavier tail for `task20`** (max 36 vs scout 25).

5. **Entity-drop works** for both prompts (4/4 on the anchored `quebec` need).

6. **Stochastic.** Which cells run away varies run-to-run (temperature-0 gpt-oss is not truly
   deterministic on batched inference): in the aborted grid `quebec` timed out and `self_hypnosis`
   completed; in the fail-fast rerun it flipped. So exact timeout counts are noisy, but the
   direction (`task20·list` runs away, `scout` never does) held across both runs.

**Correction on record:** the first 30-min timeout was initially called a "transient vLLM stall."
That was wrong — the fail-fast rerun reproduced timeouts on 5/16 `task20` cells, so it is the
prompt×tool **runaway**, not an environment blip.

## Conclusion / fix direction

The shipped agent is `task20` prompt + `list` tool — the single corner that runs away ~half the
time and has the worst tail. Move the prompt scout-ward (eliminates runaways, tightens the tail)
and/or give the tool a structural bound (`list → faceted` cut runaways 4/8 → 1/8), plus an explicit
facet-size cap to pull the mean down from ~17. The **tool shape** deserves its own study — see the
follow-up `../../tool-variants/`.

## Caveats

- n = 4 needs/cell; the outcome is stochastic; the grid was aborted (mixed client configs across
  the two halves, controlled for by using the clean `scout` cells + the fail-fast `task20` rerun).
- Metric counts all `(+ …)` operands (`word*` + bare + quoted phrases), not phrases alone.
- One generation per cell — the multi-turn loop is out of scope here.

## Data (this directory)

- [`2026-07-01-scout-partial.records.jsonl`](2026-07-01-scout-partial.records.jsonl) — 16 scout cells + 2 leaked task20 cells (old client).
- [`2026-07-01-task20-rerun.records.jsonl`](2026-07-01-task20-rerun.records.jsonl) — the 16 fail-fast task20 cells.
- [`2026-07-01-combined-summary.txt`](2026-07-01-combined-summary.txt) — the clean combined tables above.
- [`2026-07-01-scout-partial.summary.txt`](2026-07-01-scout-partial.summary.txt) — scout-only summary.

Harness that produced these: [`../factors.py`](../factors.py), [`../run.py`](../run.py),
[`../metrics.py`](../metrics.py), [`../summarize.py`](../summarize.py), [`../README.md`](../README.md).
