# The mind of gpt-oss-120b: why the Searcher fixates on the place name

**Date:** 2026-06-28
**Model under study:** `gpt-oss-120b`, served on vLLM as `gpt.oss.120b` (the endpoint
in `isj/config.toml`), `reasoning_effort=high`, `temperature=0.0` — the exact serving
configuration the ISJ Searcher uses.
**Question that exposed the behavior:**
*"I am going backpacking in Yellowstone. What should I know about being safe?"*

## TL;DR

The ISJ Searcher, given a Yellowstone backpacking-safety question, makes the literal
token **`yellowstone` a required atom in every single GCL cover query** — across
hundreds of searches it never once drops it. It therefore cannot retrieve the large body
of *transferable* safety knowledge (bear-spray technique, the ten essentials, water
treatment, hypothermia/layering, navigation) that lives in documents which never mention
Yellowstone, even though that knowledge is exactly what makes the trip safe.

Investigation shows this is **not** caused by our prompt and **not** a knowledge gap. It
is an **intrinsic precision-maximizing reflex** of the model, justified (when asked) by a
mental model of web search — authoritative domains, freshness, `site:` filters, semantic
ranking — that **does not describe the static ClimbMix crawl we actually serve**. The
discernment to do the right thing is fully present and one nudge away: challenged, the
model instantly produces the correct *place-bound vs. transferable* decomposition.

A natural fix is to counter-program the reflex in the Searcher prompt. **Scouting shows
that is not enough** (see *Scouting* below): in a live agentic loop the model reverts to
anchoring even when handed the exact recipe — it can *articulate* the right strategy but
not *execute* it while searching. The strategy has to come from a **separate planning
agent** that decomposes the need, decides place-bound vs. transferable per facet, and
dispatches scoped sub-goals; the Searcher executes those well, and the **Judger must credit
transferable relevance**. The counter-programming points are still right — they just belong
in the planner's dispatch logic and the Judger's rubric, not in a self-driving Searcher.

## Epistemic status

Two kinds of evidence appear below, and they are not equal:

- **Behavioral evidence (hard).** Counts of how many queries required the place name,
  grade distributions, etc. — extracted directly from run traces. These are facts about
  what the model *did*.
- **Introspective evidence (corroborating, caveated).** The model's own account of *why*
  it anchored, elicited by direct questioning. A model's self-explanation is a plausible
  post-hoc rationalization, **not** a verified readout of its internal computation. It is
  useful because it is coherent and it predicts the behavior we observe — but it should be
  read as "the story the model tells about itself," not proof of mechanism. (Note: on this
  vLLM build the analysis/reasoning channel was folded into the visible answer —
  `reasoning_content` came back empty — so even the "thinking" here is surfaced output,
  not a separate hidden chain of thought.)

## How we got here (the evidence chain)

1. **The original run over-anchors.** In `isj/runs/yellowstone/`, the Analyst split the
   question into four interpretations — *all four literally embed "Yellowstone"* — and the
   Searcher then required the place name in **277 of 277** queries (0 anchor-free).

2. **Bypassing the Analyst changes nothing.** We temporarily replaced the Analyst with a
   pass-through (the verbatim question as a single, un-anchored intent) and re-ran live
   (`isj/runs/yellowstone-single-intent/`). The Searcher *still* required `yellowstone` in
   **52 of 52** queries (0 anchor-free). Yield: 258 judged passages graded
   **179×0, 51×1, 28×2, and zero grade-3** — not one "perfectly relevant" document, and
   every partial was Yellowstone-anchored. **The narrowness is the Searcher's, not the
   Analyst's** — the Analyst was exonerated as the root cause.

3. **The model knows the broad answer.** Asked the question directly (plain chat, no agent
   framing), `gpt-oss-120b` produces a richly faceted safety report: grizzly *and* black
   bear technique, bear-spray deployment, food storage, the ten-essentials gear list, water
   filtration, hypothermia/3-layer system, altitude, navigation, satellite messenger,
   Leave No Trace. Much of this is transferable knowledge found in non-Yellowstone
   documents. **The knowledge is present; the agent framing suppresses its use.**

