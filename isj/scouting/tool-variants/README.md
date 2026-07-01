# prompt × tool-shape experiment (query fixed = TREC-4 questions)

**Motivation:** the 2×2×2 factorial ([`../tiered-factorial/captured/FINDINGS.md`](../tiered-factorial/captured/FINDINGS.md))
showed the shipped `task20` prompt + the **bare-list** tool is the runaway corner (4/8 timeouts),
while giving the tool a **structure** bounds the generation. This experiment fixes the query type
to full TREC questions and crosses the prompt against the **three structured tool shapes** to see
which one best disciplines (lower `max_terms_per_facet`) and stabilizes (fewer timeouts) each prompt.

## Factors (6 cells × 4 needs = 24 generations)

- **prompt** ∈ {`scout`, `task20`} — `prompts/scout.md`, `prompts/task20.md`.
- **tool** ∈ {`V2_labeled`, `V3_angle_why`, `V4_facets_tiers`} — the structured shapes (`variants.py`):
  - `V2_labeled` — `tiers: [{label, gcl}]`
  - `V3_angle_why` — `tiers: [{angle, gcl, why}]` (each tier must state which angle it targets and why)
  - `V4_facets_tiers` — `facets: [{name, gcl}]` + `tiers: [{label, gcl}]`
- **query** — FIXED to `trec` (the full-question form). (`V1_minimal`, the bare list, is defined in
  `variants.py` for reference/control but is not a factor level.)

Same four TREC-4 needs as the factorial (207 quebec — entity-anchored, 214 hypnosis, 224 blood
pressure, 249 rain forest), excluding the prompts' worked-example topics 201/202/250.

## Response

`max_terms_per_facet` (headline bloat) + per-cell **done/timeout** counts (the runaway signal),
computed statically (`metrics.py`, copied from the factorial). `entity_dropped` for the quebec need.

## Run (fail-fast by default: 0 retries, 120 s/attempt)

```sh
uv run --directory isj python scouting/tool-variants/run.py            # full 6x4 grid
uv run --directory isj python scouting/tool-variants/run.py --needs quebec_independence   # smoke
uv run --directory isj python scouting/tool-variants/summarize.py
```

Model gpt-oss-120b, `reasoning_effort=high`, `temperature=0`, one generation per cell. Records
append to `results/records.jsonl` (resumable). A 120 s timeout is recorded as an error row (= the
runaway signal), not a crash.

## Notes

- Prompts are used as-authored; under `tool_choice="required"` with a single offered tool the model
  must call it and fill the required fields (e.g. `angle`/`why`/`facets`) even if the prompt never
  mentions them — which is the point (does the tool's structure discipline the output?).
- Files: `variants.py` (tools/needs/grid), `metrics.py`, `run.py`, `summarize.py`, `prompts/`.
