# Agentic ISJ — an Investigation Planner over Cottontail

**Status:** proposed / draft, **prepared for Mark and Charlie to review.** This is
the **primary-system** spec for the Cottontail TREC RAG 2026 entry. Track-facing
concerns (corpus/task facts, output formats, docid parity, dev-data harness, build
plan) remain in [`docs/trec-rag-2026-design.md`](trec-rag-2026-design.md). Open
questions are marked **⚑ For Mark / Charlie** inline and collected at the end.

This spec **supersedes the primary-system direction in
[`docs/agentic-gcl-search-spec.md`](agentic-gcl-search-spec.md)** (the RISC /
compiler-loop framing). The RISC ideas survive as background; the *system we are
going to build* is the one described here.

The CLI, HTTP server, and tool surface this design binds to are specified in
[`docs/cottontail-jsonl-cli-spec.md`](../reference-specs/cottontail-jsonl-cli-spec.md),
[`docs/cottontail-search-server-spec.md`](../reference-specs/cottontail-search-server-spec.md), and
[`docs/cottontail-search-agent-spec.md`](cottontail-search-agent-spec.md).

---

## 1. Thesis — Interactive Searching and Judging, faithfully

The system mirrors **Interactive Searching and Judging (ISJ)** as practised by
Cormack, Palmer, and Clarke at TREC-6 (SIGIR '98) using the MultiText system.
Four human searchers, working independently, produced a TREC-6 qrels set that
matched the official pool's effectiveness with **one-quarter the judgements and
~105 person-hours** (2.1 hours / topic). The MultiText UI gave them only:

1. a **manual Boolean query** (no auto-translation, no recall fallbacks),
2. matching documents **ranked by passage length and number of passages
   satisfying the query** (proximity / cover-density),
3. **passages with the query terms highlighted**,
4. a way to **render a relevance judgement**.

The searchers' loop: formulate a Boolean query → judge the ranked passages →
continue down the list until the rate of relevant judgements *dropped to a level
where continuing seemed fruitless* → reformulate the query, or abandon the
topic. No formal strategy beyond *find as many relevant documents as possible
with reasonable effort*.

We are not changing that loop. **The agent plays the role of the human
searcher.** Cottontail provides the engine the MultiText system provided in
1998: precise Boolean (GCL) cover finding, passage-ranked results, full-document
read-back. The LLM provides the reading, the judging, and the reformulation a
human did.

> **The ranker's job is to find all of the relevant passages, document their
> source (docid + cover span), and order them from most useful to least.**
> Everything in this document is in service of that single deliverable.

### 1.1 What this system is not

- **Not** the RISC / compiler-loop design in `docs/agentic-gcl-search-spec.md`.
  That design proposed a precise→broad *compound query list* authored up front
  with tier-by-tier ranking. ISJ is the opposite: one query at a time, read
  judgments down the list, reformulate based on what you read.
- **Not** a bag-of-words ranked-retrieval system. The agent writes Boolean (GCL)
  queries; cover-density / proximity is a *reading order*, not the verdict.
- **Not** a system whose output is a single free-text answer. The output is a
  **graded, sourced ranked list of relevant passages**; the optional RAG-task
  answer is compiled *from* that list, not produced in parallel with it.

### 1.2 The one place we improve on the 1997 humans

The TREC-4 hand-written queries (Charlie's upstream
`claclark/Cottontail:apps/trec4.queries`) used **no NOT**: excluding material
you cannot see is dangerous when you are authoring blind. The agent **reads
what it excludes**, so `!>` / `!<` (cover-carving) become first-class precision
tools with a *carve-and-verify* reflex — after a carve, read a sample of what
the carve *removed* to confirm it did not drop relevant material. Interactivity
licenses sharp tools; the agent should use exclusion *more* freely than the
zero-shot author would, not less.

---

## 2. The typed protocol — five artifacts

The system is a small set of **single-transformation agents** that read and
write five typed artifacts. No agent sees the whole picture; every agent's
prompt is "given input X of type T, produce output Y of type U." The five
artifacts are the entire system state.

| Artifact | Carries | Written by | When |
|---|---|---|---|
| **INP** — Information-Need Profile | what the question really asks | Analyst | once per topic; re-emitted on `regenerate_inp` |
| **CM** — Concept Map | the vocabulary universe for searching this topic | Cartographer (seed) + Bookkeeper / Tactician (enrich) | seeded once; enriched after every task |
| **IP** — Investigation Plan | the report outline + the typed task list | Strategist (initial) + Bookkeeper / Critic (revise) | seeded once; revised after every task |
| **TaskResult** | what one task produced | Session Controller (collecting Judge outputs) | once per task |
| **RankedList** | the final ranked, sourced relevant passages | Compiler | once at end (or on early termination) |

The rest of §2 specifies the schema and semantics of each.

### 2.1 INP — Information-Need Profile

A structured paraphrase of the question into machine-actionable parts. The
Analyst produces it once; the Critic may prescribe a regeneration.

```jsonc
{
  "literal":   "the original user question, verbatim",
  "compressed":"one-sentence essential question (intent compression)",

  "question_type": {
    "primary":   "decision-support | synthesis | exploratory | comparative | known-item",
    "secondary": ["normative", "comparative", "exploratory", ...]      // optional, ordered
  },

  "nucleus": {                                                          // when entity-anchored
    "entity":          "Geoffrey Hinton",
    "entity_variants": ["Hinton", "Dr. Hinton", "Geoffrey Everest Hinton",
                        "the godfather of AI"],
    "predicate":       "warned about dangers of AI",
    "context_events":  ["resignation from Google, May 2023"]
  },

  "sub_questions": [                                                    // for multi-part questions
    { "id": "Q1", "text": "...", "load_bearing": true,  "section_id": "§1" },
    { "id": "Q2", "text": "...", "load_bearing": true,  "section_id": "§2" }
  ],

  "outline": [                                                          // report sections
    { "id": "§1", "title": "Background",                "from": ["Q1"] },
    { "id": "§2", "title": "The resignation and timing","from": ["Q2"] }
  ],

  "negative_space": {                                                   // unstated defaults
    "population":  "humans",
    "era":         "contemporary",
    "domain":      "general",
    "register":    "scientific-research",
    "purpose":     "descriptive enumeration",
    "_provenance": { "population": "absence of 'animal'" }
  },

  "temporal_scope": {
    "kind":        "implicit-post-event | implicit-current | explicit-range | none",
    "anchor":      "Hinton's resignation, May 2023",
    "enforcement": "language-proxies | date-filter"                     // ClimbMix has no dates
  },

  "framing_vs_content": {
    "framing_only": ["I'm a college student", "no tech background"],
    "content":      "Hinton × AI-warnings (only)"
  },

  "answer_style": {                                                     // consumed by Writer; NOT searcher
    "audience":   "college student, no tech background",
    "voice":      "narrative explainer",
    "length":     "medium",
    "tech_floor": "explain technical terms in passing"
  },

  "rubric": {
    "kind":   "ladder | grid",
    "ladder": [                                                         // when kind=ladder
      { "grade": 4, "criterion": "system-level discussion across all dimensions" },
      { "grade": 3, "criterion": "in-depth on one major thread" },
      { "grade": 2, "criterion": "one factor or one instance in detail" },
      { "grade": 1, "criterion": "tangential mention" },
      { "grade": 0, "criterion": "wrong topic" }
    ],
    "grid": {                                                           // when kind=grid
      "axes":  ["entity_presence", "predicate_presence"],
      "cells": { "EP_PP": 4, "EP_PA": 2, "EA_PP": 2, "EA_PA": 1 }
    }
  },

  "fences": [                                                           // anti-drift ceilings
    { "id": "F1", "topic": "Hinton research papers / citation graph", "ceiling": 1 },
    { "id": "F2", "topic": "general AI primers / future-of-AI without Hinton",
      "ceiling": 1 },
    { "id": "F3", "topic": "AI safety voices without Hinton mention", "ceiling": 2 }
  ]
}
```

**Slots that are non-optional for every topic:** `literal`, `compressed`,
`question_type.primary`, `outline`, `rubric`. **Conditionally present:**
`nucleus` (named-entity questions), `sub_questions` (multi-part questions),
`temporal_scope.anchor` (event-anchored questions), `fences` (when adjacent
attractor topics threaten drift).

> **⚑ For Mark:** the `rubric` is the per-topic relevance criterion the Judge
> applies on every passage. Two shapes are supported (ladder when the question
> has one ordering axis; grid when the nucleus has two orthogonal axes). Are
> there question shapes you expect that fit neither — and should we admit a
> third `kind` for them?

### 2.2 CM — Concept Map

The vocabulary universe the Query Author draws from. Every term in the CM
either **arrived from a passage during a Learn / Disqualify / Hunt task** or is
a small **seed** the Cartographer emitted at the start. Every harvested term
carries its passage source — the audit trail is part of the schema.

```jsonc
{
  "positions": [
    {
      "id":         "P1",
      "name":       "creativity",
      "role":       "target-attribute",        // target-attribute | instance-class |
                                               // measure | actor | threat | dimension |
                                               // nucleus-entity | nucleus-predicate | ...
      "morphology": "exact",                   // "exact" | "stemmed"
      "core":       "creativity",
      "variants":   [
        { "term": "creative thinking", "source": null,             "morphology": "exact" }
      ],
      "instances":  [],                        // named members of a class
      "manifestations": [                      // specific forms an abstract takes
        { "term": "divergent thinking", "source": "shard_00123_456", "morphology": "stemmed" }
      ],
      "kinds":      [                          // subtypes for umbrella concepts
        { "term": "Big-C / Little-C",          "source": "shard_00045_789" }
      ],
      "related_positions": ["P2"],             // pivots for Learn-by-inversion
      "calibration": {
        "df":         12354,
        "tag":        "decent"                 // zero | tiny | decent | oceanic
      },
      "_provenance":  "Analyst-seeded; enriched T2, T3"
    }
  ],

  "register_pos": [                            // `+` group baked into every Hunt
    "study", "research", "measured", "assessed", "participants", "subjects",
    "sample", "N=", "validity", "reliability", "psychometric", "peer-reviewed"
  ],

  "register_neg": [                            // anti-register
    "tips", "ideas", "brainstorming", "workshop", "creative writing",
    "marketing", "advertising"
  ],

  "carves": [                                  // `!>` clusters from Disqualify
    {
      "id":       "C1",
      "name":     "popular-usage cluster",
      "cluster":  "(+ tips ideas brainstorming workshop \"creative writing\" marketing)",
      "source":   "T6 Disqualify"
    }
  ],

  "acronyms": [                                // deterministic expansions
    { "code": "AI",  "expansion": "artificial intelligence",     "ambiguous_with": [] },
    { "code": "ML",  "expansion": "machine learning",            "ambiguous_with": [] },
    { "code": "AGI", "expansion": "artificial general intelligence" }
  ],

  "anchors": [                                 // for Learn-by-inversion
    { "kind": "concept-anchor", "from_position": "P_threat", "to_position": "P_measure" },
    { "kind": "expert-anchor",  "from_position": "P_researcher", "to_position": "P_instrument" },
    { "kind": "system-anchor",  "from_position": "P_system", "to_position": "P_dimension" }
  ]
}
```

**The Cartographer's seeding rule:** a position may carry seed terms (typically
≤ 3 per slot) emitted from world knowledge, but every term must be tagged with
`source: null` so the Bookkeeper can spot which terms have *not* yet been
corpus-confirmed. Calibrate replaces `source: null` with a calibration tag.

