# SearchCoach — a pluggable coaching layer for the Searcher

Status: design. The design below is settled by the prompt-scouting in
`isj/scouting/search-coach/` (see that directory's `captured/FINDINGS.md`); the **v6**
free-text coaching prompt (`prompt-v6.md`) is the chosen shape. Not yet ported into the
live Controller.

## Problem

Each turn, the Searcher does two cognitively different jobs: it **diagnoses** what its
last query did (reading a pile of judged results + stats) and it **authors** the next
query. That is a lot to hold at once, and it competes for the Searcher's bounded context.

Today the Controller feeds the Searcher back a **mechanically-sliced** view of the judged
results (TASK-36: the top `top_results_to_show` by rank plus any deeper result graded
`>= min_show_grade`). That keeps context bounded, but it is a dumb fixed rule and it still
leaves the Searcher to do the "what is relevant here / what should I try next" thinking
over raw material.

Move that "digest the judged pile into high-value guidance" work off the Searcher onto a
dedicated, ephemeral **coach** — and make the layer **pluggable**, so today's mechanical
behavior is one (low-intelligence) implementation and a smarter LLM coach drops in behind
the same interface.

## Overview

`SearchCoach` is an abstraction that, given one query's judged results + stats, produces
the feedback the Searcher sees after the Judger stops judging. The Controller places that
feedback into the tool message it sends back to the Searcher.

Two implementations behind one protocol:

- **`LlmSearchCoach`** — an LLM that studies the information need and the judged results
  and writes a **free-text coaching report** (the v6 shape below). Query-blind and
  engine-agnostic.
- **`MechanicalSearchCoach`** — a deterministic, no-LLM listing of the top-N + high-grade
  passages (the current TASK-36 content, as text). Pure code over data the Controller
  already has; **cannot fail**; it is the always-works fallback.

The Controller is configured with one coach. **If the configured coach fails (error /
timeout / empty output), the Controller falls back to the mechanical coach** — so the
intelligent path can fail without failing the run.

Cadence: the coach runs **after every query's judging**. Judging dominates the per-query
cost (waves of full-document LLM judgements), so one extra coach call is comfortably worth
it; it is not gated on the query underperforming.

## Scope: a coaching / relevance-feedback agent, query-blind and engine-agnostic

The LLM coach studies the judged results and coaches; it does **not** understand or write
queries.

**The coach is given:**

- the **information need** (the interpretation being searched);
- **computed stats** about the judged results (relevance distribution, already-judged /
  retread counts, total matches, descent depth);
- a **selection of the judged results** — the **top `input_top_k` (default 25) by rank,
  plus any deeper result graded `>= input_min_grade`** — each with its `summary` (the
  passage excerpt), the assessor's `reason`, and `grade`. Every one carries a grade (the
  top ranks are judged this query or cached from a prior query; the deep ones are pulled
  in because they graded high). This is, by construction, **today's mechanical search
  summary** (top-N-by-rank + high-grade nuggets), built by the shared
  `select(descended, top_k, min_grade)` helper — we feed the coach today's summary and ask
  it to write a better one.

**The coach is NOT given:**

- the Searcher's **query** or any query **machinery** (GCL, the MultiText DSL, Lucindri
  syntax);
- the Searcher's **prompt / instructions**;
- the **atom-match counts**.

**Why this boundary:**

- **Engine-agnostic.** Knowing no query language, the *same* coach serves every searcher —
  Cottontail cover / tiered / multitext, and Lucindri — with no per-language knowledge and
  no duplicated query-language reference in the coach prompt.
- **No syntax leakage.** Withholding the query and the atom terms keeps the coach from
  imitating query syntax it should not emit. (Scouting still occasionally saw it slip in a
  `NOT "..."`; withholding the query minimises the temptation.)
- **Uniformity.** Lucindri produces no atom counts; a coach that depended on them would not
  behave uniformly across engines.
- **Trackability.** Coaching from need + results is a small, legible task with a testable
  output — far easier to evaluate than a query-diagnosing coach.

**Deferred — a query-aware "true coach"** that could attribute failures to query operators
("your proximity window is too tight"). It needs per-language knowledge and is out of
scope; it can be added behind the same protocol later. The atom-count path (below) still
surfaces the most valuable query-failure hint — a dead or ultra-rare term — and the
Searcher owns query mechanics anyway.

## The coach output — a free-text coaching report (v6)

The LLM coach emits **plain-markdown free text**, not a guided-JSON object. Scouting v2
tried guided-JSON structured output and it failed badly on gpt-oss-120b/vLLM: guided
decoding forced the `selected` field to be emitted *before* the analysis (inverting the
task), a separate `recommended_terms` field siphoned off the "how to improve" content, and
long prose inside a JSON string degraded into whitespace loops (2/7 parse failures).
Free text (v3–v6) parses cleanly, gives more reasoning room, and produces genuinely better
coaching. So: **no `response_format`; the report is prose.**

