# SearchCoach — a pluggable relevance-feedback layer for the Searcher

Status: design draft (for review). Not yet implemented.

## Problem

Each turn, the Searcher agent does two cognitively different jobs: it **diagnoses**
what its last query did (reading a pile of judged results + stats), and it **authors**
the next query. That is a lot to hold at once, and it competes for the Searcher's
bounded context.

Today the Controller feeds the Searcher back a **mechanically-sliced** view of the
judged results (TASK-36: the top `top_results_to_show` by rank, plus any deeper result
graded `>= min_show_grade`) so as not to blow the Searcher's context. That slice keeps
context bounded, but it is a dumb fixed rule, and it still leaves the Searcher to do the
"what is relevant here / what words should I try next" thinking over the raw material.

We want to move the "digest the judged pile into high-value guidance" work off the
Searcher onto a dedicated, ephemeral agent — and make that layer **pluggable**, so
today's mechanical behavior is just one (low-intelligence) implementation and we can
drop in a smarter one behind the same interface.

## Overview

Introduce a `SearchCoach` abstraction: given the per-query judged results and stats,
it produces the distilled feedback the Searcher sees after the Judger stops judging.

Two implementations behind one protocol:

- **`MechanicalSearchCoach`** — today's rule-based selection (top-N by rank + grade
  threshold). Pure code over data the Controller already has; deterministic; **cannot
  fail**. Its parameters move out of `[loop]` into its own config.
- **`RelevanceFeedbackCoach`** — an LLM that reads the information need and the judged
  results, selects the informative ones, and recommends vocabulary/phrases. It is
  **query-blind and engine-agnostic** (see scope below).

The Controller is configured with one coach. **If the configured coach fails, the
Controller falls back to the mechanical coach**, which always works — so the
intelligent path can fail without ever failing the run.

## v1 scope: a Relevance Feedback Agent, not a query coach

To keep v1 small and trackable, the LLM coach is deliberately a **relevance-feedback
agent**, not a search coach that understands query machinery.

**The coach is given:**

- the **information need** (the interpretation being searched),
- **computed stats** about the judged results (relevance distribution, already-judged /
  retread counts, total matches, descent depth),
- a **relevance-feedback selection** of the judged results — the **top `input_top_k`
  (default 25) by rank, plus any result deeper than that graded `>= input_min_grade`** —
  each with its `summary`, the assessor's `reason`, and `grade`. (Every one carries a
  grade: the top ranks are judged this query or cached from a prior query, and the deep
  ones are pulled in precisely because they were graded high.)

  This selection is, by construction, **today's mechanical search summary** — the
  top-N-by-rank plus the high-grade nuggets found deeper — built by the same
  `select(descended, top_k, min_grade)` helper the mechanical coach uses (below). We are
  feeding the coach today's summary and asking it to distill a *better* one. A deep
  grade-4/3 result the current scheme would surface to the Searcher is therefore also
  seen by the coach; it is never dropped just for being past rank 25.

**The coach is NOT given:**

- the Searcher's **query** or any query **machinery** (GCL, the MultiText DSL, Lucindri
  syntax),
- the Searcher's **prompt / instructions**,
- the **atom-match counts**.

**Why this boundary:**

- **Engine-agnostic.** Knowing no query language, the *same* coach serves every searcher
  — Cottontail cover / tiered / multitext, and Lucindri — with no per-language knowledge
  and no duplicated query-language reference in the coach prompt.
- **No syntax leakage.** Withholding the query and atom terms keeps the coach from
  picking up and imitating query syntax that is not appropriate for it to emit.
- **Uniformity.** Lucindri produces no atom counts; a coach that depended on them would
  not behave uniformly across engines.
- **Trackability.** "Which of these judged passages are informative, and what vocabulary
  distinguishes the relevant from the non-relevant" is a small, legible task with a
  testable output — far easier to evaluate and debug than a query-diagnosing coach.

