# Notes for the coding agent: search-coach v3 (free-text report)

Audience: the agent doing the next round of work on `scouting/search-coach/`
(and eventually the `RelevanceFeedbackCoach` in the real Controller).
Context: `docs/design/search-coach.md`, `prompt-v3.md`, and the modified `run.py`.

## What changed and why

v2 (guided JSON) produced summaries instead of coaching reports. Root causes, in
order of weight:

1. **Guided decoding forced `selected` to be emitted before `observations`** —
   the model had to commit its citations before writing any analysis, inverting
   the task's natural order.
2. **`recommended_terms` as a separate field siphoned off the "how to improve"
   section** — the model treated the terms array as the advice and wrote only a
   what's-relevant summary in the prose.
3. **Three brevity instructions ("concise", "tight", "do not pad") vs. one
   coverage instruction** — at temperature 0 the compression signals won.
4. **Long-form prose inside a JSON string field degrades** under constrained
   decoding on this model/stack (gpt-oss-120b on vLLM; the reasoning-parser /
   structured-output interaction for GPT-OSS also has open upstream bugs, e.g.
   vllm-project/vllm #23120, #37359).

v3 therefore drops guided decoding entirely. The coach emits a plain markdown
report; nothing in the output is machine-oriented. `selected` is derived by
regex over the `[Rn]` handles the report cites.

## How the scout now runs

- `--prompt prompt-v3.md` with no `--schema`: the derived `schema-v3.json`
  does not exist, so the run is **free-text** (no `response_format`). v1/v2
  replays are unchanged (their schema files exist, so they stay guided).
- Free-text transcripts keep the same diagnostics (grades of picks, kept
  top-grade doc, kept R1/R2, invalid handles) computed from **cited** handles,
  plus a report word count. Console line mirrors this.
- Versioning convention update needed in `search-coach.md` and the `run.py`
  docstring wording: a version is a (prompt, schema) pair **only when guided**;
  v3+ may be prompt-only.

## Things to verify on the first v3 run

1. **Harmony leakage into `content`.** Without `response_format`, gpt-oss on
   some serving stacks leaks reasoning prefixed with `analysis` into the
   content field. The v1/v2 runs returned clean JSON, so this stack's
   final-channel extraction is probably fine — but read the `## coach OUTPUT
   (raw)` section of the first transcript before trusting the batch. If it
   leaks, the fix is server-side (vLLM reasoning parser config), not in
   `run.py`.
2. **Report shape.** Confirm the three sections appear, that section 3 contains
   genuine directives (not restated observations), and that the "Vocabulary
   worth pursuing:" line is present. These were exactly the v2 failure points.
3. **`reasoning_content` is still `(none exposed)`** because the server runs
   without `--reasoning-parser`. Reasoning IS happening (behavior differs
   between `reasoning_effort` medium/high; high can loop endlessly — keep
   medium). If you want the reasoning visible in transcripts, add
   `--reasoning-parser openai_gptoss` to the `vllm serve` command — but that
   flag interacts with the open upstream bugs above, so verify one query
   end-to-end after changing it.

## Known gaps / deliberate trade-offs

1. **Citation-as-selection incentive gap.** The prompt does not tell the model
   that its citations determine which passages get forwarded (telling it would
   invite over-citing). A strong report that under-cites therefore forwards few
   passages. The design's guaranteed floor (Controller always forwards the top
   1–2 by rank) covers this in production; in the scout, the `kept_top` /
   `kept R1 or R2` lines now measure *citation habits*, not deliberate
   selection — read WHIFF flags with that in mind before "fixing" anything.
2. **`--max-str 600` truncates assessor reasons mid-sentence.** The coach now
   writes prose grounded in those reasons, so clipped inputs matter more than
   they did for v1's term-picking. Consider raising the cap or truncating at a
   sentence boundary; if you change it, re-run v1/v2 comparisons with the same
   value or the comparison is confounded.
3. **Hallucinated handles** (cited `[Rn]` not in the input) are extracted and
   reported per-query (`bad_handles=...`). Zero is the expectation; any
   nonzero count is a prompt-adherence signal worth tracking across queries.
4. **`max_selected` from the design config is not enforced** in the scout. If
   v3 reports routinely cite more than ~8 handles, the Controller-side cap (or
   a prompt nudge) becomes relevant; measure first.

## When porting v3 into the real `RelevanceFeedbackCoach`

- `CoachResult.report` = the raw markdown; `CoachResult.selected` = the deduped
  cited handles mapped back to docnos. The regex is `\[(R\d+)\]`, first-mention
  order, deduped, unknown handles dropped (and logged).
- A report with no parseable citations is NOT a coach failure — forward the
  report with the guaranteed-floor selection. Reserve the mechanical fallback
  for transport/timeout/empty-output failures.
- The feedback contract in `search-coach.md` §"What the Searcher always sees"
  is unchanged: the report is item 4's advice text; expansion of `selected` to
  verbatim summary+reason still happens Controller-side.