The **v6** report (see `isj/scouting/search-coach/prompt-v6.md`) has four sections:

- **What is working** — which results are surfacing relevant material and what the relevant
  passages share (topics, angle, framing, vocabulary), citing the best illustrations by
  handle `[R3]`.
- **What is hurting** — what is dragging in non-relevant/marginal material (wrong sense,
  off-topic angle, shallow sources, a missing facet), including explicitly naming any facet
  of the need with **no** relevant coverage (the most valuable thing a searcher can learn).
- **What to pursue next** — concrete directions + a `Vocabulary worth pursuing:` line of
  8–15 concrete words/phrases drawn from the relevant passages. No query syntax.
- **Cited passages** — for each cited passage, its handle + grade + the **excerpt copied
  VERBATIM** from the input `summary:` + the assessor's reason.

The first three sections are the coaching (~200–400 words). The **Cited passages** section
makes the report **self-contained**: the Searcher sees the actual passages the coach refers
to, so **the Controller does not expand handles into passages** — the coach already did.
This is the key change from the earlier design (which had the coach return bare handles for
the Controller to expand). Scouting measured the reproduction as faithful: **39/40
verbatim on cover, 73/78 (94%) on multitext** (misses are 2-word title summaries).

## What the Searcher sees each turn (the feedback contract)

The Controller composes the tool message it sends back from four parts:

1. **"You used this search"** — the query, echoed back. (Controller-owned; the coach is
   query-blind.)
2. **Quality stats** — relevance distribution over the judged results, already-judged /
   retread counts, total matches, depth descended.
3. **Atom matches — only if the engine provides them.** Cottontail returns per-term corpus
   counts; Lucindri does not. Rule: *pass the counts through iff they exist.* They let a
   Cottontail Searcher diagnose a real failure (a term matching nothing, or so common it is
   not selective). They flow **engine → Searcher directly, bypassing the coach** (this
   gating already matches the current engine behavior — the Lucindri engine reports none).
4. **The coach report** — the self-contained v6 report (coaching + Cited passages).

Swapping coaches is a config change. The **mechanical fallback** replaces item 4 with a
plain deterministic listing of the top-N + high-grade passages (handle, grade, reason,
verbatim excerpt) — no coaching prose. The Searcher prompt is written once and tolerant of
both: "you receive a coaching report; if coaching is unavailable you receive a plain list
of the top graded passages."

## Delivery, and why the Controller owns the seam

The Controller keeps a single in-memory chat-messages list (`msgs`) per intent (see
`controller.py`): seeded with `[system, user(intent)]`, then each turn it appends the
Searcher's `assistant` message (the query/tool-call) and its own reply as a
`{"role": "tool", "tool_call_id": ..., "content": ...}` message via the `_tool` helper.
`searcher.propose(msgs)` re-sends the whole list each turn, so **`msgs` is the accumulating
context**.

Because the Controller builds the `content` of that tool message, it is the single seam for
both size controls below — it decides exactly what the Searcher sees, so caps and
compaction are just "what we hand to `_tool`," never after-the-fact edits.

## Bounding one report — the reproduction cap

A report's size is `fixed coaching prose (~650 tok) + Σ reproduced excerpts`. The excerpts
are ~2/3 of the tokens and are the only variable that blows up: on dense-relevant or
many-marginal result sets the coach over-cites (scouting: multitext q10 reproduced 19
passages → ~5.4k tokens for one turn). Bound it with two layers:

- **Prompt cap on reproductions** (soft): reproduce the excerpts for at most ~N most
  valuable cited passages (cite handles freely in prose — a handle is cheap — but cap the
  reproduced excerpts). Adherence must be *measured*: caps are not guaranteed (the model
  has ignored per-section caps before).
- **Controller post-trim** (hard backstop): the `## Cited passages` section is structured
  (one block per passage), so the Controller can keep the top-N blocks by grade and drop
  the rest before sending. Extraction of handles/blocks must be **tolerant** (see below).

`max_reproduced` (a.k.a. `max_selected`) is a config knob. Typical target ~6–8; measure
first.

## Bounding the conversation — context compaction (shrink-in-place)

The reproduction cap bounds a *single* report; compaction bounds the *cumulative* `msgs`.
Because the Controller owns `msgs`, it compacts **in place** before a `propose` when the
conversation grows large. We shrink **only tool messages** (the assistant messages are just
queries — tiny; and the tool-calling protocol forbids orphaning a tool message from its
`assistant` tool-call, so shrinking-content-in-place is the protocol-safe move — we never
delete a message).