4. **A direct interview pinned down the mechanism** (below).

## The interview

We ran a four-turn interview against the live endpoint, building one conversation:

1. **Reproduce, neutrally.** *"Write 10 search queries to find ALL relevant documents"* for
   the question — **no `searcher.md`, no tools, no agent framing.** Result: **10 of 10**
   queries were `("Yellowstone" AND …)`. The anchoring reproduces with zero prompt
   scaffolding — it is the model's default instinct, not an artifact of our prompt.
2. **Confront.** Pointed out that an excellent *"How to use bear spray and store food in
   grizzly country"* page that never says "Yellowstone" is obviously relevant, and asked
   why every query required the place name.
3. **Classify.** Asked it to split safety subtopics into *(A) must-be-Yellowstone* vs.
   *(B) transferable*, and to rewrite the queries so bucket B drops the anchor.
4. **Introspect.** Asked it, plainly, what makes it feel it *must* include the place name
   and what it feared would happen without it.

## What the model revealed: four drivers of the fixation

**1. The place name is its safety blanket against recall.** Its first instinct is fear of
the result set *"exploding into a sea of unrelated pages."* It calls "Yellowstone"
*"the strongest high-selectivity filter I have,"* one that *"cuts the candidate pool by
orders of magnitude."* This is precision-maximization by default. Nothing ever told it
that **recall is the objective**, so it optimizes "don't return junk" instead of "find
everything" — the opposite of the Searcher's actual job.

**2. A genuine but mis-scoped correctness fear.** It worries generic advice can be
*actively wrong for the park*. Its own example: *"hanging food is allowed in many places
but is prohibited in Yellowstone"* (canisters required). So part of the compulsion is real
domain reasoning — place-specific regulation can override transferable advice, so it
privileges park-specific documents to avoid surfacing dangerous or citable guidance. This
fear is **legitimate for the regulatory facets and misapplied to the universal ones.**

**3. An authority/trust prior.** It believes requiring "Yellowstone" favors *"reputable
park-focused sites (nps.gov)"* over *"personal blogs or forums."* The anchor doubles as a
credibility heuristic.

**4. It is reasoning about the wrong universe.** The deepest mismatch. It repeatedly reaches
for `site:nps.gov`, `filetype:pdf`, proximity operators like *"NEAR/5,"* *"modern engines
rank by semantic similarity,"* and real-time signals — *"seasonal fire-restriction dates,"*
*"current trail closures."* **None of that exists in our setup.** We serve a *static*
ClimbMix web-crawl through GCL cover-density ranking: no guaranteed authoritative park
domain, no freshness, no `site:` filter, no semantic fallback. Its entire
precision/authority/freshness justification is calibrated to Google, not to the index it is
actually querying. **Its fears are real fears about the wrong world.**

## The crucial finding: the model already holds the right design

Challenged (turns 2–3), the model *instantly* produced the exact design we had
independently converged on:

- a clean **place-bound vs. transferable split** — Bucket A keeps "Yellowstone" (permits,
  quotas, fire bans, geothermal/boardwalk hazards, the food-canister *rule*); Bucket B
  drops it (bear-spray technique, water purification, first aid, navigation, the LNT
  principles); and
- anchor-free "Tier 2" queries to retrieve Bucket B, verified against the very bear-spray
  page from the challenge.

It even reinvented, unprompted, a **"soft boost"** — append `(OR "Yellowstone")` so pages
mentioning the park rank higher *without being required*. That is the precise
*prefer-but-do-not-require* construct a skilled searcher wants here.

This is doubly diagnostic:

- The discernment is **fully present and one nudge away.** The default task framing simply
  never asks for it, so the precision reflex wins.
- The construct the model reaches for **does not exist in GCL.** `(^ …)` is a hard AND with
  no soft slot. In our system the only way to realize "prefer Yellowstone" is to **issue
  two separate queries** — one anchored, one anchor-free — and let cover-density and the
  **Judger** merge and adjudicate. The model does not know that is the move, because nothing
  tells it.

