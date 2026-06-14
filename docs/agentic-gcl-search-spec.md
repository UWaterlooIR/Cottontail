# Agentic GCL search — a RISC instruction set for retrieval

**Status:** proposed / draft. This is the **primary-system** spec for the Cottontail
TREC RAG 2026 entry. Track integration, the CISC baselines we aim to beat, and the
evaluation harness live in `docs/trec-rag-2026-design.md`. Not yet an approved
implementation task list.

## 1. Thesis

**Relevance-by-reading replaces relevance-by-scoring.**

Every CISC retrieval instruction — BM25, cover-density ranking, a learned
cross-encoder — is a complex one-shot heuristic that *bakes a guess about relevance
into a score* so that a human, or a dumb pipeline, gets a usable ranked list without
having to think. A tireless, language-fluent agent does not need that crutch. Give it
a *reduced* instruction set — exact Boolean covers with proximity — and let it do
directly what the score was only approximating: **read the material and judge it.**

- **The engine's job collapses to localization:** enumerate covers precisely
  (Boolean set-algebra + proximity). No statistical score, ever.
- **The agent's job is adjudication:** read covers, judge relevance, and reformulate
  the query — with set-algebra precision — until the query's result set *is* the
  relevant set.

The punchline for us: **Cottontail is already a RISC machine.** GCL is the reduced
instruction set; the engine has been computing Boolean covers since Clarke's algebra.
We have simply been hiding it under ranking layers (`icover`, `ssr`, BM25). The move
is to expose the algebra directly to an LLM "compiler" and lift the ranker out of the
hot path.