**Trigger.** Use the **server-reported `prompt_tokens`** from the last `propose`
(`pr.usage.prompt_tokens`) as the size signal — exact and free, no local tokenizer. When
it reaches **80% of the model limit** (0.8 × 131072 ≈ 105k), run a shrink pass before the
next turn.

**Shrink pass.** Shrink the **oldest 50% of the currently-un-shrunk tool messages**. Each
subsequent trigger halves the oldest half of what is *still* full (K → K/2 → K/4 …).
Already-shrunk messages are left alone. **Invariant: the most recent tool message is never
shrunk** (that is what the Searcher reformulates from).

**How to shrink a message.** Drop the `## Cited passages` section (keep the coaching prose +
the `Vocabulary worth pursuing:` line — the durable advice; the excerpts' immediate
vocabulary-mining value is spent once the Searcher has moved on). **If that section is not
found** (regex miss, or a mechanical-fallback listing that has no such section),
**hard-truncate** the content to a configured size (default ~800 tokens ≈ the coaching-prose
length).

**Effect.** A full v6 report ≈ ~2,000 tok; shrunk ≈ ~650 tok (a ~70% cut). Keeping the last
few full and shrinking the rest raises the per-intent ceiling from ~60 queries to ~170+
(`~10k + (N−5)·650 < ~120k`). Combined with the reproduction cap, the Searcher effectively
never hits the context wall in a realistic run.

**Degenerate floor.** If everything is shrunk to just the untouchable last message and we
are *still* ≥ 80%, either second-pass hard-truncate the already-shrunk messages or proceed
(we are still 20% under the hard limit). This cannot happen inside a normal `max_queries`
run (you would need ~160 shrunk reports + one full to approach the trigger); it is a
defensive line, not a hot path.

Compaction is a deliberate behavior change (it alters exactly what the LLM sees), so it is
a knob to test in the scout/harness like temperature or the caps. It churns the prompt
cache for the compacted prefix — accepted (we compact in occasional larger steps, not a
trim every turn).

## Selection & logging (tolerant citation extraction)

With v6 self-contained, extracting the coach's cited handles is **not** needed to build the
feedback (the passages are already in the report). It is used only to **log which docs the
coach referenced** (run-output / analysis) and to drive the Controller post-trim. The model
is inconsistent about bracketing (it drifts from `[R7]` to bare/bold `**R7**`), so
extraction must match `R\d+` **bracketed OR bare**, validated against the input handle set
(so stray tokens drop out). A report with *no* parseable citations is **not** a failure —
it is self-contained; forward it as-is and log zero references. (This retires the old
"guaranteed floor of top-1–2 by rank": scouting showed the coach reliably keeps top-grade
material, and a rank floor would wrongly displace deep grade-3 nuggets the coach correctly
reaches for; the self-contained report needs no rank floor.)

## Interfaces

```python
class SearchCoach(Protocol):
    def coach(self, ctx: CoachContext) -> CoachOutput: ...
```

- `CoachContext` (query-blind, atom-blind): `intent`; `stats`; `results` — the query's
  judged descent in rank order (`{docno, rank, score, grade, summary, reason}`). The
  Controller holds the full descent in memory; each coach shapes its own view via the
  shared `select(descended, top_k, min_grade)` helper (the LLM coach's *input* uses
  `select(input_top_k, input_min_grade)`; the mechanical coach's *output* uses
  `select(top_results_to_show, min_show_grade)`).
- `CoachOutput`: `report: str` (the text the Controller puts in the tool message —
  coaching report or mechanical listing) and `referenced: list[docno]` (the cited docs,
  tolerant-extracted; for logging + post-trim; may be empty).

Controller flow, per query, after the descent:

```
ctx = build_context(descended, stats)
try:    out = self.coach.coach(ctx)
except Exception:   out = self.mechanical.coach(ctx)   # emit a coach_fallback event
out = self.cap_reproductions(out)                      # Controller post-trim to max_reproduced
content = compose(query_echo, stats, atom_counts_if_present, out.report)
self._tool(msgs, tool_call_id, content)
maybe_compact(msgs)                                    # shrink-in-place at 80%
```

## Implementations

### `LlmSearchCoach`

An LLM agent like Analyst / Searcher / Judger: `client` + `model` + prompt file +
`temperature = 0` + the TASK-37 generation caps (`max_tokens`, `timeout_s`). Prompt = the
v6 report format above (query-blind, atom-blind). No `response_format` — free-text markdown.

### `MechanicalSearchCoach`

