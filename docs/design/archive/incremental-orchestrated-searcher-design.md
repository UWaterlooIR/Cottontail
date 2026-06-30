# Incremental design: from per-intent Searcher to an orchestrated searcher

**Status:** draft for review (2026-06-28). No code committed; no backlog tasks opened yet.
The first-release choice (R1 vs R2A) is an **open decision** — see §9.

This document proposes a **multi-release** path for evolving the ISJ search pipeline. Its
governing constraint is *incrementality*: add the next minimal component, measure it against
a fixed baseline, then decide the next step. It deliberately does **not** specify a complete
solution — a prior attempt to design the whole agent at once
(`agentic-isj-investigation-planner.md`) proved too large to execute. Where a design genuinely
forks, the forks are **named and advanced separately** rather than merged.

## Source basis

Grounded in five documents now on this branch:

- **`the-mind-of-gpt-oss-120b.md`** — the problem: the Searcher anchors ~100% of queries on the
  question's proper noun, can't self-supply strategy in-loop, and (Qwen) perseverates; *but*
  planner-dispatched scoped sub-goals work.
- **`pickens-sigir-2008.md`** — algorithmic mediation: Prospector/Miner roles, computable
  **freshness** $w_f=\text{unseen}/\text{seen}$ and **relevance** $w_r=\text{rel}/\text{nonrel}$
  weights, $w_r w_f$-weighted Borda fusion, and a term-suggestion feed.
- **`discovery-search-by-claude.md`** *(a.k.a. discovery-search)* — recall-vs-discovery as
  separate budgets; **goal-phrased queries with no names**; the **saturation** stopping rule;
  falsifiable "definition of done."
- **`search-tactics-playbook-by-claude.md`** — the move repertoire (facets, OR-within/AND-across,
  pearl-growing, symptom→move reformulation, diminishing-returns stop).
- **`deep-research-agent-design-by-claude.md`** — DR architecture: plan→iterative
  search/read/reflect→synthesize→cite; **single-agent (end-to-end RL) vs. multi-agent
  (orchestrator-worker)**; read-vs-write; cap effort in the orchestration layer, not the prompt.

## 1. Where we are (R0, the baseline)

**Architecture.** Analyst (tool-less, one-shot) → ordered intents. Per intent, a Controller runs
the Searcher (one GCL query/turn, no judging) and the Judger (parallel full-doc 0–3,
transferable-aware rubric). The Controller owns paging, dedup, the grade-0 streak, budget,
`max_queries`, and the heavy trace.

**Measured failures** (`isj/runs/yellowstone*`):

| Failure | Evidence |
|---|---|
| **Anchoring** — proper noun required in ~100% of queries | gpt-oss **277/277**, Qwen **251/251** anchor-free = 0; ≤1 grade-3 found |
| **Perseveration** — re-proposes identical queries | Qwen: one query 50×; **142** redundant re-proposes; stop logic misses pure repetition |
| **Can't self-supply strategy in-loop** | scouting cond. E: handed the exact recipe, still anchored 10/10 |

**Validated positive.** Planner-*dispatched* scoped sub-goals work (scouting P): the model drops
the anchor and finds grade-3 transferable docs (5/5 anchoring decisions correct).

**Eval harness already exists.** Trace-parsing yields, per run: `anchor_free%`,
`distinct_queries`, `redundant_reproposes`, `judged`, grade distribution (esp. **grade-3 count**),
and `stop reason`. R0 baselines are captured. Every release re-runs the same question(s) and diffs
these.

## 2. Design principles

1. **One minimal component per release, then measure** against R0 before the next.
2. **Fork only where the design genuinely diverges**; advance forks independently.
3. **Controller/planner owns control flow; the LLM executes** (cap effort in orchestration, not the
   prompt — DR §6).
4. **Read-heavy ⇒ parallel-safe** (DR §4.4); defer the single write phase (synthesis) to its own
   late track.
5. **Each release states a falsifiable hypothesis and a decision gate** (discovery-search
   "definition of done").

## 3. Eval discipline

Keep **Yellowstone as the anchor case**, but add **2–3 more probe questions** before the first
release (one place-anchored, one person/entity-anchored, one genuinely single-sense) so the fix
isn't overfit to one topic.

---

## 4. Release 1 — Controller saturation + freshness guard *(shared; no fork; no new agent)*

The smallest possible step. It fixes a measured bug and builds the signal **both forks need**, so
it is no-regret regardless of where we go next.