**Morphology default:** *exact* for proper names, the topic's defining noun
(*creativity*, *Hinton*, *Leitkultur*), and short common words whose
morphological cognates are noise (`creative` vs. `creativity`). *Stemmed* for
verb-adjective-noun families that share semantic content (*measure /
measurement / measured*; *screen / screening / screened*).

### 2.3 IP — Investigation Plan

The outline of the report + the typed task list + budgets and stop rules. The
Strategist emits the initial IP; the Bookkeeper revises it mechanically; the
Critic can prescribe a restructure.

```jsonc
{
  "outline": [
    { "id": "§3", "title": "Comparative anatomy of major systems",
      "load_bearing": true, "from_sub_questions": ["Q3"] }
  ],

  "tasks": [
    {
      "id":     "T1",
      "type":   "learn-direct | learn-by-inversion | calibrate | disqualify | hunt",
      "pivot":  "concept-anchor | expert-anchor | system-anchor | null",
      "goal":   "harvest measure vocabulary via researcher names",
      "position_focus": ["P_measure", "P_researcher"],
      "section_id":     "§3",                                // which outline section this serves
      "draft_queries":  ["(^ creativity researcher)"],       // Query Author may refine
      "judging_policy": "harvest | grade",                   // grade for Hunt; harvest for Learn
      "stop": {                                              // task-local stop rule
        "kind":            "fixed-budget | window-rate | none",
        "budget_passages": 8,
        "window_W":        5,
        "min_rate_theta":  0.2
      },
      "state":  "pending | active | succeeded | failed | dropped"
    }
  ],

  "task_ordering": ["learn-direct", "learn-by-inversion",
                    "calibrate", "disqualify", "hunt"],

  "budget": {
    "topic_max_judgements":      300,
    "topic_max_llm_tokens":      "...",
    "per_task_max_judgements":   60
  },

  "abandon_rule": {                                         // topic-level (not task-level)
    "max_fruitless_reformulations": 3
  },

  "stop_conditions": {
    "every_LB_section_has_grade_3_count":   5,
    "every_populated_matrix_cell_has_count":3,
    "every_grid_cell_has_count":            1,
    "topic_budget_exhausted":               true
  },

  "coverage_matrix": {                                      // counters maintained by Bookkeeper
    "axes":  ["section", "matrix_cell"],
    "cells": { "§3 × Turkish-language":    { "grade_3_plus_count": 4 } }
  },

  "counters": {                                             // Bookkeeper state for Critic triggers
    "fence_breach":          { "F1": 0, "F2": 1 },
    "reformulations_per_task":{ "T7": 2 },
    "revisions_since_change":3,
    "critic_invocations":    0
  }
}
```

### 2.4 TaskResult

The output of one task. The Session Controller emits one per task.

```jsonc
{
  "task_id":  "T7",
  "task_type":"hunt",
  "queries_run": [                                          // the queries actually executed
    {
      "id":       "Q7.1",
      "gcl":      "(^ \"Geoffrey Hinton\" (+ warning danger risk concern) (+ AI \"artificial intelligence\"))",
      "strategy": "initial",                                // or one of the Tactician.Reformulate
                                                            // enum: add_synonym | tighten_proximity |
                                                            // add_facet | add_carve |
                                                            // split_into_subqueries
      "passages_seen": 12
    }
  ],

  "judgements": [                                           // present when task_type=hunt
    {
      "docid":      "shard_00459_61697",
      "grade":      4,
      "passage":    { "start": 4123, "end": 4271, "text": "..." },
      "surfacing_query_id": "Q7.1",
      "justification":      "Hinton explicitly cites job displacement as a key warning ...",
      "evidence_quote":     "...up to 125 chars..."
    }
  ],

  "harvest": [                                              // present when task_type=learn-*
                                                            //              or disqualify
    {
      "term":            "Alternative Uses Task",
      "from_passage":    { "docid": "shard_00012_345", "start": 100, "end": 220 },
      "proposed_position":"P_measure",                      // Bookkeeper Rule 1 places this
      "proposed_role":   "measure"
    }
  ],

  "drift_signals": {
    "queries_missing_nucleus":  [],
    "judgements_over_ceiling":  [{ "fence_id": "F2", "grade_given": 3, "docid": "..." }]
  },

  "budget_used": {
    "judgements": 12,
    "queries":    1,
    "wall_clock_ms": 18432
  },

  "task_outcome": "succeeded | abandoned | failed | dropped",
  "abandonment_reason": "window-rate < 0.2 for last 5 judgements" // when abandoned
}
```

### 2.5 RankedList

The deliverable. Produced once by the Compiler from accumulated TaskResults.

```jsonc
{
  "topic_id":  "...",
  "entries": [
    {
      "rank":               1,
      "docid":              "shard_00459_61697",
      "grade":              4,
      "best_passage":       { "start": 4123, "end": 4271, "text": "..." },
      "surfacing_query":    "(^ \"Geoffrey Hinton\" (+ warning danger ...) ...)",
      "surfacing_task_id":  "T7",
      "justification_chain":["task T2 surfaced 'job displacement' as a risk",
                             "task T7 confirmed Hinton names this risk"],
      "ordering_signals":   { "grade": 4, "query_tier": 1, "cover_length": 148 }
    }
  ],
  "metadata": {
    "passages_judged":    "...",
    "passages_relevant":  "...",
    "topic_budget_used":  "..."
  }
}
```

**Ordering:** `(grade desc, query_tier asc, cover_length asc)`. *Grade* is the
primary signal: a grade-4 docid always outranks a grade-3 docid. *Query tier*
breaks ties by which query surfaced the passage — precise queries (more facets,
narrower covers) outrank broader ones. *Cover length* is the cheap sub-tiebreak.
Per-docid deduplication keeps the best passage; long documents appear once.

> **⚑ For Mark:** the Compiler's ordering is intentionally simple. The
> "Level-1 / Level-2" ladder from the RISC spec (read-judgment as primary
> signal; listwise LLM rerank) is *recoverable* from this baseline by replacing
> the Compiler with a richer one — the rest of the system doesn't change. Is
> the grade-first / query-tier / cover-length baseline the right floor to ship
> first?

---

## 3. The framework vocabulary

Six examples grew this vocabulary; what follows is the cumulative naming. The
artifact schemas above bind to these names.

### 3.1 Question-type taxonomy

| Type | Marker | Plan shape |
|---|---|---|
| **Decision-support** | *"should I … / does X help Y / is X effective"* | direct-evidence first; quality-of-evidence facet; prefer SRs/RCTs |
| **Synthesis / report-writing** | *"what are the differences / impediments / factors …"* | enumerate instances and manifestations; coverage across a matrix is the stop signal |
| **Exploratory / definitional** | *"what is X / how does X work"* | broad explanatory passages; multiple perspectives |
| **Comparative** | *"X vs. Y / does X differ from Y"* | paired evidence on both arms |
| **Known-item / lookup** | *"find the document about Z"* | tight Boolean cover, single Hunt, narrow stop rule |

Hybrids are explicit: `primary` plus an ordered list of `secondary` types (the
healthcare topic is synthesis-dominant with secondary comparative, exploratory,
normative).

### 3.2 Concept-map roles

A position's `role` controls which slots are populated and which Hunts can use
it. The recurring roles, with examples from the six worked topics:

| Role | Carries | Examples |
|---|---|---|
| `target-attribute` | the topic's defining attribute | creativity; achilles tendonitis |
| `instance-class` | an abstract class with named instances | foreign minorities in Germany; major healthcare systems |
| `manifestation` | a dimension of an abstract concept | cultural differences (religion, gender, education) |
| `argument-position` | a named position of a relation | target / threat / measure / actor / status (airport security) |
| `nucleus-entity` | the named entity at the heart of the question | Geoffrey Hinton |
| `nucleus-predicate` | the specific act/property of the entity | warned about AI dangers |
| `context-event` | a referenced event that scopes the answer | resignation from Google |
| `pivot-anchor` | a position used to harvest another position's vocabulary | researchers (creativity); systems (NHS, USA, ...) |

Per-position slots: `variants` (same concept, other words) · `instances`
(concrete members) · `manifestations` (specific forms) · `kinds` (abstract
subtypes) · `morphology` (exact vs. stemmed).