Deterministic, no LLM: emits the top `top_results_to_show` by rank + any deeper result
graded `>= min_show_grade` as a plain passage listing (handle, grade, reason, verbatim
excerpt). A pure function of `ctx` → **cannot fail** → the universal fallback. It is also
the standalone coach if `class = MechanicalSearchCoach` (approximates today's TASK-36
feedback in text form).

## Configuration

`top_results_to_show` / `min_show_grade` move out of `[loop]` into `[coach.mechanical]`
(with a deprecated `[loop]` shim for one release).

```toml
[coach]
class = "isj_agent.agents.search_coach.LlmSearchCoach"   # or MechanicalSearchCoach
llm   = "default"
# input_top_k = 25           # coach INPUT: top-N by rank ...
# input_min_grade = 3        # ... plus any deeper result graded >= this
# max_reproduced = 8         # cap on excerpts reproduced in the report (Controller post-trim + prompt)
# reasoning_effort = "medium"
# temperature = 0.0          # TASK-37 caps + temp 0, as with the other agents
# max_tokens = 8000
# timeout_s = 120

[coach.mechanical]           # always-present fallback; used directly if class = Mechanical
top_results_to_show = 10
min_show_grade = 3

[loop]
# context compaction (shrink-in-place)
# compact_trigger = 0.80     # fraction of the model context limit that triggers a shrink pass
# shrink_truncate_tokens = 800   # hard-truncate size when a report has no ## Cited passages section
```

- `class = MechanicalSearchCoach` → mechanical only; no LLM; it *is* the fallback.
- `class = LlmSearchCoach` → LLM primary + mechanical fallback (always built from
  `[coach.mechanical]`).

## Observability

- The LLM coach's call is a trace event with `purpose = "coach"` (viewable via
  `isj/scripts/traceview.py --purpose coach`).
- `coach_fallback` records when the mechanical path was used because the coach failed.
- `compact` records a shrink pass (how many tool messages shrunk, size before/after).

## Resilience

Same philosophy as TASK-27 (a failed judge → grade -2, run continues) and TASK-37 (bounded
generation): the intelligent path may fail; the run must not. The coach inherits the
TASK-37 caps, so a runaway coach **times out into the mechanical fallback** rather than
hanging the wave.

## Token budget (from v6 scouting)

Per-turn Searcher-context growth ≈ the coach report (~2,000 tok mean/median across cover +
multitext) + a small assistant query message (~150 tok). Initial context (Searcher system
prompt + intent) ≈ ~3,600 tok. So **~60 queries per intent before the 131k limit** without
compaction — comparable to today's mechanical feedback (~2–5k tok/turn), i.e. the coach
does not blow the budget. The reproduction cap keeps the mean near ~2,000 (bounding the
over-citation tail); compaction lifts the ceiling to ~170+.

## Scouting evidence

`isj/scouting/search-coach/` — versioned (prompt, schema) pairs, per-prompt results dirs,
full transcripts (input + reasoning + raw output). Headlines (`captured/FINDINGS.md`):
guided-JSON (v2) fails; free-text (v3–v6) is 7/7 clean; **v6** adds verbatim self-contained
excerpts (39/40 cover, 73/78 multitext), reliable and faithful across cover (topics 14, 31)
and multitext. Open concern measured: no reproduction cap → reports balloon on
dense/many-marginal sets (→ the cap above).

## Rollout (task tree)

1. **Extract `SearchCoach` protocol + `MechanicalSearchCoach`** — pull the Controller's
   feedback assembly (`_summarize` / `_select_feedback`) behind the protocol as the
   deterministic text-listing fallback; migrate `[loop]` knobs → `[coach.mechanical]`.
   (Behavior changes from a JSON dict to a text listing, so verify the Searcher still reads
   it; not a pure no-op.)
2. **Add `LlmSearchCoach`** — v6 prompt, query-blind/atom-blind context, free-text report,
   tolerant citation extraction, reproduction cap, Controller fallback, `purpose="coach"` /
   `coach_fallback` traces, config wiring.
3. **Add context compaction** — the shrink-in-place pass (80% trigger via `prompt_tokens`,
   halve oldest un-shrunk, keep last intact, drop `## Cited passages` / hard-truncate
   fallback), `compact` trace, config knobs.
4. **A/B on the dev topics** — coach-on vs coach-off over the 22 RAG25 dev topics: recall@k
   against the ClimbMix qrels, turns-per-intent, no_query rate, and whether the coach's
   recommended vocabulary appears in gold-relevant documents.

## Open items

- **Reproduction cap value** — measure ~6 vs ~8 vs prompt-only vs prompt+post-trim.
- **Compaction A/B** — does shrinking old reports measurably hurt reformulation? Tune the
  recency window and trigger.
- **Query-aware "true coach"** (deferred) — attribute failures to query operators; needs
  per-language knowledge.