- **Hypothesis.** Killing perseveration/retreads reclaims wasted budget and is a precondition for
  any planner (a planner driving a perseverating Searcher is worse). *Basis:* Pickens $w_f$;
  discovery-search & tactics saturation rule; the-mind perseveration finding.
- **Minimal change (controller only).**
  (a) **Repeat guard** — if a proposed query equals a recent one (normalized), bounce it back as a
  tool error ("already issued; change facet/register").
  (b) **Saturation/freshness** — compute per-query $w_f$ from new-vs-seen; when two consecutive
  *distinct* queries return only already-seen docs, end the intent ("saturated") rather than
  grinding to `max_queries`.
  (c) **Record $w_f,w_r$ per query in the trace** (raw material for later forks).
- **Test & metric.** Re-run Yellowstone (both models) + new probes. *Expect:* `redundant_reproposes`
  → ~0 (Qwen from 142); `distinct_queries` up; `stop reason` = "saturated" not "max_queries";
  same-or-better yield at lower query cost.
- **Decision gate.** If perseveration drops and yield/query improves → proceed to the fork. If the
  Searcher merely finds new ways to spin → strengthens the case for a planner (Fork A) over
  mediation.
- **Deferred:** anything semantic; any new agent; the term-feed.

---

## 5. The fork

The anchoring fix and the Pickens mediation **cannot live on one path**, because they put the
intelligence in different places:

- Dropping the proper noun is a **semantic decision** (place-bound permit rules *must* name
  Yellowstone; bear-spray technique *must not* require it). Only an **LLM planner** can make that
  call.
- Pickens' Prospector/Miner mediation is **algorithmic** ($w_f/w_r$ fusion + term suggestions). It
  improves depth-prioritization, breadth, and vocabulary, and deepens R1's stopping — but it has
  **no semantic model**, so a mediation-only system **still anchors**.

Therefore:

- **Fork A — Semantic Planner** (orchestrator-worker). Fixes the headline problem
  (anchoring/narrow exploration). Strong prior evidence (scouting P). *Recommended main track.*
- **Fork B — Algorithmic Mediation** (Pickens Miner queue + Prospector term-feed). Does **not** fix
  anchoring; fixes depth-prioritization, breadth, vocabulary, and deepens stopping. A **complement
  to layer onto A later**, or a **cheaper deterministic alternative** if we want no more LLM agents
  (accepting the anchoring limitation).

---

## 6. Fork A — Semantic Planner

### R2A — Static sub-goal planner *(the minimal planner)*

- **Hypothesis.** A tool-less planner that decomposes each intent into a few **scoped sub-goals,
  each tagged `entity-bound` or `transferable`**, dispatched to the Searcher one at a time, breaks
  the anchoring and surfaces grade-3 transferable docs. *Basis:* scouting P; discovery-search
  goal-phrased-no-names; DR §3.2 tool-less planner + decompose.
- **Minimal change.** New **Planner agent** (tool-less, one-shot, like the Analyst): intent → 3–6
  sub-goals with the bound/transferable tag, and for transferable ones an explicit "do **not**
  require the entity name." Controller dispatches each sub-goal to the *existing* Searcher (the
  sub-goal becomes its objective) and Judger. **Still static** — decompose once, no re-planning.
  Reuses R1's controller.
- **Test & metric.** *Primary:* `anchor_free%` > 0, and **grade-3 count** up vs R0 single-intent (0).
  Transferable docs (bear-spray, ten-essentials, water) appear in the judged set. *Guard:*
  entity-bound sub-goals *keep* the anchor (the model made this distinction 5/5 in P).
- **Decision gate.** If anchor-free dispatch lifts grade-3/recall → planner thesis holds; go dynamic.
  If sub-goals are poorly scoped or the Searcher still anchors transferable ones → fix the Planner
  prompt first.
- **Deferred:** re-planning; cross-intent reasoning; term-feed; fusion.

### R3A — Dynamic re-planning *(the static→dynamic upgrade)*

- **Hypothesis.** A planner that **reads each sub-goal's Searcher+Judger results and the R1
  freshness/saturation signals, then chooses the next sub-goal** (pursue a vein, open a new avenue,
  or stop) beats static decomposition at equal budget — and stops honestly. *Basis:* DR §3.2–3.3
  dynamic workflow + gap/discrepancy reflection; Pickens responsiveness; "reliable stopping" open
  problem (DR §8).
