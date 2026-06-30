---
name: discovery-search
description: >-
  Run a literature or source search that balances assembling the known canon (recall) with
  finding categories of work you don't already know exist (discovery), while staying bounded.
  Use this whenever the task is to survey a field, find the approaches/solutions/prior work on a
  topic, build a related-work or background section, compile sources for a report, or answer
  "what's been done about X" — any search where missing an entire category of work would quietly
  corrupt the result. Especially reach for it when you'd otherwise build queries around the names
  and methods you already know, when recent or boundary work might exist, or when the user asks for
  a "comprehensive," "thorough," or "fuller" search. Apply it even if the user only says "find
  what's out there," "research X," or "what else is there" without naming this method.
---

# Discovery Search

## Why this exists

The default way to search a topic is to look up the canon you already know: query by author
name, by method name, by famous-paper title. That is **recall** — and it is genuinely good at
assembling the established literature. But it is structurally blind to whatever you *don't* already
know to name. A query built around a method presupposes that method; it cannot surface a different
method family, a recent paper, or work at the edge of an adjacent field. So a search made entirely
of name/method lookups reliably produces a survey that *looks* complete while missing whole
categories — and a missed category silently corrupts everything built on top of it.

This skill fixes that by treating **recall** and **discovery** as two different jobs with separate
budgets, and by bracketing the recall work with two thin, cheap discovery passes. It is built to be
**bounded**: discovery is a capped minority of effort with hard stopping rules, not an open-ended
review of everything ever written.

## The failure modes it prevents

Keep these in mind — every move below targets one of them:

1. **Confirmation-driven search** — every query is a lookup for something you already know exists.
2. **Vocabulary anchoring** — searching a concept only in your home field's dialect, so the same
   idea named in an adjacent field's terms stays invisible.
3. **Staleness blindness** — named-paper lookups cannot find recent or boundary work by construction.
4. **Closed taxonomy** — walking in with a fixed list of categories and only ever populating slots,
   so an approach with no slot is never searched for.

## Core principle: budget discovery, and spend it

Reserve a fixed minority of the search budget — roughly a quarter to a third — for discovery moves.
**Do not declare the task done until that discovery budget is spent or a stopping rule fires.** The
asymmetry justifies the reservation: a missed category is very costly, an extra discovery query is
cheap. The cap is what keeps it bounded.

## Sequencing: discovery → recall → discovery

Do not sprinkle discovery randomly. Use two thin bookends around the recall bulk.

**1. Front pass (cheap, ~3–4 queries).** Map the territory *before* populating it:
- Find one recent **survey or "open challenges / open problems"** paper and read only its **section
  headings and taxonomy**. You are not reading it for content — you are diffing its category list
  against yours to ask "which of its columns do I not have a slot for?" A survey is the cheapest map
  of a field's structure.
- Run one or two **goal-phrased queries** (see moves below).

**2. Recall pass (the bulk).** Now populate each category with name/method/title lookups. This is
the part the default approach already does well — do it thoroughly.

**3. Back pass (~3–4 queries).** Populating the map reveals gaps the front pass couldn't:
- Run **one-hop citation traversal** from your single best hit (see moves).
- Explicitly interrogate the assembled results: **"what approach has no slot here?"** Then run a
  query aimed at that suspected gap.

## Discovery moves

Each move is tied to a failure mode and carries its own bound.

**A. Goal-phrased queries** *(fixes confirmation-driven search).* For each thing the work is
*trying to achieve*, run one query phrased as the **goal**, containing **no author or method names**.
Goal-phrasing surfaces alternative method families a method-named query cannot.
- *Method-named (recall):* "Steck unbiased MNAR estimator recommender."
- *Goal-phrased (discovery):* "evaluate recommender without held-out historical data."
- Bound: one per goal, ~2–3 total.

**B. Vocabulary translation** *(fixes vocabulary anchoring).* Build a tiny alias table mapping your
2–3 most central concepts into the **dialect of the nearest adjacent field**, and search each
concept in both dialects.
- *Example:* recsys "ask users to judge unseen items" ↔ IR "pooling / relevance judgments / test
  collection." The same idea, titled in the other field's words, is otherwise invisible.
- Bound: translate the 2–3 most central concepts only.

**C. Recency sweeps** *(fixes staleness blindness).* For each category, run at least one query that
is **concept + recent year + nothing else** — no names, no famous methods.
- *Example:* "recommender offline evaluation user judgments 2025."
- Use the actual current year; a stale year returns stale results.
- Bound: one per category.

**D. Survey-as-map** *(fixes closed taxonomy).* Covered in the front pass — find one survey, read
its headings, diff against your category list. Bound: one survey, headings-only.

**E. One-hop citation traversal** *(highest yield, naturally bounded).* From your **top one or two**
most on-point hits, look at what they **cite** (backward) and, where available, what **cites them**
(forward) — exactly **one level deep**. A strong target's reference list is often the entire
neighborhood. Bound: one hop, from at most two seed papers, never recursive.

**F. Mine the artifact for concrete nouns** *(bypasses canon entirely).* When a source (a transcript,
a paper, a brief) names specific **datasets, labs, named experiments, tools, or people**, search
those nouns directly. They lead to work that no method-name query would reach. Bound: chase only
nouns the source itself surfaced.

## Stopping rules (this is what keeps it bounded)

- **Saturation:** stop a category when two consecutive *distinct* new queries return only
  already-seen sources. The signal is *repetition of results*, not exhaustion of your ideas.
- **Triage gate:** a discovered item earns a fetch or a citation hop **only if it names a category
  or mechanism not already represented.** If it is just another instance of a known slot, log it in
  one line and move on. This rule is what stops discovery from becoming "read everything" — most
  discovered items cost one line, not an investigation.
- **Caps:** ≤3–4 queries per category; a global soft cap around 30 total. Past that, the honest move
  is to tell the user a fuller dedicated review is warranted rather than fake completeness.
- **Depth limit:** citation traversal is one hop, never recursive.

## Definition of done

Both conditions are required:
1. Every category in your (now diffed-and-expanded) taxonomy is populated, and
2. The back discovery pass surfaced **no new category**.

Then **state condition 2 explicitly in the output as a falsifiable claim** — e.g., "No new method
family appeared across N goal-phrased, recency, and citation-traversal queries." This sentence is
cheap, it is honest about the limits of the search, and it is exactly the kind of claim a reader can
later refute by producing a counterexample. Do not imply completeness you did not test for.

## A note on proportion

The change from a default search is small in volume — typically six to eight queries reallocated and
reordered, not doubled. The point is not to search more; it is to spend a fixed slice of the search
on the moves that can find what you didn't know to look for, and to stop on rules rather than on the
feeling of being finished.
