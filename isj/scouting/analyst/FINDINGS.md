# Analyst scouting — findings

**Result: prompt-v3 shipped as `isj_agent/agents/analyst.md` (2026-07-12).**

## Why we scouted

On dev topic 14 the Analyst over-decomposed (3 interpretations) and emitted a **source-type-framed**
intent — *"identify books, reports, or academic papers that discuss …"*. On the ClimbMix web corpus
that sent the Searcher into a 100-turn dead end (`intent-02`: 40% no-query bounces, ~7.6M tokens,
~0 gold hits). Root cause traced to the Analyst's decomposition, so we scouted the prompt.

## Harness

`run.py` runs a prompt variant (`--prompt prompt-vN.md`) over the 22 RAG25 dev topics
(`dev-topics.tsv`, a fixture copy) and prints the generated interpretations, flagging
source-type framing. Needs only vLLM (the Analyst is one LLM call — no search), so it runs with the
shard array down. Raw `Intents` JSON per topic saved under `captured/<prompt-stem>/`.

## Prompt progression

- **v1** — snapshot of the shipped `analyst.md` (baseline). Source-type framing **7/63** interps
  (incl. topic 14 "scholarly sources / articles"); counts 1–6; some redundant "umbrella" intents.
- **v2** — added a Role note: the collection is source-less web text; don't inject source demands
  unless the user asks. Fixed topic 14, but framing survived on health/science topics (233/225/897);
  **6/65**. Exposed the umbrella pattern (213 → an all-encompassing [1] + the same facets).
- **v3** — strengthened the source ban ("the downstream system decides trustworthy sources itself;
  do not specify sources unless requested"), added an anti-redundancy rule ("do not create multiple
  interpretations that say the same thing"), and dropped the "order most-plausible-first" instruction.

## v3 results (over the 22 dev topics)

- **Source-type framing 7 → 1** — only topic 225 [1] ("Research studies …") remains. Topic 14 and
  the health/science topics are clean.
- **Umbrella redundancy eliminated** — 213 went 7 → 6 with [1] now a specific facet (not the union of
  the rest); 219's umbrella gone.
- **Interpretation count still noisy / not reduced** (`1→5,2→5,3→3,4→6,5→1,6→2`); a few topics
  decompose *more* (499: 1→4, 224→5). Left as an open lever — the decompositions read as reasonable.

## Open / noted

- The lone remaining source-framing (225 "Research studies").
- Over-decomposition / count stability is untouched (no soft cap tried).
- v3 dropped "order most-plausible-first"; harmless for the current controller (budget splits evenly
  across intents), but note the `Intents` schema docstring still claims that ordering.