**Deferred:** operator-level query diagnosis ("your proximity window is too tight"). The
atom-count path (below) still surfaces the most valuable query-failure hint — a dead or
ultra-rare term — and the Searcher owns query mechanics anyway. A future query-aware
"true coach" can be added behind the same protocol without disturbing v1.

## What the Searcher always sees (the feedback contract)

The Controller assembles the Searcher's feedback after the Judger finishes, for every
query. It is **one contract regardless of which coach is configured**:

1. **"You used this search."** The query, echoed back. (The Controller owns this — the
   coach is query-blind.)
2. **Quality stats.** How well it worked: the relevance distribution over the judged
   results, already-judged / retread counts, total matches, depth descended.
3. **Atom matches — only if the engine provides them.** Cottontail returns per-term
   corpus counts; Lucindri does not. Rule: *pass the counts through to the Searcher iff
   they exist.* They let a Cottontail Searcher diagnose a real failure (a term that
   matched nothing or is so common it is not selective). They flow **engine → Searcher
   directly, bypassing the coach.** (This gating already matches the current engine
   behavior: the Lucindri engine reports no atom counts, so they are simply omitted.)
4. **Coach summary + advice.** The coach's distilled output: the informative results it
   selected (their verbatim `summary` + `reason`) plus its observations and recommended
   words/phrases.

Because the shape is fixed, swapping coaches is a **config change only** — the Searcher
prompt does not fork. The mechanical coach fills item 4 with its rule-based selection and
no advice prose; the relevance-feedback coach fills it with a curated selection + advice.

## Interfaces

### `SearchCoach` protocol

```python
class SearchCoach(Protocol):
    def summarize(self, ctx: CoachContext) -> CoachResult: ...
```

`CoachContext` (built by the Controller; query-blind, atom-blind):

- `intent: str` — the information need.
- `stats` — relevance distribution, already-judged counts, total_matches, depth.
- `results` — the query's judged results in rank order, each `{ id, rank, score, grade,
  summary, reason }`. The Controller passes the full descent (it is in-memory only — no
  LLM cost until a coach chooses to send some of it). Each coach shapes its own view via
  the shared `select(descended, top_k, min_grade)` helper: the relevance-feedback coach's
  LLM input is `select(input_top_k, input_min_grade)` (top-N + high-grade nuggets — see
  scope), and the mechanical coach's output is `select(top_results_to_show,
  min_show_grade)`.

`CoachResult`:

- `selected: list[id]` — the informative results to forward. The Controller expands
  these to the docs' **verbatim** `summary` + `reason` (the coach never transcribes
  passages, so it cannot drift or hallucinate the vocabulary the Searcher mines).
- `report: str | None` — observations + recommended words/phrases. `None` for the
  mechanical coach.

### Controller assembly

1. Build `ctx` from the descent's judged results + stats.
2. Call the configured coach with a fallback:
   ```
   try:    result = self.coach.summarize(ctx)
   except Exception:   result = self.mechanical.summarize(ctx)   # emit a coach_fallback event
   ```
3. **Guaranteed floor:** always include the top 1–2 results by rank in the forwarded
   selection, then the coach's picks — so a bad coaching turn cannot starve the Searcher.
4. Expand `result.selected` → verbatim `summary` + `reason`.
5. Emit the Searcher feedback = `{ query (echo), stats, atom_counts (iff present),
   results (selected, verbatim), report }`.

## Implementations

### `MechanicalSearchCoach`

- Reproduces today's selection rule: the top `top_results_to_show` by rank regardless of
  grade, plus any deeper result graded `>= min_show_grade`. `report = None`.
- A pure function of `ctx` → **cannot fail** → the universal fallback.
- Config `[coach.mechanical]`: `top_results_to_show` (default 10), `min_show_grade`
  (default 3) — the same knobs as today, relocated here.

### `RelevanceFeedbackCoach`

- An LLM agent like Analyst / Searcher / Judger: `client` + `model` + prompt +
  `temperature = 0` + the TASK-37 generation caps (`max_tokens`, `timeout_s`).
- Prompt, in spirit: *"You are a relevance-feedback assistant. Given an information need
  and a set of already-judged passages (each with a relevance grade and the assessor's
  reason): (a) select the passages most informative for understanding what is relevant;
  (b) note briefly what distinguishes the relevant from the non-relevant material; (c)
  recommend concrete words/phrases drawn from the relevant passages that would sharpen
  the search. Be concise. Do not write queries or query syntax."*
- Returns structured output `{ selected, report }` via guided decoding.
- Query-blind, atom-blind, engine-agnostic.

## Configuration

Move `top_results_to_show` / `min_show_grade` out of `[loop]` and into
`[coach.mechanical]` (with a deprecated `[loop]` shim for one release so existing configs
keep working).

```toml
[coach]
class = "isj_agent.agents.search_coach.RelevanceFeedbackCoach"   # or MechanicalSearchCoach
llm   = "default"
# input_top_k = 25                # coach INPUT: top-N by rank fed to the coach ...
# input_min_grade = 3             # ... plus any deeper result graded >= this (high-grade nuggets)
# max_selected = 8                # cap on results the coach forwards to the Searcher
# reasoning_effort = "medium"     # TASK-37 caps + temperature 0, as with the other agents
# temperature = 0.0
# max_tokens = 8000
# timeout_s = 120