**`morphology` is per-term, not per-query.** It is the *default* for a position
and may be overridden per individual variant. The Query Author realizes the
choice as per-atom GCL syntax — bare `<term>` for exact, `porter:<term>` for
stemmed — never as a whole-query stemming pass. See §4.1.4.

### 3.3 The four Learn pivots

When one position is under-named in the corpus, search a related well-named
position and read passages to harvest the under-named one.

| Pivot | Anchor (well-named) | Target (under-named) | Example |
|---|---|---|---|
| **Direct** | the position's term IS the corpus's term | itself | "achilles tendonitis" → variants tendinopathy / tendinosis |
| **Concept-anchor** | a related concept | the underspecified position | airport threats → security measures |
| **Expert-anchor** | researchers / authors / institutions | their methods / instruments / outputs | creativity researchers → AUT, RAT, Torrance Tests |
| **System-/exemplar-anchor** | well-named instances of a class | the field's transferable vocabulary | NHS / USA / Canada → financing vocabulary |

The Strategist records on the CM (`anchors[]`) which pivots are active and
between which positions.

### 3.4 Task types

| Type | Purpose | Output | Judging policy | Stop rule |
|---|---|---|---|---|
| **Learn-direct** | discover variants/instances/manifestations from corpus passages | harvest | none — read, don't grade | fixed budget (e.g. 5–10 passages) |
| **Learn-by-inversion** | as above, via a pivot anchor | harvest | none | fixed budget |
| **Calibrate** | df / count probe per facet | calibration tags | none | one probe per facet |
| **Disqualify** | surface a false-positive cluster to author a `!>` carve | carve cluster | brief — confirm cluster | a few passages |
| **Hunt** | find and judge relevant passages | judgements (graded qrels) | full ISJ inner loop | moving-window relevance rate `θ` |

### 3.5 Drift control

| Mechanism | What it prevents | Recorded as | Enforced by |
|---|---|---|---|
| **Load-bearing thread (drift-toward guard)** | dropping a hard but central sub-question | `sub_questions[].load_bearing = true` | Bookkeeper Rule 11 + Critic trigger T2 |
| **Anti-drift fence (drift-away guard)** | expanding into a popular adjacent topic | `INP.fences[]` with `ceiling` grade | Judge enforces ceiling; Bookkeeper Rule 5 + Critic trigger T4 |
| **Query-nucleus rule** | a Hunt query that drops the named anchor | `INP.nucleus.entity` and `predicate` | Query Author + Bookkeeper Rule 6 |

### 3.6 Outline-first scaffolding

For synthesis questions, the report outline is the **first artifact** the
Analyst emits, before the concept map. Each outline section binds to one or
more sub-questions, and each Hunt task binds to one outline section. The
coverage stop rule reads per-section counts.

### 3.7 Self-reframing

For verbose/conversational questions, the Analyst includes intent compression
and (for synthesis topics) a "what would I need to search for to write a report
on this?" reframing. The compressed form drives every downstream prompt; the
literal form stays on the INP for audit and for the final answer's framing.

### 3.8 Negative-space inference

