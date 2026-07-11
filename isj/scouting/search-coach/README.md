# Scout: RelevanceFeedbackCoach (search-coach v1)

Scouting for the design in [`docs/design/search-coach.md`](../../../docs/design/search-coach.md).

**Question:** does the v1 relevance-feedback coach behave well enough that we can skip the
design's "guaranteed floor" (always keep the top 1-2 by rank)? I.e. does the coach ever
*whiff* — drop the strong (high-grade / top-ranked) results when curating?

## What it does

`run.py` takes a Searcher run's `intent-NN.json` (compiled judged results). For each
`surfacing_query` it reconstructs that query's slice — top `input_top_k`(25) by search
score + any deeper result graded `>= input_min_grade`(3) — and feeds the slice to
`gpt.oss.120b` with the v1 RF-coach prompt (`prompt.md`): select informative passages,
observe what separates relevant from non-relevant, recommend vocabulary. Structured JSON
output; temperature 0; reasoning medium; query-blind and atom-blind (matches the design).

Every run **saves a full transcript** to `captured/<topic>-intent-NN-qNN.md`: the exact
passages fed, the model's raw `reasoning_content`, its raw JSON output, and the parsed
picks mapped back to docnos/grades — so the raw LLM behavior is readable, not just summaries.

## Versions & results (convention)

**Never edit a version or its results in place.** A version is a **pair** — a prompt file
AND a guided-output schema file — because BOTH steer the model: the JSON schema's field
names and `description` text are sent to vLLM for guided decoding and affect behavior just
like the prompt (v1's schema says the observation is "1-3 sentences"; v2's says "your
coaching report…"). Each version gets its own results directory.

- `prompt-v1.md` + `schema-v1.json` — terse relevance-feedback (select + 1-3 sentence
  observation + terms).
- `prompt-v2.md` + `schema-v2.json` — expert-searcher coaching report with `[R#]` citations.
- results land in `captured/<prompt-stem>/` (e.g. `captured/prompt-v1/`, `captured/prompt-v2/`).

To try a new idea, add `prompt-v3.md` + `schema-v3.json` (copy + edit) and run with
`--prompt prompt-v3.md`; do not overwrite an existing version. `--schema` defaults to the
matching `schema-vN.json`. `run.py` is the only constant harness (trace reconstruction +
transcript writing).

## Run

```sh
# from isj/ (uses the venv). --prompt defaults to prompt-v1.md.
uv run python scouting/search-coach/run.py <path-to>/results/gcl-cover/14/intent-00.json --prompt prompt-v1.md
# options: --queries N (limit slices), --max-str N (truncate summary/reason)
```

Needs vLLM serving `gpt.oss.120b` on :8000. Reads a run's `intent-NN.json` (path is an
argument; the runs live in the trec-rag-2026 repo).

See [`captured/FINDINGS.md`](captured/FINDINGS.md) for results.