[coach.mechanical]                 # always-present fallback; used directly if class = Mechanical
top_results_to_show = 10
min_show_grade = 3
```

- `class = MechanicalSearchCoach` → mechanical only; no LLM; it *is* the fallback.
- `class = RelevanceFeedbackCoach` → LLM primary + mechanical fallback (always built from
  `[coach.mechanical]`).

## Observability

- The relevance-feedback coach's LLM call is a trace event with `purpose = "coach"`
  (viewable with `isj/scripts/traceview.py --purpose coach`).
- A `coach_fallback` trace event records when the mechanical path was used because the
  configured coach failed.
- So a trace shows how often coaching fails, what the coach selected, and what it advised.

## Resilience

Same philosophy as TASK-27 (a failed judge → grade -2, run continues) and TASK-37
(bounded generation): the intelligent path may fail; the run must not. The
relevance-feedback coach inherits the TASK-37 caps, so a runaway coach **times out into
the mechanical fallback** rather than hanging the wave.

## Rollout (task tree)

1. **Extract the protocol + mechanical coach** — a behavior-preserving refactor of the
   Controller's `_summarize` / `_select_feedback` into `SearchCoach` +
   `MechanicalSearchCoach`; migrate `[loop]` knobs → `[coach.mechanical]`. Verified
   against the current test suite with no behavior change.
2. **Add `RelevanceFeedbackCoach`** — the LLM coach + prompt + query-blind context +
   Controller fallback + `purpose="coach"` / `coach_fallback` trace events + config
   wiring.
3. **A/B on the dev topics** — coach-on vs coach-off over the 22 RAG25 dev topics:
   recall@k against the ClimbMix qrels, turns-per-intent, no_query rate, and whether the
   coach's recommended vocabulary actually appears in gold-relevant documents.

## Decided

- **Cadence: every search.** The coach runs after every query's judging. Judging
  dominates the per-query cost (waves of full-document LLM judgements), so one extra coach
  call is comfortably worth it; we do not gate it on the query underperforming.
- **Deep high-grade nuggets are included.** The coach input is the top `input_top_k` by
  rank *plus* any deeper result graded `>= input_min_grade` — never dropping a strong
  result just for being past the top-N (see scope).

## Open items / future

- **v2 "true coach"** — query-aware, able to attribute failures to query operators. Needs
  per-language knowledge; deliberately out of v1.