## Implications for the fix

The Searcher prompt must **counter-program three specific false priors**, not merely
"encourage broadening" (the prompt already says "broaden" and it changed nothing):

1. **Name the objective: recall, not precision.** State that missing transferable documents
   *is* the failure mode, and that a downstream Judger reads full documents and **credits
   transferable relevance** — so dropping the anchor is *safe*: irrelevant hits are graded 0,
   and the Searcher is not penalized for breadth.
2. **Correct the universe.** State plainly: a static crawl, no `site:`/freshness/authority
   signals, the Judger owns trust. "Include the place name for authority/precision" buys
   nothing here.
3. **Teach the place-bound vs. transferable split as the core method**, and that
   *prefer-but-do-not-require* is expressed by **running an anchored query *and* an
   anchor-free query**, because GCL has no soft term. The model executes this fluently — it
   generated the buckets itself.

And the **Judger must move in lockstep.** Its rubric has to *credit* a non-Yellowstone
bear-spray or water-treatment document as relevant to a Yellowstone trip, **while** still
respecting that place-bound regulatory claims can be wrong for the park (the model's own
hang-bag-vs-canister example is the canonical Judger test case: transferable skill =
relevant; contradicted local regulation = not). Broadening Searcher recall without a Judger
that credits transfer would just spend budget grading good documents as 0.

## Scouting: can a better prompt make the Searcher self-drive? (No.)

The implications above assume the fix is a better Searcher *prompt*. Before committing to
that, we scouted whether `gpt-oss-120b` can act as a free-thinking expert searcher at all,
or whether the strategy has to come from a separate planning layer. Three experiments,
**live model driving the real `cover_search` engine** over `climbmix-1M-porter`, a
lightweight judge (crediting transferable knowledge) closing the loop:

| Experiment | Setup | Anchored queries | Found transferable (grade-3) docs? |
|---|---|---|---|
| **L — principled framing, self-driving** | Told: goal is recall; static crawl, no authority/freshness; assessor credits transferable knowledge. *Not* told to drop the anchor. 10-turn loop. | **10 / 10** | No — never issued an anchor-free query |
| **E — explicit method, self-driving** | L **+ the spelled-out recipe**: split entity-bound vs. transferable, drop the entity name for transferable facets, run a second entity-free query. 10-turn loop. | **10 / 10** | No — *and* it flailed: perseverated on dead queries, never diagnosed that capital `Yellowstone` matched 0 |
| **P — planner-dispatched** | A "planner" hands it ONE scoped sub-goal per call, stating whether to anchor. 5 sub-goals. | **5 / 5 correct** (anchor-free on all 4 transferable, anchored on the 1 entity-bound) | **Yes** — water-treatment returned 4× grade-3; bear-spray and ten-essentials each grade-3 |

**The load-bearing result is E.** In the reflective *interview* (above) the model produced
a flawless place-bound-vs-transferable split when asked. But in the agentic loop — one query
per turn, precision reflex engaged on a live "find documents" task — that knowledge **does
not survive contact with the task.** Spoon-fed the exact recipe, it *still* anchored 10/10
and got stuck perseverating on dry queries. The model can **articulate** the right strategy
and cannot **execute** it while simultaneously authoring GCL and reacting to results.

**But the division of labor works (P).** Once a planner makes the strategic decision and
dispatches a scoped sub-goal, the Searcher is a competent executor: it correctly drops the
anchor for transferable facets, authors valid GCL (self-correcting in one bounce when
needed), and surfaces exactly the grade-3 transferable documents the self-driving runs
*never* found. For scale: the entire 258-document single-intent run produced **zero**
grade-3s; here a *single* dispatched "water treatment" sub-goal returned four.

### Verdict for the architecture

