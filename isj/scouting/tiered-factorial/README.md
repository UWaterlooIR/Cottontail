# Tiered-query 2×2×2 investigation

**Question:** why does the shipped `TieredSearcher` **over-enumerate** — piling 30–50
alternatives into a single `(+ …)` facet — when the earlier scouting produced disciplined
tiers (~13 alternatives max)?

**Why we can't already answer it:** the shipped live run differed from the scouting run on
**three axes at once**, so the regression can't be attributed to any one of them:

| Axis | Scouting run (disciplined) | Shipped live run (bloated) |
|---|---|---|
| **prompt** | `scout` — "expert search-query author" (~3.9k chars, compact) | `task20` — "search analyst" (~8.9k chars, expanded) |
| **query** | `trec` — full TREC-4-style questions | `keyword` — short web-search strings |
| **tool** | `faceted` — `{facets, tiers:[{label,gcl}]}` | `list` — `{tiers:[gcl]}` |

This experiment crosses all three as a **2×2×2 factorial (8 cells)** and measures facet bloat,
so we can read the **marginal effect of each factor** (and any interaction) and decide the fix.

- Known-good corner: `scout · trec · faceted` (the scouting baseline).
- Known-bad corner: `task20 · keyword · list` (what shipped).
- The other 6 corners isolate which factor(s) actually drive the bloat.

## Factors

- **prompt** ∈ {`scout`, `task20`} — `prompts/scout.md`, `prompts/task20.md`.
- **query** ∈ {`trec`, `keyword`} — each need in `factors.py` has both forms (matched pairs, so
  only the phrasing changes).
- **tool** ∈ {`list`, `faceted`} — the two tool schemas in `factors.py`. Under
  `tool_choice="required"` with a single offered tool, the model must call that tool; a prompt
  that names a *different* tool is inert.

## Needs (matched pairs)

Four TREC-4 topics, each as a `trec` question (the verbatim topic description) and a `keyword`
string: `quebec_independence` (207, entity-anchored — `entity="quebec"` — for the entity-drop
observation), `self_hypnosis` (214), `blood_pressure` (224), `rainforest_weather` (249).

**Topics 201 / 202 / 250 are deliberately excluded**: they are the prompts' own worked examples
(au pair, nuclear treaties, firearms/crime), so testing on them would measure *parroting the
example*, not authoring. All needs are drawn from `docs/trec4/topics.201-250` outside that set.

## Response variables (in `metrics.py`, computed from the GCL text — no engine needed)

- **`max_terms_per_facet`** — the headline bloat number (scouting ~13; bloated run ~30–50).
- `mean_terms_per_facet`, `max_phrases_per_facet`, `total_quoted_phrases`, `total_gcl_chars`.
- `n_tiers`, `tier0_has_proximity` (structure sanity: a precise→broad ladder starts with a
  `(>> (# N) …)` tier).
- `entity_dropped` — for the entity-anchored need, did some tier drop the entity (a transferable
  tier)?
- **Optional live validation** (`--validate`): execute each cascade on a running cottontail
  server → `ok` / `parse_fail` (a tier 400s) / `timeout_degenerate` (parses but too big to run).
  Off by default; the static metrics are the primary signal.

## Files

```
factors.py     prompts, matched needs, the two tool schemas + extractors, the 8-cell grid
metrics.py     static over-enumeration metrics from GCL text
run.py         the harness: generate over the grid, score, (optional) validate; incremental + resumable
summarize.py   per-cell table + per-factor marginals + rollups
prompts/       scout.md (recovered), task20.md (= shipped tiered_searcher.md)
results/       records.jsonl written here (gitignored)
```

## Running (review first — do not run until we agree)

From the repo root, with vLLM up (and, for `--validate`, a **TASK-19-built** cottontail server):

```sh
# 1-need smoke (8 calls) to sanity-check the harness:
uv run --directory isj python scouting/tiered-factorial/run.py --needs au_pair

# full grid (8 cells × 4 needs = 32 generations; ~30-60 min at high reasoning -> background it):
uv run --directory isj python scouting/tiered-factorial/run.py

# add live parse/exec validation (needs the server on :8080):
uv run --directory isj python scouting/tiered-factorial/run.py --validate

# summarize:
uv run --directory isj python scouting/tiered-factorial/summarize.py
```

Resumable: re-running skips `(cell, need)` pairs already in `results/records.jsonl`.
Knobs: `--effort`, `--temperature`, `--model`, `--vllm`, `--server`, `--needs`, `--validate-timeout`.

## Interpreting

- **Marginals** in `summarize.py` show each factor's mean `max_terms_per_facet` averaged over the
  other two. A large gap between a factor's two levels ⇒ that factor drives the bloat.
- Compare the two known corners against the isolated ones to spot **interactions** (e.g. the
  `faceted` tool might discipline `task20` even on `keyword` queries).
- Outcome feeds the fix: pick prompt / tool / query-handling that minimizes bloat while keeping
  valid, precise→broad, entity-aware tiers — then re-validate before finalizing TASK-20.

## Provenance / caveats

- `scout.md` and the `faceted` (`submit_tiered_query`) schema were recovered from the session
  transcript `d0a817e3…jsonl` (the tiered-scouting harness, ~lines 825–828). `task20.md` is a copy
  of `isj/isj_agent/agents/tiered_searcher.md` as shipped.
- Prompts are tested **as authored**; each mentions its own tool name, which is inert under a
  single required tool (see above).
- `temperature=0` but gpt-oss still has mild nondeterminism; one entity-anchored need limits the
  entity-drop read (it is observational, not a factor).
- This measures **query authoring** (one generation per cell/need), not the full multi-turn loop —
  the right scope for the over-enumeration question.