The Analyst enumerates the unstated defaults — population, era, domain,
register, purpose — and records each with a `_provenance` line ("inferred from
absence of 'animal'"). These slots are auditable and adjustable.

### 3.9 Temporal scope

When the question is event-anchored or carries an implicit time qualifier, the
Analyst records the scope (`implicit-post-event`, `implicit-current`,
`explicit-range`, `none`), the anchor, and how it will be enforced
(`date-filter` if the corpus has dates; `language-proxies` otherwise — ClimbMix
is in the latter regime).

### 3.10 Acronym expansion

Deterministic step in the Analyst / Cartographer pipeline: every acronym in the
literal question is expanded into a `+` group with both forms. Ambiguous
expansions are recorded so Disqualify can carve the wrong sense.

---

## 4. The agent roster

Six LLM roles + four engine roles. Every LLM role has a focused prompt — one
input artifact (or slice), one output artifact (or delta) — and no global
knowledge of the others.

### 4.1 LLM roles

#### 4.1.1 Analyst

- **Input:** the literal question.
- **Output:** the INP (§2.1).
- **Job:** intent compression, question-type classification, nucleus
  identification, sub-question decomposition with LB flags, negative-space
  inference, framing-vs-content split, temporal scoping, rubric authoring
  (ladder or grid), anti-drift fence enumeration, outline emission.
- **Sees:** the question text only. Never the corpus, never GCL.

#### 4.1.2 Cartographer

- **Input:** the INP.
- **Output:** the initial CM (§2.2).
- **Job:** seed concepts and roles from the INP — variants / instances /
  manifestations / kinds the LLM can plausibly emit from world knowledge — and
  identify which pivots will be needed (concept-anchor, expert-anchor,
  system-anchor). Pick the register vocabulary from the INP's register slot.
- **Sees:** the INP only. Never the corpus.
- **Discipline:** every seed term is tagged `source: null`. The Bookkeeper
  treats `source: null` terms as *unconfirmed* — Calibrate must confirm them
  before they appear in a Hunt's `+` group, or Learn must replace them with
  passage-sourced variants.

#### 4.1.3 Strategist

- **Input:** the INP + the seed CM.
- **Output:** the IP (§2.3).
- **Job:** order the outline; emit the typed task list (Learn-direct →
  Learn-by-inversion → Calibrate → Disqualify → Hunt); bind each task to its
  outline section and position-focus; set per-task stop rules (`W`, `θ`,
  budget); set topic-level budget; set stop conditions (per-section,
  per-matrix-cell, per-grid-cell); set the `abandon_rule` (max fruitless
  reformulations).
- **Sees:** the INP and the CM. Never the corpus.

#### 4.1.4 Query Author

- **Input:** one task from the IP + the relevant CM slice (the focal positions,
  their variants, the register `+`, the carves `!>`).
- **Output:** one or more GCL queries for that task.
- **Job:** compile the focal positions into a GCL expression using the CM's
  morphology choices; bake in the register `+` facet (only on Hunt and
  Disqualify); apply the carves `!>`; for Hunt tasks enforce the
  **query-nucleus rule** (every query must carry `INP.nucleus.entity`); produce
  precise→broad candidates when the task is a Hunt.
- **GCL operators:** `^` (And) · `+` (Or) · `<>` / `...` (FollowedBy /
  proximity) · `<<` / `>>` (Contained / Containing) · `!>` / `!<` (NotContaining
  / NotContainedIn). (Verified against `src/parse.cc`.)
- **Sees:** task + CM slice. Never the INP rubric, never the corpus directly.

**Morphology is per-atom, not per-query.** The Query Author emits the morphology
choice directly into the GCL: bare `<term>` for `morphology=exact`,
`porter:<term>` (the stemmed-stream atom for the index's stemmer, per
`docs/stemming.md`) for `morphology=stemmed`. A single query routinely mixes the
two — e.g. `(^ creativity (+ measure porter:measure))` keeps the topic noun
exact (its cognates *creative* / *creator* are noise vectors here) while letting
the verb facet match *measured* / *measurement* without enumerating each form by
hand. The CLI's `--stem` flag, which rewrites a whole expression by passing
every term through the stemmer (`apps/jsonl_core.cc:stem_gcl`), is a convenience
for humans running one-off queries and is **not** invoked by the agent.
Stemming is a tool the agent **composes into the cover**, not a switch it
toggles. The exact and stemmed streams are co-located in the same index (the
index was built with `--stem`); a `+`-group can address either or both.

#### 4.1.5 Judge

- **Input:** one passage + the INP rubric + the task mode (`hunt` or
  `learn-*` or `disqualify`).
- **Output:**
  - in `hunt` mode: a graded judgement (grade 0-4) with quoted evidence and a
    short justification — respecting the `fences[].ceiling` from the INP.
  - in `learn-*` / `disqualify` mode: a structured harvest (terms with the
    role they appear to fill, plus the passage as `source`).
- **Job:** apply the per-topic rubric; respect anti-drift fence ceilings; emit
  quoted evidence so the judgement is auditable.
- **Sees:** one passage, the INP rubric, the task mode. Never the plan, never
  which task the passage came from, never the rest of the trace.

#### 4.1.6 Tactician

Two narrow LLM calls, each invoked only by the Bookkeeper on the corresponding
escalation:

- **Tactician.Reformulate** *(failing Hunt → replacement queries).*
  - **Input:** the abandoned task, its queries, the grade ≤ 1 passages it
    surfaced (≤ 5), the CM slice for its position-focus.
  - **Output:** one or two replacement queries, each tagged with a strategy
    from a fixed enum: `add_synonym(term)` · `tighten_proximity` ·
    `add_facet(facet)` · `add_carve(cluster)` · `split_into_subqueries(facets)`.
  - **Why the strategy enum:** so the Critic trigger T1 ("same task reformulated
    R₂ ≥ 3 times *without strategy converging*") is well-defined.

- **Tactician.PlaceConcept** *(stray harvest term → CM position).*
  - **Input:** the term, the passage text it came from (excerpt), the current
    CM.
  - **Output:** either `attach_to(position_id)` or `add_position(name, role,
    seeds)`.

#### 4.1.7 Critic

Defined in §6.3 — see there for the full contract.

#### 4.1.8 Writer (RAG output only)

- **Input:** the RankedList + the INP.answer_style.
- **Output:** a TREC RAG `rag_output_*.jsonl` answer object —
  `{ references, answer:[{text, citations}] }`.
- **Job:** synthesize grounded sentences from the cited cover passages; honor
  the audience/voice/length from `answer_style`; per-sentence citations index
  into `references`; ≤125-char quoted source per item.

### 4.2 Engine roles (deterministic; no LLM)

#### 4.2.1 Searcher

The Cottontail tool layer. Per task, the Session Controller calls into one of:

| Tool | Cottontail action | Returns |
|---|---|---|
| `triage(expr, k, judged_set)` | `ssr_ranking` over `:item` excluding docids in `judged_set` | passages in proximity order, windowed per the cover-window rule |
| `mine(docid, expr)` | solutions of `(<< (^ expr) (>> :item (>> :docno "<docid>")))` | every cover inside one document, tightest first |
| `read(docid, around?)` | extension of `jsonl_get` | full body or a window around a span |
| `count(expr)` | `count_matches` | match count (and/or cover count) |
| `df(term)` | `idx()->count(featurize(term))` (already exposed by `--explain`) | document frequency |

`triage` and `read` are the workhorses for Hunt; `mine` populates per-document
passages once a document is judged relevant; `df` and `count` serve Calibrate.

**Per-topic judged-set state.** The Searcher owns a `judged_set: Set<docid>`
per (run, topic) and excludes its members from `triage` results. This is what
gives the agent the MultiText UI's "Next" button — *the system tracks what
has been judged, the LLM does not have to.*

> **⚑ For Mark / Charlie:** the judged-set is server-side state. Either a new
> stateful endpoint pair (`POST /sessions/{id}/judge`, `POST
> /sessions/{id}/triage`) or per-request `judged_docids: [...]` injection. I
> lean toward per-request injection so the server stays stateless and the
> agent's session state lives in one place (the orchestrator). Confirmation?

#### 4.2.2 Session Controller

Drives the ISJ inner loop for a single Hunt task. Pseudocode:

```
def run_hunt(task, queries, rubric, fences):
    seen_in_task = 0
    window      = deque(maxlen=task.stop.window_W)
    for q in queries:
        cursor = Searcher.triage(q.gcl, k=∞)
        for passage in cursor:
            if seen_in_task >= task.stop.budget_passages: break
            j = Judge(passage, rubric, mode="hunt")
                # Judge respects fences[].ceiling
            record_judgement(j)
            window.append(1 if j.grade >= 3 else 0)
            seen_in_task += 1
            if len(window) == window_W and mean(window) < task.stop.min_rate_theta:
                break       # query exhausted; reformulate
        if window-rate-low or topic-budget-spent: break
    return TaskResult(...)
```

For Learn / Disqualify tasks the loop is simpler: read up to `budget_passages`
passages and call Judge in harvest mode. Calibrate calls `df` / `count` once
per facet.

#### 4.2.3 Bookkeeper

The rules engine that does ≥90% of the Reviser's work. Fully specified in
§6.1.

#### 4.2.4 Compiler

Produces the RankedList from the union of all TaskResults' judgements.
Mechanical ordering: `(grade desc, query_tier asc, cover_length asc)`. Per-docid
deduplication; longest document appears once via its best passage.

`query_tier` is assigned by the Strategist on each Hunt query at IP-build time
(tier 0 = most precise, increases by 1 per relaxation step) and inherited by
each judgement from `surfacing_query.tier`.

#### 4.2.5 Validator (RAG output only)

Schema validation, citation-validity check, NLI entailment per sentence. Drops
or repairs weak citations; recomputes `references` to be exactly the cited set.

### 4.3 Roster summary

| Layer | Role | Type | When invoked |
|---|---|---|---|
| Understand | Analyst | LLM | once at start; once per `regenerate_inp` |
| Map | Cartographer | LLM | once at start; once per `add_cm_position` |
| Plan | Strategist | LLM | once after CM; once per `restructure_outline` |
| Execute | Query Author | LLM | per task |
| Execute | Judge | LLM | per passage |
| Execute | Searcher | engine | per query |
| Execute | Session Controller | engine | per Hunt |
| Adapt | **Bookkeeper** | engine | every TaskResult |
| Adapt | **Tactician.Reformulate** | LLM (narrow) | per failing Hunt (Rule 10) |
| Adapt | **Tactician.PlaceConcept** | LLM (narrow) | per stray harvest term (Rule 1) |
| Adapt | **Critic** | LLM (rare) | per T1–T5 escalation; one of seven prescriptions |
| Compile | Compiler | engine | once at end |
| Compile (RAG) | Writer | LLM | once at end |
| Compile (RAG) | Validator | engine | once at end |

---

## 5. Control flow

Six phases. The phases are nested: Phase 4 is the main loop; everything else
fires once per topic (with the exception that Phases 1-3 may re-fire on a
Critic prescription).

```
Phase 1  Understand
    Question                  ─►  Analyst        ─►  INP

Phase 2  Map
    INP                       ─►  Cartographer   ─►  CM

Phase 3  Plan
    INP + CM                  ─►  Strategist     ─►  IP

Phase 4  Execute   (loop per task, in IP order, until IP.stop_conditions)
    for task in IP.next_tasks():
        Query Author(task, CM)                       ─►  queries
        Session Controller(queries, INP.rubric, task.mode):
            while not task.stop:
                passage    ←   Searcher.next_unjudged(current_query)
                outcome    ←   Judge(passage, INP.rubric, task.mode)
                Session Controller updates window-rate / harvest accumulator
            returns TaskResult
        Bookkeeper(CM, IP, TaskResult)               ─►  CM', IP', signals
        switch signals:
            continue                                  → outer loop picks next task
            stop                                      → enter Phase 5
            Tactician.Reformulate(failing_task)       → replacement queries
            Tactician.PlaceConcept(stray_term)        → CM' update
            CriticEscalation(trigger, evidence)       → Critic → prescription
                                                                       │
            prescription routes to upstream agent or in-place update   ▼
                regenerate_inp        → Analyst
                add_cm_position       → Cartographer
                restructure_outline   → Strategist
                widen/narrow_fence    → INP update in place
                revise_rubric         → INP update in place
                accept_and_terminate  → stop
                replan_only           → Bookkeeper re-prioritizes

Phase 5  Compile
    {TaskResults}             ─►  Compiler       ─►  RankedList

Phase 6  Write   (RAG only)
    RankedList + INP.answer_style ─► Writer      ─►  answer
    answer                        ─► Validator   ─►  validated answer
```

**The orchestrator's job** is to host the six artifacts (INP, CM, IP, the
accumulating TaskResults, the RankedList) and route signals out of the
Bookkeeper. It is not an agent; it is the kernel that holds state and dispatches.

---

## 6. Self-correction

The system corrects itself through the Bookkeeper's rule set, the Tactician's
two narrow calls, and the Critic's rare structural diagnoses. The Critic is
the only "meta" agent; everything else is single-transformation.

### 6.1 Bookkeeper — eleven rules

Owns all mechanical state updates. Takes a TaskResult and the current
`(CM, IP)`; emits `(CM', IP')` plus one or more signals to the orchestrator.

| # | Rule | Trigger | Action |
|---|---|---|---|
| 1 | **Apply harvest** | TaskResult.harvest non-empty | per term: pattern-match to a CM position by role; if it fits → add with `morphology` inherited from parent and `source` = passage docid; if no position fits → escalate `Tactician.PlaceConcept(term, passage, CM)` |
| 2 | **Apply calibration** | TaskResult from Calibrate | write df / count onto each term; tag as `zero` / `tiny` / `decent` / `oceanic` |
| 3 | **Apply carves** | TaskResult from Disqualify | add the carve cluster to `CM.carves[]`; mark downstream Hunts for query recompilation |
| 4 | **Update coverage matrix** | TaskResult from Hunt | per judgement with grade ≥ threshold (default 3): increment the (section × matrix-cell) counter; per grid cell increment the grid counter |
| 5 | **Verify anti-drift fences** | always | any judgement with grade > fence ceiling on a fenced topic → increment `IP.counters.fence_breach[fence_id]` |
| 6 | **Verify query-nucleus rule** | always | scan TaskResult.queries: any Hunt query missing `INP.nucleus` → reject the TaskResult, mark task to be re-run with corrected query |
| 7 | **Schedule additive tasks from harvest** | harvest non-empty | per fixed templates: new instance → Hunt for it (or extend an existing Hunt); new researcher → expert-anchor Learn; new measure → Hunt for it; new threat → Learn-by-inversion on it |
| 8 | **Drop dead tasks** | calibration in Rule 2 produced any new `zero` tags | any pending task whose required terms are all zero-df → set `state = dropped`, log reason |
| 9 | **Compute stop signal** | always | check `IP.stop_conditions`: every LB section ≥ N, every populated matrix cell ≥ M, every grid cell ≥ 1, or topic budget exhausted → emit `stop` |
| 10 | **Detect a failing Hunt** | TaskResult.task_outcome == "abandoned" AND task's `(matrix_cell).df > 0` | escalate `Tactician.Reformulate(task, queries, low_grade_passages, cm_slice)`; increment `IP.counters.reformulations_per_task[task_id]` |
| 11 | **Detect Critic-escalation conditions** | counters cross thresholds | per the T1–T5 table in §6.3 → emit `CriticEscalation(trigger, evidence)` |

Rules 1, 7, and 10 are the only ones that escalate to an LLM (Tactician);
everything else is straight state update. The Bookkeeper has a complete
unit-test surface: feed fixture TaskResults, check the `(CM', IP', signals)`
delta.

### 6.2 Tactician — two narrow LLM calls

#### 6.2.1 Tactician.Reformulate

```
Input:
  - the abandoned task (its goal, position_focus, draft_queries)
  - the queries actually run
  - up to 5 grade ≤ 1 passages it surfaced (so the model sees what went wrong)
  - the CM slice for the task's position_focus

Output (structured, one of):
  { strategy: "add_synonym",         params: { term: "..." },
    replacement_query: "(^ ... ...)" }
  { strategy: "tighten_proximity",   params: {},
    replacement_query: "(... ...)" }
  { strategy: "add_facet",           params: { facet_position: "...",
                                               terms: ["...", "..."] },
    replacement_query: "..." }
  { strategy: "add_carve",           params: { cluster: "(+ ...)" },
    replacement_query: "(!> ...)" }
  { strategy: "split_into_subqueries", params: { facets: [...] },
    replacement_queries: ["(...)", "(...)"] }
```

The named strategy makes the move auditable, and is the discriminant the
Bookkeeper uses for the T1 counter — only *strategy-converging* reformulations
count toward T1, so the Tactician is not penalized for trying genuinely
different moves.

#### 6.2.2 Tactician.PlaceConcept

```
Input:
  - the harvest term
  - the passage text excerpt it came from
  - the current CM (positions with their roles)

Output (structured, one of):
  { decision: "attach_to",   position_id: "P_..." }
  { decision: "add_position", name: "...", role: "...", seeds: ["..."] }
```

### 6.3 Critic — contract

The Critic is the structural diagnostician. Where the Tactician fixes a
**local** problem (one failing Hunt or one stray term), the Critic looks at the
whole trace and identifies whether an **upstream artifact** has gone wrong.

#### 6.3.1 Input bundle

- the current INP, CM, IP
- the last K TaskResults (default K = 5)
- the trigger that fired and its evidence

#### 6.3.2 Output — exactly one prescription from a closed enum

| Prescription | Effect (which agent re-runs, on what) |
|---|---|
| `regenerate_inp(slot, reason, hint)` | re-run **Analyst** on the literal question with `hint` constraining one INP slot (e.g. "question-type was misclassified — re-classify as synthesis with secondary normative") |
| `add_cm_position(name, role, seeds, rationale)` | **Cartographer** extends `CM` with one new position |
| `restructure_outline(diff, rationale)` | **Strategist** re-emits the IP outline with section adds / removes / splits |
| `widen_fence(fence_id, reason)` / `narrow_fence(fence_id, reason)` | adjust `INP.fences[fence_id].ceiling` in place (Bookkeeper) |
| `revise_rubric(slot, change, rationale)` | adjust `INP.rubric` in place (Bookkeeper) |
| `accept_and_terminate(reason)` | the corpus doesn't have more to find; emit `stop` |
| `replan_only(hint)` | nothing upstream is wrong; Bookkeeper re-prioritizes pending tasks per `hint` |

One LLM call. One structured output. The Critic **prescribes**; it does not act.
The orchestrator routes the prescription to the appropriate upstream agent
(Analyst / Cartographer / Strategist) or updates state in place.

#### 6.3.3 Triggers — when the Bookkeeper fires the Critic

All five are mechanically detectable from counters the Bookkeeper already
maintains. Each ships its evidence inside the Critic's bundle.

| ID | Trigger | Default threshold | Likely diagnosis the Critic must pick between |
|---|---|---|---|
| **T1** | Hunt-reformulation cycle stuck | Tactician.Reformulate has run ≥ 3 times on the same task without window-rate clearing θ | CM lacks the right vocabulary for this cell, OR the cell shouldn't exist (matrix mis-shaped), OR the rubric is too strict |
| **T2** | Load-bearing thread starved | LB thread has had ≥ 2 Hunt attempts, none yielded grade ≥ 3 passages | rubric mis-set for this thread, OR CM missing a position the thread needs, OR corpus doesn't carry it |
| **T3** | Coverage stalled across revisions | no new matrix cells filled across the last 3 revisions, and stop condition unmet | outline needs restructuring, OR rubric too strict, OR plan has converged short |
| **T4** | Fence-breach rate too high | `fence_breach` counter ≥ 5 in the last 10 judgements | fence mis-set, OR rubric mis-set, OR nucleus mis-identified |
| **T5** | Budget mid-warning | ≥ 50% of topic budget spent, < 25% of expected coverage achieved | global rethink — replan vs. restructure vs. accept-and-terminate |

#### 6.3.4 Critic budget

Hard cap on Critic invocations per topic (default **3**). If exceeded → the
Bookkeeper forces `accept_and_terminate` without invoking the Critic again.
Prevents thrashing on hard topics.

#### 6.3.5 Counter persistence across upstream regeneration

When the Critic prescribes `regenerate_inp` (or `add_cm_position` /
`restructure_outline`):

- counters tied to the regenerated artifact **reset** (T2 thread-starvation
  counters reset because the threads themselves are now different),
- cross-artifact counters **persist** (T5 budget, `critic_invocations`).

### 6.4 Self-correction summary — failure → check table

| Failure mode | Caught by |
|---|---|
| Hunt query drifts off the nucleus | Query Author + Bookkeeper Rule 6 (query-nucleus rule) |
| Hunt expands into adjacent topic | Judge (fence ceiling from INP) + Bookkeeper Rule 5 → T4 → Critic |
| Term is zero-posting / oceanic | Calibrate task + Bookkeeper Rule 8 (drop dead tasks) |
| Load-bearing thread starved | Bookkeeper Rule 11 → T2 → Critic |
| Window-rate never recovers | Session Controller (abandon-after-fruitless) + Bookkeeper Rule 10 → Tactician.Reformulate → eventually T1 → Critic |
| Vocabulary leaks (CM has unread terms) | Cartographer seeds tagged `source: null`; Bookkeeper Rule 1 only promotes corpus-sourced terms to Hunt-eligible |
| Grade inflation (Judge too lenient) | optional second-pass Judge with stricter prompt on a sample of top-RankedList |
| Answer unsupported (RAG) | Validator NLI entailment per sentence |
| Plan is structurally wrong | Critic-on-demand (one of seven prescriptions) |

---

## 7. Mapping to Cottontail

The agent layer is what's new; Cottontail's tool layer is largely already in
place. What follows is the exact mapping.

### 7.1 Tools already shipped

The JSONL CLI + HTTP server exposes (per
[`docs/cottontail-jsonl-cli-spec.md`](../reference-specs/cottontail-jsonl-cli-spec.md) and
[`docs/cottontail-search-server-spec.md`](../reference-specs/cottontail-search-server-spec.md)):

| Server endpoint | Used by |
|---|---|
| `POST /tools/search_gcl` | the Searcher's `triage(expr, k)` — already returns proximity-ordered passages with `:item` deduplication |
| `POST /tools/get_document` | the Searcher's `read(docid)` |
| `POST /tools/count_matches` | the Searcher's `count(expr)` |
| `POST /tools/explain` | the Searcher's `df(term)` for Calibrate (per-leaf df) |
| `GET /describe` | the orchestrator on startup (tool schemas) |

### 7.2 Engine additions required

To complete the ISJ Searcher contract:

1. **Server-side or per-request `judged_set` filtering.** The Searcher must
   skip docids already judged in this (run, topic) session. Two implementations
   are possible; see the **⚑ For Mark / Charlie** in §4.2.1.

2. **Cover-windowed passage return.** Each result's passage text should be
   widened symmetrically to the configured window `W` per the windowing rule
   in `docs/agentic-gcl-search-spec.md` §3 (the windowing rule itself survives
   the move to ISJ). The window is presentation only — scoring/ordering is on
   the raw cover.

3. **`mine(docid, expr)`** — enumerate the solutions of
   `(<< (^ expr) (>> :item (>> :docno "<docid>")))` and return every cover in
   that document, tightest first, each with its windowed text. This is the one
   genuinely new engine capability; it is **cheap because bounded to one
   document** and is used (1) for Hunt mode when a document is judged grade ≥ 3
   and we want all its relevant passages for §RAG evidence, and (2) for
   document-scoped reformulation (Tactician.Reformulate may want to inspect a
   confirmed-good document's structure).

4. **Optional: graded-judgement endpoint.** A `POST /tools/judge` endpoint that
   accepts `{ docid, grade, justification, evidence_quote }` and persists into
   a session-scoped qrels accumulator. Convenient but not strictly necessary —
   the orchestrator can hold judgements in memory.

### 7.3 Carving is already supported

`!>` (`NotContaining`) and `!<` (`NotContainedIn`) are already parsed
(`src/parse.cc:33-36`) and implemented (`src/gcl.h:137,154`). The Query Author
uses them freely.

### 7.4 Proximity-width operator (open)

The TREC-4 queries used a hard `< [n]` proximity-width operator (e.g.
`(("nuclear" + "atomic") ^ ("plant" + ...)) < [5]`); Cottontail's GCL has none.
The ISJ system can operate without it (cover-length ordering is the soft
substitute), but adding it would let the Query Author author tighter Hunts on
broad queries. Open question per `docs/agentic-gcl-search-spec.md`.

### 7.5 No new ranking on the hot path

The agent's **judgement** is the verdict. `icover` / `ssr` / `tiered`
cover-density rankers (`src/ranking.cc`) survive as **baselines**
(`docs/trec-rag-2026-design.md` §6); they are not in the agent's submission
path. `ssr` is what `triage` calls under the hood — but as the *reading order*,
not the rank-it-and-ship answer.

---

## 8. Output for TREC RAG 2026

Per `docs/trec-rag-2026-design.md` §2 / §7:

### 8.1 Task R — `r_output_trec_rag_2026.tsv`

The Compiler emits the RankedList; the orchestrator writes one row per entry:

```
<topic_id>  Q0  <docid>  <rank>  <score>  <run_id>
```

`rank` restarts at 1 per topic; `score` is a non-increasing function of
`(grade, query_tier, cover_length)` — typically `grade + 0.1 / (1 + query_tier)
+ 0.01 / (1 + cover_length / 100)` or similar; the exact monotone function is a
tuning detail; the *ordering* is what matters.

### 8.2 Task RAG — `rag_output_trec_rag_2026.jsonl`

The Writer (§4.1.8) and Validator (§4.2.5) produce the schema-conforming
object per topic. Evidence is the RankedList's top entries (grade ≥ 3); the
Writer is **not** asked to do retrieval — it grounds sentences in the already-
judged-and-graded passages.

> **⚑ For Mark:** how deep into the RankedList does the Writer pull evidence?
> Default: all grade ≥ 3, or up to a cap (say 25 entries). Probably driven by
> token budget on the Writer model.

---

## 9. Eval and dev-data harness

Per `docs/trec-rag-2026-design.md` §8: 24 dev topics, three UMBRELA judges,
research rubrics, nuggets. The agentic-ISJ system is the *system under test*;
its **agent policy** (prompts, rubric authoring, stop rules, fence
calibration, Critic thresholds) is the configuration space.

### 9.1 Per-topic deliverables (eval-side)

The orchestrator writes, per topic:

- the literal question + the INP (full plan trace)
- the CM (final state)
- the IP (with all task states and counters)
- the union of TaskResults
- the RankedList (Task R input)
- the RAG answer (Task RAG input, when requested)
- a trace log: every task's queries, judgements, harvest, drift signals

### 9.2 Agent-by-agent fixture tests

Each agent has a typed contract (one input artifact → one output artifact),
which makes fixture-style unit testing straightforward:

- Analyst: 6+ fixtures (one per worked example in Appendix A), check INP slots.
- Cartographer: feed an INP, check CM positions / roles / seed sourcing.
- Strategist: feed INP+CM, check IP outline + task list + ordering.
- Query Author: feed task+CM slice, check GCL conforms to morphology rules,
  carries the nucleus (Hunt), bakes the register `+` (Hunt / Disqualify),
  applies carves.
- Judge: feed passage+rubric, check grade is consistent with rubric criteria;
  feed harvest-mode fixtures, check extraction.
- Bookkeeper: pure unit tests — every rule, every escalation.
- Tactician.Reformulate: feed a failing Hunt fixture, check the strategy enum.
- Tactician.PlaceConcept: feed a stray harvest, check attach-to vs.
  add-position.
- Critic: feed each trigger fixture (T1–T5) with a synthetic trace, check the
  prescription kind.
- Compiler: pure unit tests on RankedList ordering.

### 9.3 Significance and Goodhart guards

Inherit the `docs/trec-rag-2026-design.md` §8 protocol:

- **Significance, not deltas** — paired bootstrap / randomization, hold across
  all three UMBRELA judges.
- **Held-out split / k-fold.**
- **Prior-plausibility weighting** — prefer policy / prompt changes with a
  mechanistic explanation; an unexplained dev win is an overfitting smell.
- **Goodhart guard** — the gold is LLM-generated; the real eval is human
  battles; cross-judge agreement narrows but does not close the gap.
- **Cost-aware** — optimize metric-per-cost. Critic invocations cost more than
  Bookkeeper invocations; Reformulations cost less than Critics.

### 9.4 Head-to-head against the §6 baselines

The point of `docs/trec-rag-2026-design.md` §6 baselines (self-hosted tuned
BM25, book pure-`rankProximity`, optionally full CISC pipeline) — the agentic
ISJ system must beat them on the dev harness before we commit to it as the
submission. The baselines are *not* on the agent's hot path; they are
comparison points.

---

## 10. Open choices

Carried forward from the design discussion. Each is a **⚑ For Mark / Charlie**
the implementation should not close without explicit input.

1. **Stop-this-query rule.** Moving window `W` and threshold `θ`? Defaults in
   the IP schema; harness-tunable.
2. **Abandon-this-topic rule.** Max fruitless reformulations `R`? Hard topic
   judgement budget?
3. **Judgement grading granularity.** 0–4 (UMBRELA-aligned, default) vs. binary
   (1998-faithful).
4. **Multi-searcher pooling.** Parallel personas (multiple agent sessions per
   topic) vs. sequential reframings vs. single-pass? Default single-pass for
   now; parallel-personas is the natural next experiment.
5. **Final ordering for Task R.** Grade-first / query-tier / cover-length
   (default) vs. MTF-by-discovery vs. listwise LLM re-rank as an optional
   Compiler upgrade.
6. **Tool minimalism.** Strict (Boolean + passages + judge + abandon) vs. relax
   with `df` / `count` as planner pre-checks. Default: relaxed — Calibrate
   needs them.
7. **Passage-return window size `W`.** Charlie's window-around-cover rule; size
   open for ClimbMix's ~400-word median document. Probably 200–250 words.
8. **Highlight format in the passage return.** Inline tags around matched
   tokens vs. a separate offset list vs. both.
9. **Plan representation.** Canonical JSON in the harness + Markdown view in
   prompts.
10. **Re-plan cadence.** After every task (default), every K judgements, or
    only on a failed Hunt.
11. **Budget allocation.** What fraction of token budget is allowed for
    Learn / Calibrate / Disqualify before Hunt starts.
12. **Source-quality / register vocabulary — universal lists per register or
    planner-authored per topic?**
13. **Read-grounded expansion bar.** Add every interesting term, or only those
    appearing in K independent grade ≥ 3 passages.
14. **Calibrate as first-class task or inline pre-check before each Hunt?**
    Default first-class for audit trail.
15. **Negative-space inference — display to user (clarifying questions) vs.
    record on plan.** Default: record; raise on Critic escalation.
16. **Per-term morphology recorded on the CM node or only in GCL.** Default:
    on the CM node, for audit.
17. **Triad-coverage in the stop rule (Def-Op-Instrument)** for measurement
    questions — graded signal, not hard gate.
18. **Register `+` facet — always on or off during Learn.** Default: **off
    during Learn, on during Hunt / Disqualify**.
19. **Anti-drift fence enforcement.** Rubric ceiling + query-nucleus rule (both
    on by default — belt and braces).
20. **Acronym disambiguation.** Auto-expand; Disqualify carves the wrong
    sense.
21. **Grid vs. ladder rubric.** Planner picks; both supported.
22. **Temporal scoping on a date-less corpus.** Language-proxies (default for
    ClimbMix) vs. a soft grade-time-recency preference.
23. **Framing → answer-style influence on the searcher.** Default: none. The
    answer style affects Writer only.
24. **Server-side vs. per-request judged-set.** Per-request, default — keeps
    server stateless.
25. **`replan_only` vs. Bookkeeper default ordering.** Critic's hint
    overrides; without Critic, Bookkeeper uses default order.
26. **Critic budget per topic.** Default ≤ 3 invocations.
27. **Counter persistence across upstream regeneration.** Partial: artifact-
    bound counters reset; cross-artifact persist.
28. **Strategist's task ordering — fixed (Learn → Calibrate → Disqualify →
    Hunt) or topic-shape-dependent?** Default fixed; the Critic can prescribe
    `replan_only` to override.
29. **Mining a confirmed-relevant document for its other passages — automatic
    on every grade-3+ judgement, or only when the RAG-evidence compiler asks
    for it?** Default: only on demand from the Writer.
30. **Writer evidence depth.** All grade ≥ 3 entries or top N (e.g. 25);
    token-budget driven.

---

# Addendum A — Six worked examples

Six topics, each shown as the artifact trace the system would emit. The
examples illustrate one or more features of the framework; together they cover
the abstractions catalogued in §3.

The format for each: literal question · INP highlights · CM highlights · IP
task list · what features this example exercises. JSON is shown in compact form
for readability; the canonical schemas are §2.

## A.1 Decision-support — "Will wearing an ankle brace help heal achilles tendonitis?"

Exercises: decision-support question-type · variants / mechanism / alternative
vocabulary · register vocabulary (clinical-evidence) · anti-register carve
(commercial marketing).

```jsonc
INP
  literal:    "Will wearing an ankle brace help heal achilles tendonitis?"
  compressed: "Does ankle bracing help heal Achilles tendonitis?"
  question_type: { primary: "decision-support" }
  sub_questions:
    Q1 (LB) does bracing improve AT outcomes?         → §1
    Q2 (LB) what is the mechanism (immobilization)?   → §2
    Q3      how does bracing compare to alternatives  → §3
              (eccentric loading / Alfredson protocol)?
  outline:
    §1 Direct evidence on brace efficacy for AT
    §2 Mechanism: immobilization for tendon healing
    §3 Comparison with alternatives
  negative_space:
    population: humans (no "animal")
    era:        contemporary
    register:   clinical-evidence
    purpose:    decision-support
  rubric: kind = ladder
    4: RCT or SR on bracing for AT, with effect estimate
    3: cohort or guideline statement on bracing for AT
    2: indirect evidence (mechanism or alternative-intervention comparison)
    1: anecdote / blog
    0: unrelated

CM
  P1 condition  role: target-attribute  morph: exact
     core: "achilles tendonitis"
     variants: tendinopathy, tendinosis, calcaneal tendinitis, heel cord tendinitis
     adjacent: retrocalcaneal bursitis, Haglund, AT rupture
  P2 intervention  role: target-intervention  morph: stemmed
     core: "ankle brace"
     variants: bracing, orthosis, AFO, ankle support
     mechanism: immobilization, offloading, rest
     alternatives: heel lift, eccentric exercise, Alfredson protocol,
                   taping, CAM walker, casting
  register_pos: randomized, trial, RCT, "systematic review", "meta-analysis",
                cohort, controlled, "double-blind", placebo
  register_neg: buy, shop, best, review, price, sale, discount
  carves: C1 commercial-marketing cluster

IP (abbreviated)
  T1 Learn-direct        AT vocabulary
  T2 Learn-direct        bracing/immobilization vocabulary
  T3 Calibrate           df on every variant + alternative
  T4 Disqualify          commercial-marketing cluster
  T5 Hunt §1             (^ achilles (+ tendonitis tendinopathy tendinosis)
                            (+ brace bracing immobilization)
                            (+ trial study evidence randomized))
  T6 Hunt §2             (^ tendon (+ immobilization rest offloading)
                            (+ healing recovery))
  T7 Hunt §3             (^ achilles (+ tendonitis tendinopathy)
                            (+ alfredson eccentric))
  stop_conditions: §1 ≥ N grade-3+ ; §2, §3 ≥ 1 grade-3+
```

## A.2 Synthesis (arity-2) — "What language and cultural differences impede the integration of foreign minorities in Germany?"

Exercises: synthesis question-type · instance-enumeration · manifestation-
enumeration · the report-outline reframing · matrix coverage stop · political-
diatribe Disqualify.

```jsonc
INP
  literal:    [the question, verbatim]
  compressed: "What documented language and cultural differences have
               impeded the integration of foreign minorities in Germany?"
  question_type: { primary: "synthesis" }
  sub_questions (all LB):
    Q1 Who are the foreign-minority communities discussed?
    Q2 What language differences impede integration?
    Q3 What cultural differences impede integration?
  outline:
    §1 Who counts as a foreign minority in Germany (instance enumeration)
    §2 Language barriers
    §3 Religious & cultural practices
    §4 Gender & family norms
    §5 Education & schooling
    §6 Civic / political integration
    §7 Public-discourse debates (Leitkultur, Parallelgesellschaft, multikulti)
  negative_space:
    population: foreign minorities in Germany
    era:        contemporary (1970s–present, post-Gastarbeiter era)
    register:   policy / journalism / sociology
  rubric: kind = ladder
    4: direct discussion of language/cultural impediment for a named community
    3: in-depth on a community or a manifestation
    2: supporting context (statistics, debates)
    1: peripheral mention
    0: not Germany or not integration

CM
  P_community  role: instance-class  morph: exact
    variants: Ausländer, Migrationshintergrund, "foreign nationals",
              "guest workers" (Gastarbeiter), immigrants, migrants
    instances (LEARN T1): Turkish, Kurdish, Afghan, Syrian, Yugoslav,
                          Vietnamese, "Russian-German" / Spätaussiedler,
                          Italian, Greek, Polish
  P_language  role: manifestation
    children: "German proficiency", "language barrier", "heritage language",
              "Integrationskurse", "language test"
  P_culture  role: manifestation
    children (LEARN T2): religion (Islam, Kopftuch, mosque, Ramadan, halal),
                         gender norms, family structure,
                         education attainment, civic participation,
                         public-discourse terms (Leitkultur, Parallelgesellschaft)
  register_pos: policy, sociology, study, report, statistic, integration,
                Bundesamt, OECD
  register_neg: (carve: political-diatribe cluster)
  carves: C1 political-diatribe (T5 Disqualify)

IP (abbreviated)
  T1 Learn-direct     instance enumeration  (community names)
  T2 Learn-direct     manifestation enumeration  (kinds of differences)
  T3 Learn-direct     language-integration vocabulary
  T4 Calibrate
  T5 Disqualify       political-diatribe cluster
  T6 Hunt §2          per (community instance × language facet)
  T7 Hunt §3          per (community instance × religion facet)
  T8 Hunt §4          gender / family
  T9 Hunt §5          education attainment
  T10 Hunt §6         civic / naturalization
  T11 Hunt §7         public-discourse (Leitkultur etc.)
  coverage_matrix: axes = (community × manifestation)
  stop: every populated cell ≥ 1 grade-3+
```

## A.3 Synthesis (arity-5, relational) — "What security measures are in effect or are proposed to go into effect in airports?"

Exercises: argument-position decomposition · Learn-by-inversion
(concept-anchor) · status / modal split · calibration-filtered combinatorial
Hunt assembly.

```jsonc
INP
  compressed: "What airport-security measures are in effect or proposed,
               and against what threats, for what targets, by which actors?"
  question_type: { primary: "synthesis", secondary: ["comparative"] }
  outline:
    §1 Measures by target (passengers, luggage, cargo, ...)
    §2 Measures by threat (hijacking, bombs, insider, drones, cyber)
    §3 Measures by actor (TSA, FAA, ICAO, airlines)
    §4 In-effect vs. proposed (status axis)
  negative_space:
    era: contemporary (post-2001, with current proposed measures)
    register: government-policy / journalism
  rubric: kind = ladder
    4: specific named measure with target / threat / actor / status named
    3: measure with at least 2 of (target, threat, actor, status)
    2: measure named but context thin
    1: incident report only
    0: not airport / not security

CM
  positions (* = upfront-known; ? = needs Learn-by-inversion)
    target*    passengers, carry-on, checked baggage, cargo, mail, personnel,
               aircraft, perimeter, runway, terminal, control tower, IT
    threat*    hijacking, bomb/IED, weapon smuggling, hazmat/CBRN, drugs,
               insider, drone, cyber, sabotage
    measure?   (seed: screening, scanning, watchlist, ID check, K9 —
                T1/T2/T3 will fill via Learn-by-inversion)
    actor*     TSA, FAA, airline, airport authority, CBP, ICAO, private security,
               federal air marshal
    status*    in-effect: deployed, implemented, current, operational, standard
               proposed:  proposed, planned, considering, pilot, draft, bill
  carves: incident-reporting cluster; vendor-marketing cluster

IP (abbreviated)
  T1 Learn-by-inversion (concept-anchor=threat → measure)
                       (^ airport (+ hijacking bomb explosive weapon insider drone))
  T2 Learn-by-inversion (concept-anchor=target → measure)
                       (^ airport (+ luggage cargo perimeter personnel)
                                  (+ check inspect screen verify))
  T3 Learn-direct      security prose
                       (^ airport security (+ measure procedure protocol
                                              technology system))
  T4 Calibrate         (target × threat) cells; drop zero-postings
  T5 Disqualify        incident & vendor clusters
  T6+ Hunt             per (target × status) — parallel in-effect / proposed branches
  coverage_matrix: (target × threat) × status
  stop: every populated (target × threat) cell ≥ 1 grade-3+ AND
        every harvested measure has ≥ 1 airport-context grade-3+ AND
        both status branches have non-trivial coverage
```

## A.4 Methodology inventory — "Find ways of measuring creativity."

Exercises: Learn-by-inversion via **expert-anchor** · Def-Op-Instrument triad
· per-term morphology (exact "creativity" vs. stemmed "instrument") · implicit-
kind enumeration · register `+` for scientific research · popular-usage
Disqualify.

```jsonc
INP
  compressed: "Enumerate the named instruments, tests, and methods researchers
               use to operationalize and measure creativity (in humans)."
  question_type: { primary: "synthesis", secondary: ["exploratory"] }
  sub_questions (all LB):
    Q1 What kinds of creativity does the field distinguish?
    Q2 What named instruments / tests measure each?
    Q3 Who developed each, and how is each validated?
  outline:
    §1 Subtypes of creativity (kinds enumeration)
    §2 Named instruments (Def-Op-Instrument triad per instrument)
    §3 Methodological families (paper-and-pencil, neural, observer-rated, ...)
  negative_space:
    population: humans (no "animal")
    era:        contemporary research methodology
    register:   scientific-research
  rubric: kind = ladder
    4: named instrument with definition + operationalization + validity
    3: instrument named with operationalization
    2: subtype discussed methodologically
    1: popular-press mention of "creativity test"
    0: unrelated

CM
  P_topic   role: target-attribute   morph: exact (CRITICAL: don't stem)
    core: "creativity"
    kinds (Learn T1): divergent thinking, convergent thinking, originality,
                      fluency, flexibility, elaboration,
                      Little-C / Big-C, Pro-C / Mini-C
  P_instrument  role: target-output  morph: stemmed
    seeds: test, scale, instrument, battery, assessment, task, inventory
    to harvest:  Torrance Tests of Creative Thinking, AUT (Alternative Uses Task),
                 RAT (Remote Associates Test), Creative Achievement Questionnaire,
                 ...
  P_researcher  role: pivot-anchor (expert-anchor)  morph: exact
    seeds: researcher, psychologist, professor, "Dr."
    to harvest:  Torrance, Guilford, Mednick, Sternberg, Amabile,
                 Csikszentmihalyi, Runco, Kaufman, Plucker, ...
  register_pos: study, research, measured, assessed, participants, subjects,
                sample, "N=", validity, reliability, psychometric, peer-reviewed
  carves: popular-usage cluster (writing class, marketing, brainstorming)

IP (abbreviated)
  T1 Learn-direct        kinds of creativity
  T2 Learn-direct        instrument seed vocabulary
  T3 Learn-by-inversion  expert-anchor: research-author names
                         (^ creativity (+ researcher psychologist "Dr." professor))
  T4 Learn-by-inversion  per-researcher (chained from T3)
                         (^ <Researcher> creativity)
  T5 Calibrate           drop zero-df instruments / researchers
  T6 Disqualify          confirm popular-usage cluster &
                         confirm exact "creativity" (no stem) helps
                         (compare df("creativity") vs stemmed)
  T7+ Hunt per instrument × Def-Op-Instrument triad
       e.g. (^ "Alternative Uses" creativity (+ measure validity participants))
  T_k Hunt per kind/subtype
  stop: every harvested instrument has ≥ 1 grade-3+ with Def-Op context AND
        every harvested kind has ≥ 1 grade-3+ describing its measurement
```

## A.5 Hybrid synthesis with sub-questions and load-bearing threads — "I'm hoping to grasp the intricacies of different healthcare systems..."

Exercises: intent compression · sub-question decomposition with LB flags ·
question-type hybridization · system-anchor pivot · graded relevance ladder
· **drift-toward guard** on the normative thread · outline-first scaffolding.

```jsonc
INP
  literal:    [verbose multi-clause question]
  compressed: "How do healthcare systems compare on access, cost, equity, and
               the normative question of care as a right vs. privilege —
               and what reforms improve outcomes?"
  question_type: { primary: "synthesis",
                   secondary: ["comparative", "exploratory", "normative"] }
  sub_questions:
    Q1 (LB) what is a healthcare system; access/cost/equity definitions  → §1
    Q2 (LB) healthcare as a right vs. privilege  ← DRIFT-TOWARD GUARD   → §2
    Q3 (LB) comparative anatomy of major systems                        → §3
    Q4 (LB) factors affecting delivery, equity, expenses                → §4
    Q5      reform proposals                                            → §5
  outline:
    §1 Definitions  §2 Rights debate  §3 Comparative anatomy
    §4 Factors      §5 Reforms
  negative_space:
    era:        contemporary
    register:   policy / health-economics + political-philosophy (for §2)
    purpose:    explainer / primer
  rubric: kind = ladder
    4: system-level comparative discussion across access/cost/equity/rights
    3: deep treatment of one thread (one country, or the rights debate)
    2: one factor or one instance in detail
    1: patient anecdote with system context
    0: unrelated

CM
  P_system  role: instance-class / pivot-anchor (system-anchor)  morph: exact
    seeds: NHS UK, USA, Canada Medicare, Germany Bismarck, Sweden,
           Singapore, France, Japan, Switzerland, Netherlands, Cuba, Australia
  P_access      role: dimension   manifestations: universal coverage, uninsured,
                                                  underinsured, wait time, rationing
  P_cost        role: dimension   manifestations: insurance, single-payer, multi-payer,
                                                  premium, deductible, copay, taxation,
                                                  OOP, GDP%
  P_equity      role: dimension   manifestations: disparity, life expectancy,
                                                  infant mortality, social determinants
  P_rights      role: dimension   ← LOAD-BEARING DRIFT-TOWARD GUARD
                vocabulary: human rights, "right to health", "UDHR Article 25",
                            social contract, market commodity, libertarian,
                            communitarian, distributive justice
  P_reform      role: dimension   manifestations: "Medicare-for-all", "public option",
                                                  ACA, value-based care, prevention
  register_pos (policy/econ):   policy, analysis, OECD, WHO, comparative,
                                expenditure, spending
  register_pos (philo):         ethic, philosophy, justice, "right to health"
  carves: partisan op-ed without analysis; pure clinical without policy framing

IP (abbreviated)
  T0 Outline emit
  T1 Learn-direct        healthcare-system vocabulary
  T2 Learn-by-inversion  system-anchor: per known system (NHS, USA, Canada, ...)
  T3 Learn-direct        rights / normative vocabulary  ← serves §2 explicitly
  T4 Calibrate
  T5 Disqualify          partisan-without-analysis cluster; insurance-product marketing
  T6-T9 Hunts §3 comparative; §4 factors; §5 reforms (register=policy)
  T10 Hunt §2            normative (register=philo)
                          ← LB DRIFT GUARD: must run; must yield ≥ N grade-3+
  T11 Hunt §1            definitional
  re_plan_triggers: drift check — §2 has scheduled/active Hunts? if not, spawn
  stop: every §1-§5 ≥ N grade-3+ AND §2 ≥ N grade-3+ on its own
        AND ≥ K named systems represented in §3
```

## A.6 Named-entity event-anchored — "I'm a college student who has seen articles about Geoffrey Hinton and his resignation from Google..."

Exercises: intent compression on a long conversational question · **nucleus
identification** (entity × predicate) · **anti-drift fences** with rubric
ceilings · framing-vs-content split · acronym expansion · grid rubric ·
temporal scoping via language proxies on a date-less corpus.

```jsonc
INP
  literal:     [the verbose college-student question]
  compressed:  "Why did Geoffrey Hinton resign from Google, and what are his
                warnings about AI?"
  question_type: { primary: "synthesis", secondary: ["exploratory"] }
  nucleus:
    entity:         "Geoffrey Hinton"
    entity_variants: ["Hinton", "Dr. Hinton", "Geoffrey Everest Hinton",
                      "the godfather of AI"]
    predicate:      "warned about dangers of AI"
    context_events: ["resignation from Google, May 2023"]
  sub_questions:
    Q1 (LB) Who is Geoffrey Hinton (bounded background)        → §1
    Q2 (LB) Why did he resign from Google? Timing & meaning    → §2
    Q3 (LB) What are his specific warnings?                    → §3 (core)
    Q4 (LB) Why do his warnings carry weight?                  → §4
    Q5 (LB) What specific risks does he name?                  → §5 (drills §3)
  outline: §1-§5 as above
  negative_space:
    era:        post-resignation (May 2023+)
    register:   tech journalism + AI-safety discourse
  temporal_scope:
    kind:        "implicit-post-event"
    anchor:      "Hinton's resignation, May 2023"
    enforcement: "language-proxies"     (ClimbMix has no dates)
  framing_vs_content:
    framing_only: ["I'm a college student", "no tech background",
                   "interested in future of AI"]
    content:      "Hinton × AI-warnings (only)"
  answer_style:
    audience:   "college student, no tech background"
    voice:      "narrative explainer"
    length:     "medium"
    tech_floor: "explain technical terms in passing"
  rubric: kind = grid
    axes:  [entity_presence, predicate_presence]
    cells: { EP_PP: 4, EP_PA: 2, EA_PP: 2, EA_PA: 1 }
    refinements: weight-bearing CV (Turing award, "godfather of AI") → grade 3
                 specific named risks attributed to Hinton           → grade 4
                 same risks without Hinton attribution               → grade 2
  fences:
    F1 Hinton research papers / citation graph             → ceiling 1
    F2 general AI primers / future-of-AI without Hinton    → ceiling 1
    F3 AI safety voices without Hinton mention             → ceiling 2

CM
  P_entity   role: nucleus-entity   morph: exact (proper name; never stem)
    variants: "Geoffrey Hinton", Hinton, "Dr. Hinton", "Geoffrey Everest Hinton",
              "the godfather of AI"
  P_predicate role: nucleus-predicate  morph: stemmed (warn/warned/warning)
    vocabulary: warning, danger, risk, concern, alarm, threat, peril, "spoke out"
  P_event    role: context-event
    vocabulary: resign, resigned, departure, "left Google", "former Google",
                "step down", "free to speak"
  P_risks    role: predicate-subtype  (to harvest from T2)
    seeds: "job loss", misinformation, deepfake, "autonomous weapons",
           "election interference", "existential risk", "control problem"
  P_weight   role: contextual-grade-3
    vocabulary: "Turing award", "deep learning pioneer", backpropagation, Google,
                "University of Toronto"
  acronyms:
    AI  → "artificial intelligence"        (and AI both)
    ML  → "machine learning"
    AGI → "artificial general intelligence"
    LLM → "large language model"
  register_pos: said, told, warned, interview, statement, op-ed, essay,
                podcast, talk, testified, "in an interview"
  carves: ML-research-papers cluster; AI-vendor-marketing cluster;
          generic-AI-explainer cluster

IP (abbreviated)
  T1 Acronym expansion (deterministic; written into CM.acronyms)
  T2 Learn-direct        nucleus-anchored
                         (^ "Geoffrey Hinton" (+ AI "artificial intelligence")
                            (+ warning danger risk concern))
                         → harvest named risks, biographical anchors
  T3 Learn-direct        resignation/timing vocabulary
  T4 Calibrate           df("Hinton") vs df("Geoffrey Hinton"); choose variant
  T5 Disqualify          confirm three carve clusters
  T6 Hunt §3 (core)      his warnings — entity-anchored
                         (^ "Geoffrey Hinton" (+ warning danger risk concern)
                            (+ AI "artificial intelligence"))
                         + register +carves
  T7 Hunt §5             per harvested risk (chained from T2)
  T8 Hunt §4             why his warnings carry weight
                         (^ Hinton (+ "godfather of AI" "Turing award" pioneer
                                       "deep learning" backpropagation))
  T9 Hunt §2             the resignation
                         (^ Hinton Google (+ resign "left Google" "former Google")
                            (+ said cited explained "free to speak"))
  T10 Hunt §1            bounded background — small budget
  query-nucleus rule (Bookkeeper Rule 6): every Hunt query MUST carry
                       "Geoffrey Hinton" or a variant
  fence enforcement (Bookkeeper Rule 5): judgement grade ≤ ceiling on F1/F2/F3
  stop: §3 ≥ N grade-3+ AND §5 enumerates ≥ K distinct named risks each with
        ≥ 1 grade-3+ AND §2, §4 ≥ 1 grade-3+ AND §1 has ≥ 1 short-background
```

---

# Addendum B — Relation to other branch docs

| Doc | Relation to this spec |
|---|---|
| `docs/trec-rag-2026-design.md` | the track-facing wrapper (corpus, docid parity, output formats, dev harness, baselines, build plan); this doc replaces its §4 "primary system" section. The §5 ranking-policy ladder, §6 baselines, §7 RAG-task formatter, §8 dev-data harness, §9 build plan, §10 risks remain authoritative — they are *about* the agentic-ISJ system that this doc specifies. |
| `docs/agentic-gcl-search-spec.md` | superseded as the primary-system direction. The GCL ISA mapping (its §3 / §8), the windowed-passage rule (its §3), and the `!>`-as-first-class observation (its §4) survive and are referenced from this doc. |
| `docs/cottontail-jsonl-cli-spec.md` | the CLI / library contract that the Searcher engine binds to. Unchanged. |
| `docs/cottontail-search-server-spec.md` | the HTTP server contract. Needs one extension: server-side or per-request `judged_set` filtering for `triage` (§7.2 here). |
| `docs/cottontail-search-agent-spec.md` | the prior CISC-style agent design (5 tools: search_text / search_gcl / explain / get_document / count_matches). The 5-tool surface stays — agentic-ISJ uses 4 of them (`search_gcl` for `triage`; `get_document` for `read`; `count_matches` for `count`; `explain` for `df`); plus the new `mine` (§7.2). The example agent's prompt is replaced with the agentic-ISJ multi-agent orchestrator. |
| `docs/cover-density-ranking-from-book.md` | the canonical-source description of the engine's cover-finding machinery (`nextCover`, §2.15 scoring). This spec demotes the §2.15 scoring from final verdict to triage reading-order. |
| `docs/multitext.md` (and Charlie's upstream `apps/trec4.queries`) | the 1997 hand-written Boolean queries that inspire the agent's query shape; the *no-`NOT`* discipline of those queries is the one thing the agent reverses (interactivity licenses `!>`). |
| `docs/stemming.md` | the per-term morphology infrastructure the CM's `morphology: exact` vs `stemmed` choice binds to. |
| `docs/revisiting-bm25.md` | informs the §6 baselines in `trec-rag-2026-design.md`. Not on the agent's hot path. |