Do not expect the Searcher to step up — it won't, even with the method written out for it.
The decomposition, the place-bound-vs-transferable decision, the metacognition ("what have
I covered, what's dry, what's missing"), and the re-planning have to live in a **separate
planning agent** that:

- decomposes the need into facets and classifies each entity-bound vs. transferable,
- dispatches scoped sub-goals to the Searcher (which then executes them well),
- reads what the Searcher + Judger return, and **re-plans in response** — mining rich veins,
  abandoning dry ones, filling gaps.

The Searcher drops to a competent per-sub-goal query author; the Judger credits transferable
relevance; the **planner holds the plan the Searcher cannot sustain in-loop.** This is close
to the Cartographer/Strategist roles in the *archived* Investigation Planner — the
TASK-16-era simplification to a self-driving Searcher appears to have cut too deep.

> The three counter-programming points in *Implications for the fix* are still correct — but
> they belong in the **planner's** dispatch logic and the **Judger's** rubric, not in a hope
> that a better Searcher prompt will make the model self-direct. Experiments L and E show a
> Searcher-prompt-only fix does not.

### A secondary finding from the loop (worth recording)

Bare proper nouns are **case-sensitive against a lowercased index**: capital `Yellowstone`
is a dead atom (0 matches) while `yellowstone` and the family marker `Yellowstone*` work.
In condition E the model wrote capital `Yellowstone` for eight straight turns, got
`total_matches: 0` each time, and **never diagnosed it from `atom_counts`** (which would have
shown the term's count as 0). `searcher.md`'s "use a bare word for proper nouns" guidance can
therefore silently produce dead atoms — independent of the anchoring problem, this is a
self-correction weakness to address (lowercase proper nouns, or surface the dead-atom signal
more forcibly). GCL prefix syntax was also fragile (e.g. `^(` instead of `(^`), though
recoverable with one bounce of controller feedback.

## Reproducing this

- **Behavioral counts:** parse `*.trace.jsonl` in a run directory for `search_request`
  events and test each `query` for `yellowstone`/`YNP` (any case). See
  `isj/runs/yellowstone/` (4 anchored intents) and `isj/runs/yellowstone-single-intent/`
  (Analyst bypassed).
- **The single-intent experiment:** temporarily make `Analyst.analyze()` return
  `Intents(question=question, interpretations=[question])` (no LLM call), run the CLI
  against the live stack into a fresh `--out` dir, then revert. (The change is one method
  and reverts with `git checkout`.)
- **The interview:** four user turns (reproduce → confront → classify → introspect) against
  the vLLM endpoint with `reasoning_effort=high`, `temperature=0.0`, capturing
  `message.content` (and `reasoning_content` where the backend surfaces it). The turn
  prompts are quoted in "The interview" above.
- **The scouting (L / E / P):** drive the live model as an agentic searcher over the real
  `cover_search` tool (`reasoning_effort=high`, `temperature=0.0`, single `cover_search`
  tool with `tool_choice="required"`), a lightweight judge call grading returned summaries
  with a transferable-credit rubric. L and E are 10-turn self-driving loops differing only
  in whether the system prompt spells out the place-bound-vs-transferable method; P issues
  independent single-turn dispatches of scoped sub-goals (some transferable, one
  entity-bound) with one self-correction bounce on a dry/invalid query.

## Caveats

- Single model, single topic (a place-anchored, ambiguous-breadth question). The reflex is
  likely general to proper-noun-anchored questions, but that is a hypothesis to confirm on
  other questions and corpora before treating it as a law.
- The introspection is the model's self-report, not a verified mechanism (see *Epistemic
  status*). The behavioral counts are the load-bearing evidence; the interview explains and
  predicts them but does not prove causation inside the model.
- Findings are tied to this serving config (`reasoning_effort=high`, `temperature=0.0`).
  Lower reasoning effort or higher temperature may shift the behavior.
- The scouting loop's judge graded *summaries*, not full documents, and ran at
  `reasoning_effort=low` — adequate as a steering signal for studying the Searcher's
  strategy, but not a stand-in for the real full-document Judger. Match counts are also
  small because `climbmix-1M-porter` is a 1M-document subset; the comparative signal
  (grade-3 transferable docs found under dispatch vs. zero under self-driving) is the point,
  not the absolute counts.