- **Minimal change.** Wrap the per-intent loop in a planner step: after each sub-goal, feed the
  planner a **compressed** result digest (grades, saturation, terms seen, coverage-so-far); it emits
  the next sub-goal or a **falsifiable done** ("no new relevant facet across N sub-goals"). Effort
  cap stays in the controller.
- **Test & metric.** Dynamic vs static (R2A) at **equal judgment budget**: higher grade-≥2 recall,
  better distinct-facet coverage, appropriate stop. Track planner token cost (DR §6 — gains track
  spend).
- **Decision gate.** If dynamic > static enough to justify the extra planner calls → adopt; else keep
  R2A static and bank the win.
- **Deferred:** synthesis/report; cross-intent fusion.

---

## 7. Fork B — Algorithmic Mediation (Pickens)

*Can layer onto Fork A after R2A, or run as a cheaper standalone that won't fix anchoring.*

### R2B — Freshness/relevance-fused Miner queue

- **Hypothesis.** Building the Judger's work-queue as a **$w_r w_f$-weighted Borda fusion across
  *all* queries** (not per-query ranked descent) prioritizes the documents most worth judging and
  shifts attention off exhausted veins. *Basis:* Pickens §4.3.1, eq. 3.
- **Minimal change (controller + Judger queue).** Maintain the running set of query result-lists with
  $w_r,w_f$; score unseen docs by $\sum w_r w_f\,\text{borda}(d,L_k)$; feed the Judger the top unseen
  by that score. No new LLM agent.
- **Test & metric.** At equal judgment budget, more grade-≥2 docs judged earlier (precision-at-budget
  up); less effort on tapped veins. Compare vs R1.
- **Decision gate.** If fused prioritization beats ranked descent → keep; else revert (deterministic,
  low-risk to try).
- **Deferred:** the term-feed (R3B); any semantics.

### R3B — Prospector term-suggestion feed

- **Hypothesis.** Mining high-value terms from the **fresh-and-relevant** lists ($\text{rlf}$
  weighted by $w_r w_f$, minus terms already used) and surfacing them to the Searcher improves
  register/vocabulary breadth the model won't reliably self-generate. *Basis:* Pickens §4.3.2;
  tactics pearl-growing; discovery-search vocabulary translation.
- **Minimal change.** Controller computes the term feed and injects the top-k as a hint in the
  Searcher's context each turn. Searcher otherwise unchanged.
- **Test & metric.** `distinct_queries`/vocabulary diversity up; new relevant veins found that
  R2B/R1 missed; watch for noise.
- **Decision gate.** If the feed lifts recall without flooding noise → keep, and consider porting it
  into Fork A's planner; else drop.
- **Deferred:** everything else.

---

## 8. Deferred track — the write phase *(do NOT start until the read phase is good)*

Synthesis/report for TREC-RAG Task R: outline-first STORM-style synthesis, **RRF fusion across
intents**, and a **separate citation/verify pass** ("attribution ≠ truth," DR §3.6/§8). This is
write-heavy and single-threaded (DR §4.4) — architecturally separate, and pointless to build before
retrieval recall is solved.

## 9. Recommended path, open decision, and gates

**Recommended sequence.**
1. **R1** — shared, minimal, fixes a measured bug, builds the freshness signal. *(Candidate first
   backlog task.)*
2. **Fork A: R2A → R3A** — main line (fixes anchoring; P-validated).
3. **Fork B: R2B (then R3B)** — complement layered onto A after R2A, *or* a cheaper standalone if we
   decide against more LLM agents.

**Open decision — first release.** R1 first (recommended: minimal, de-risks the planner, builds the
freshness signal) **vs.** R2A first (go straight at the headline anchoring problem; treat R1 as a
fast-follow). To be decided after this report is read.

**Gates that pick the fork for us.** R1's outcome signals whether the Searcher's problem is
mechanical (lean Fork B) or strategic (lean Fork A). R2A's grade-3 lift signals whether the semantic
planner earns its keep before investing in R3A.

## 10. Risks / cautions

- **MAST / "Don't Build Multi-Agents"** (DR §4.3): keep the planner the single locus of decisions;
  isolate workers; don't over-fragment intents.
- **Cost** (DR §6): orchestration gains track token spend (~15× a chat turn); cap in the controller,
  measure \$/answer each release.
- **Don't re-mash into a big-bang.** Each release above is independently shippable and measurable;
  resist bundling.