This is grounded in the canonical source — Büttcher, Clarke & Cormack, *Information
Retrieval: Implementing and Evaluating Search Engines* (MIT Press, 2010), §2.2.2
(`docs/cover-density-ranking-from-book.md`). That chapter splits exactly along the
RISC/CISC line: cover **finding** (§7.1–7.2, `nextCover`) is the precise,
statistics-free localizer we **keep**; cover **scoring** (§7.3 —
`score(d) = Σ 1/(v−u+1)` summed over a document's covers) is a closed-form relevance
heuristic, a one-shot designer's guess, that we **drop** in favor of the agent's
read-judgment. *Keep the book's cover machinery; discard the book's cover score.*

## 2. RISC vs. CISC

- **CISC instruction** (BM25 / cover-density ranking / cross-encoder): one call that
  encodes a complex relevance heuristic, tuned so a human or simple caller gets a
  good ranked list in one shot. Designed for *direct* use. Opaque, hard to redirect,
  and it carries failure modes — idf quirks, document-length normalization, neural
  train/inference query mismatch (see `docs/revisiting-bm25.md`).
- **RISC instruction** (a GCL cover): a simple, exact set-algebra primitive. Tedious
  for a human to wield at scale, but a *compiler* can sequence many of them, with
  feedback, to reach precision and recall that the one-shot CISC instruction cannot.
- **The compiler is the LLM agent.** It sees the whole program (the question), emits
  RISC instructions (GCL queries), inspects intermediate results (reads covers), and
  optimizes (reformulates) — tirelessly.

Historical rhyme: at TREC-4 Clarke hand-wrote Boolean queries with **no interactive
search** and they did well (`docs/multitext.md`). The bottleneck was human effort and
skill. The LLM removes that bottleneck. The bet — Charlie's "grep is all you need" —
is that Boolean covers *used as a tool by an LLM in a loop* can rival or beat BM25 and
dense retrieval. This spec is how we test that bet, and it is deliberately the **pure**
idea: Boolean covers from the book, authored by the LLM. We do **not** add the
keyword→Boolean auto-generators or recall fallbacks from later Clarke/Cormack
variations — those existed only because there was no good query author in the loop,
and they make "better" ambiguous (better generator? better fallback?). There is a good
author now.

## 3. The instruction set (ISA)

A small, orthogonal, exact surface. GCL tokens are verified against `src/parse.cc`.

**Query primitives (the RISC ISA):**

| Primitive | Token(s) | Meaning / use |
|---|---|---|
| Cover (AND) | `^` / `all_of` | smallest extent containing all operands — the atom of retrieval; a cover **is** a passage `(p,q)`. |
| Alternation (OR) | `+` / `one_of` | synonyms / facet members. The LLM supplies the language knowledge. |
| Proximity / order | `...` / `<>` / `followed_by` | phrases, ordered evidence, sense via nearness. |
| Containment | `>>` / `containing`, `<<` / `contained_in` | restrict covers to a unit (e.g. `:item`), or select units that contain a cover. |
| **Exclusion (the scalpel)** | `!>` / `not_containing`, `!<` / `not_contained_in` | **carve away** a non-relevant cluster the agent has read. No bag-of-words ranker has this. |

Example covers (real syntax):

```
(^ (+ solar photovoltaic "solar panel") (+ subsidy subsidies incentive "tax credit"))   ; facet AND of OR-groups
(<> "climate" "change")                                                                   ; ordered phrase
(>> :item (^ nuclear (+ waste storage repository)))                                       ; items containing the cover
(!> (^ mercury poisoning) (+ planet astronomy orbit))                                     ; carve the astronomy sense away
```

**Meta-instructions (what the compiler needs from the engine):**

- `gcl(expr, offset, limit)` → covers **in corpus / proximity order, not ranked**,
  each with `docid`, the cover text, and a little surrounding context. Must **page
  arbitrarily deep** — the agent is tireless; there is no top-k relevance cutoff to
  respect (this is the central behavioral change from the current `search_gcl`).
- `count(expr)` → number of covers / containing docs — the agent's specificity gauge
  (too many → narrow; too few → broaden). (Exists: `count_matches`.)
- `read(docid, around=cover)` → fuller context to adjudicate relevance and to
  **harvest vocabulary** for expansion. (Exists: `get_document`.)

That is the entire product surface. Everything else is the agent's reasoning.

## 4. The compiler loop

For a question the agent runs optimization passes over the ISA:

1. **Parse intent** into facets / entities / constraints (language reasoning).
2. **Emit** a precise cover — AND of facets, proximity for phrases.
3. **Inspect:** `count`, then read covers **from the top and from deep in the
   enumeration**. Judge each relevant / not / why (with quoted evidence).
4. **Diagnose & reformulate** with a fixed move repertoire:
   - *Recall gap* (too few) → broaden: add `+` synonyms, relax proximity, drop an
     over-constraining facet, or **split into sub-queries** per sub-facet.
   - *Precision gap* (mixed) → narrow: add a facet, tighten proximity/order, or
     **carve** with `!>` / `!<` against the term/pattern characterizing the
     false-positive cluster it just read.
   - *Ambiguity / wrong sense* → disambiguate with proximity or containment.
5. **Iterate** until a query — or a small tier of queries — cleanly isolates relevant
   material.
6. **Harvest by exhaustion:** page deep through a validated query's covers. **Recall
   comes from tireless enumeration, not a ranking cutoff.**

**Read-grounded expansion — and why it is not the CISC expansion we rejected.** When
the agent reads a relevant document and finds vocabulary it did not anticipate, it
folds that term into a `+` clause. This is relevance feedback *from reading actual
results* — what a human searcher does — not an automatic thesaurus or a learned
query-rewriter. It is grounded, auditable, and *authored*. That line is the boundary
between RISC discipline and sliding back into CISC.

**Stopping / coverage.** Stop when new queries stop surfacing new relevant material
(recall saturation across the agent's facet decomposition) or when the compute budget
is hit. The agent estimates coverage from whether its facets are exhausted and whether
deep reads still turn up relevant items. (This maps directly to nugget coverage in the
TREC RAG evaluation.)

## 5. Ranking policy — a research ladder

Ordering the final list is an open research question; we climb a ladder of
increasing reasoning cost, starting affordable. **The engine never produces the
order — the policy does.**

- **Level 0 — query-tier ordering, judgment as tiebreak (the baseline; what we build
  first).** Covers from a precise query outrank covers from a broader one (the
  MultiText compound-query idea, but the *agent* authors the tiers by reading, as
  Clarke did by hand at TREC-4). Within a tier, the agent's light read-judgment breaks
  ties; cheapest sub-tiebreak is proximity (shorter cover first). Chosen for
  **affordability** — minimal reading per result.
- **Level 1 — agent read-judgment as a primary signal (next step).** The agent reads
  and grades more passages and orders by grade. More reading, more cost, plausibly
  higher quality.
- **Level 2 — listwise LLM reranking (further).** The "ZephyrRank" / RankZephyr /
  RankGPT family: feed a *window* of passages to the LLM and have it sort them by
  relative relevance, sliding the window over the candidate set. Set-based relative
  judgments, higher cost again.
- **Level n — and beyond.** Pairwise preference sorting, ensembles of judges,
  judgment with explicit rubrics, etc.

Each rung is a hypothesis to test on the dev data (`docs/trec-rag-2026-design.md`
§eval). We commit only to Level 0 now and treat the rest as a roadmap; the harness
measures whether each added rung's quality gain is worth its cost.

## 6. The output compiler

The agent assembles **one structure that is both TREC RAG task outputs**:

an ordered, docid-deduped list of
`{ docid, cover passage (p,q) + text, the query + read-evidence that justified it, agent grade }`,
ordered by the active ranking policy (§5).

- **Task R** = the docids in that order → `r_output_…tsv` (rank from 1).
- **Task RAG** = answer sentences grounded in those cover passages, cited by docid;
  the ≤125-char quoted-source rule is trivial because covers are short.

So the same compiled artifact drives both submissions.

## 7. What we stop building

To stay RISC: **no** neural re-ranker as part of first-stage; **no** dense /
learned-sparse retrieval; **no** BM25 / cover-density / `icover` as *the ranker*
(their ranking role is gone — BM25 survives only as an external baseline to beat,
`docs/trec-rag-2026-design.md`); **no** keyword→Boolean translator; **no** recall
fallbacks. In Cottontail terms this is mostly **deletion and simplification**.

(Levels 1–2 of §5 reintroduce LLM-driven reranking *deliberately and measured* — that
is the agent reasoning over read passages, not a trained CISC score, and it is gated
by the harness.)

## 8. Cottontail mapping

The engine is already a GCL machine; the work is exposure and simplification, not new
ranking.

The book's machinery (`docs/cover-density-ranking-from-book.md`) maps one-to-one onto
the engine — same author, same algebra. The inverted-index ADT
`next`/`prev`/`first`/`last` (book §1, Table 2.4) **is** the hopper (`tau`/`uat`), and
the book's `nextCover` (Fig 2.10: `v ← max next(t_i); u ← min prev(t_i, v+1)`) **is**
`Combinational::tau_` for `And` (`*p = L(*q = R(k))`, with `And::R_ = max`,
`And::L_ = min`; `src/gcl.cc:34,62-64`). So `(^ …)` computes the book's covers
exactly — what follows is exposure, not new code.

- **`gcl(expr, offset, limit)`** — extend the existing `search_gcl`
  (`apps/jsonl_core.cc`, `apps/cottontail-jsonl-server.cc`) to (a) return covers in
  **corpus/proximity order, not ranked**, (b) **page deep** via `offset`/`limit`, and
  (c) include the cover text + a context window per hit. Covers come straight from the
  `And` hopper's `tau` (`src/gcl.cc:34`, `(^ …)`); no ranker involved.
- **`count(expr)`** — already `count_matches` (`jsonl_core` / `jsonl_json`).
- **`read(docid, around=cover)`** — already `get_document`; add an option to center on
  a cover span and return surrounding context.
- **Carving** uses `!>` / `!<`, already parsed (`src/parse.cc:33-36`) and implemented
  (`NotContaining` / `NotContainedIn`, `src/gcl.h:137,154`).
- **Lift the ranker out of the agent path:** `jsonl_query`'s `icover`/`ssr` ranking
  (`apps/jsonl_core.cc`) is no longer the agent's tool. It remains available only to
  produce the CISC baselines (`docs/trec-rag-2026-design.md`).
- **The agent** (`examples/agent/search_agent.py`) is re-centered: its tools become
  the ISA above; its system prompt becomes the compiler loop (§4) and the active
  ranking policy (§5); its output is the compiled list (§6). The HTTP server
  (`apps/cottontail-jsonl-server.cc`) serves the ISA endpoints.

Net: most of the prior CISC plumbing is removed from the hot path; the GCL algebra
that was always there becomes the product.

## 9. Risks, honestly — and why the bet is reasonable now

- **Cost / latency.** Many LLM calls per topic. Mitigation: it is a *compiler* — once
  a query is validated precise, it trusts it without reading every hit; reading budget
  is spent only where a query is impure. Tireless ≠ infinite; the loop is
  budget-aware, and Level 0 ranking keeps reading minimal.
- **Recall ceiling of pure Boolean.** Real, but mitigated by what a 2026 LLM brings:
  language reasoning for synonyms/senses up front, and read-grounded expansion (§4)
  that discovers corpus vocabulary the query missed.
- **Judgment is a proxy.** The agent judging relevance is approximate — but it reasons
  over *actual passages*, and it is the same capability TREC now trusts (UMBRELA is an
  LLM judge). Require quoted evidence so judgments are auditable.
- **Reproducibility.** Log every query, read, and judgment. This is the audit trail,
  the paper's method section, and the debugging surface in one.
- **Upside that justifies it:** exactness (no idf / length-norm / train-test-mismatch
  failure modes), the `!>` scalpel, tireless depth, and — competitively — doing the
  thing only *this engine + an LLM* can do, rather than re-running the neural-IR
  playbook every other group will submit. Matching the field cannot win; this can.

## 10. How we prove it

Use the dev-data fitness function (`docs/trec-rag-2026-design.md` §eval: UMBRELA qrels,
nuggets, research rubrics). The "system under test" is now the **agent's
query-writing + ranking policy** (its prompt, move repertoire, budget, stopping rule,
and §5 rung), not ranker hyperparameters. Run **head-to-head against a plain BM25
baseline and a cover-density baseline** — that comparison is exactly the
"Boolean-as-a-tool-for-an-LLM beats BM25/dense" claim, tested with significance and
across the three UMBRELA judges.
