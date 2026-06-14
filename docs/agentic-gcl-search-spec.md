# Agentic GCL search — a RISC instruction set for retrieval

**Status:** proposed / draft, **prepared for Charlie & Mark to review.** This is the
**primary-system** spec for the Cottontail TREC RAG 2026 entry. Track integration, the
CISC baselines we aim to beat, and the evaluation harness live in
`docs/trec-rag-2026-design.md`. Not yet an approved implementation task list. Open
questions are marked **⚑ For Charlie / Mark** inline and collected at the end. This
revision folds in Charlie's first feedback round and the original TREC-4 queries
(`apps/trec4.queries`, upstream repo).

## 1. Thesis

**Relevance-by-reading replaces relevance-by-scoring.**

Every CISC retrieval instruction — BM25, cover-density ranking, a learned
cross-encoder — is a complex one-shot heuristic that *bakes a guess about relevance
into a score* so that a human, or a dumb pipeline, gets a usable ranked list without
having to think. A tireless, language-fluent agent does not need that crutch. Give it
a *reduced* instruction set — exact Boolean covers with proximity — and let it do
directly what the score was only approximating: **read the material and judge it.**

- **The engine's job collapses to localization:** enumerate covers precisely
  (Boolean set-algebra + proximity).
- **The agent's job is adjudication:** read covers, judge relevance, and reformulate
  the query — with set-algebra precision — until a small set of queries isolates the
  relevant material.

The punchline for us: **Cottontail is already a RISC machine.** GCL is the reduced
instruction set; the engine has been computing Boolean covers since Clarke's algebra.
We have simply been hiding it under whole-pipeline ranking. The move is to expose the
algebra directly to an LLM "compiler."

This is grounded in the canonical source — Büttcher, Clarke & Cormack, *Information
Retrieval: Implementing and Evaluating Search Engines* (MIT Press, 2010), §2.2.2
(`docs/cover-density-ranking-from-book.md`). The chapter splits along the RISC/CISC
line — with one refinement we reached in design discussion. Cover **finding**
(§7.1–7.2, `nextCover`) is the precise, statistics-free localizer we **keep**. Cover
**scoring** (§7.3, `score = Σ 1/(v−u+1)`) we **demote, not delete**: we drop it as the
*final relevance verdict* (the agent adjudicates that), but **keep it as a cheap
traversal/triage order**. It is statistics-free proximity — the book's "shorter cover →
more likely relevant" assumption — and it is what lets the agent spend its limited
reading budget on the most promising covers first. *Keep the book's cover machinery;
demote its cover score from a verdict to a reading order.*

> **⚑ For Charlie / Mark:** the whole design hinges on this split — proximity scoring as
> a *where-to-read-first* aid, with the *final* relevance call and the submitted ranking
> coming from the agent's reading. Does that division match your intuition? Or is a good
> proximity order, in practice, trustworthy enough to simply *be* the answer for most
> short queries — so the agent should only intervene on the hard ones rather than
> re-adjudicate everything?

## 2. RISC vs. CISC

- **CISC instruction** (BM25 / cover-density ranking / cross-encoder): one call that
  encodes a complex relevance heuristic, tuned so a human or simple caller gets a good
  ranked list in one shot. Designed for *direct* use. Opaque, hard to redirect, and it
  carries failure modes — idf quirks, document-length normalization, neural
  train/inference query mismatch (see `docs/revisiting-bm25.md`).
- **RISC instruction** (a GCL cover): a simple, exact set-algebra primitive. Tedious
  for a human to wield at scale, but a *compiler* can sequence many of them, with
  feedback, to reach precision and recall the one-shot CISC instruction cannot.
- **The compiler is the LLM agent.** It sees the whole program (the question), emits
  RISC instructions (GCL queries), inspects intermediate results (reads covers), and
  optimizes (reformulates) — tirelessly.

Historical rhyme: at TREC-4, Clarke hand-wrote Boolean queries **zero-shot** — no
interactive search, results never inspected, the full index built only the day before
submission — and they did well (`docs/multitext.md`; the queries survive at
`apps/trec4.queries`). The bottleneck was human effort and skill, and the LLM removes
it. The bet — Charlie's "grep is all you need" — is that Boolean covers with proximity,
**used as a tool by an LLM in a loop**, can rival or beat BM25 and dense retrieval.

**Why an agent can wield RISC where a blind author could not: interactivity.** A
zero-shot author needs forgiving, robust instruments — which is exactly why CISC ranking
and recall fallbacks exist, and why the TREC-4 queries used **no `NOT`** (excluding
material you cannot see is dangerous). An agent that *reads results and judges them* can
instead use sharp, brittle, *precise* instruments — tight covers, proximity, and
exclusion (`!>`) — and **repair its mistakes by reading**. Seeing results is what makes
the precision tools safe. So the agent's edge over the 1997 human is not only
tirelessness; interactivity *licenses the whole RISC approach*, and the agent should be
**more** willing than the blind author to use exclusion and tight constraints, not less.

From the TREC-4 queries we therefore transfer the **structure** — facets joined by `^`,
each an `+`-group of variants, composed into a compound list of subqueries ordered
precise→broad (§5) — but **not** the zero-shot tactics (the `NOT`-avoidance was a
blind-authoring mitigation, lifted by interactivity). This spec is deliberately the
**pure** idea: Boolean covers from the book, authored by the LLM. We do **not** add the
keyword→Boolean auto-generators or recall fallbacks from later variations — those existed
only because there was no good query author in the loop, and they make "better" ambiguous
(better generator? better fallback?). There is a good author now.

## 3. The instruction set (ISA)

Two orthogonal axes shape what a query returns: **granularity** (documents vs. covers)
and **order** (proximity vs. corpus). GCL tokens below are verified against
`src/parse.cc`.

**Query primitives (the RISC ISA):**

| Primitive | Token(s) | Meaning / use |
|---|---|---|
| Cover (AND) | `^` / `all_of` | smallest extent containing all operands — the atom of retrieval; a cover **is** a passage `(p,q)`. |
| Alternation (OR) | `+` / `one_of` | synonyms / facet members. The LLM supplies the language knowledge. |
| Proximity / order | `...` / `<>` / `followed_by` | phrases, ordered evidence, sense via nearness. |
| Containment | `>>` / `containing`, `<<` / `contained_in` | restrict covers to a unit (e.g. `:item`), or select units that contain a cover. |
| **Exclusion (the scalpel)** | `!>` / `not_containing`, `!<` / `not_contained_in` | **carve away** a non-relevant cluster the agent has read. No bag-of-words ranker has this. |

**The agent's tools — triage, mine, read, count:**

1. **`triage(expr, k)` — document level, proximity-ordered.** Run the GCL expression
   and return the matching *documents* ranked by a statistics-free proximity score,
   each with its docid and a representative cover passage. Answers "which documents are
   worth my attention?" With a generous `k` it returns the **full** matching set
   (deduplicated to one entry per document — nothing is hidden; long documents simply
   appear once via their best passage). This is essentially the existing `ssr` GCL path.
2. **`mine(docid, expr)` — cover level, proximity-ordered, scoped to one document.**
   Enumerate *all* covers of the expression within a chosen document, tightest first,
   each with its span and text. Answers "this document is good — give me all of its
   relevant passages." This is the cover-level granularity `triage` cannot provide
   (triage collapses each document to one passage). It is **cheap and bounded** — one
   document has few covers — so it does not reintroduce deep-paging cost. In GCL it is
   the solutions of `(<< (^ …) (>> :item (>> :docno "<docid>")))`.
3. **`read(docid, around=span?)`** — full document text, or a window around a span.
   Complements `mine`: `mine` returns query-matching passages; `read` lets the agent
   find relevant material the query did not phrase for (then `mine` again with an
   expanded, doc-scoped query).
4. **`count(expr)`** — number of matching documents (and/or covers) — the breadth gauge
   for deciding to narrow or broaden.

**Returned passage — a window around the cover (Charlie's rule).** Scoring/ordering is
done on the *raw* cover; the returned text is a readable window. Given a window size `W`:
if the cover is at least `W` long, return the cover unchanged (never shrink a large
cover); otherwise widen the cover **symmetrically** out to `W`, clamped at document
bounds. This applies to `triage`'s representative passage and to every cover from `mine`,
and it is what the ≤125-char RAG quote (§6) is drawn from. The window is presentation
only — it does not affect the score.

Order is **proximity by default** on both `triage` and `mine` — shorter/tighter covers
first (the triage aid of §1). Cottontail's existing `ssr` already embodies this idea; the
*exact* ordering function (e.g. `ssr`'s `1/(K+q−p)` vs. a pure inverse cover length, and
document-level summed vs. best-cover) is a **tuning detail for the harness, not a decreed
choice** — default to `ssr` as-is (see the callout). **Corpus (positional) order, and
corpus-wide cover enumeration, are shelved** (§7): triage is better served at the
document level (positional enumeration would let one dense document flood the list), and
recall is served by reformulation (§4), not by paging the tail of one broad query.
Document-scoped cover enumeration (`mine`) is the *only* cover-level enumeration we keep,
and it is cheap because it is bounded to one document.

> **⚑ For Charlie / Mark:** the *idea* — tighter covers first — is settled, and `ssr`
> embodies it; we treat the exact ordering function as a tuning detail (default: `ssr`
> as-is, *not* a decreed pure `1/len`). Any strong prior worth pinning — does `ssr`'s `K`
> matter for *ordering* (vs. absolute scores) on long web text, and should a document's
> `triage` rank use its **best** cover or its **summed** covers (book assumption 2)? Fine
> to leave to the harness if you have no strong view.

> **⚑ For Charlie / Mark (ISA gap):** the TREC-4 queries lean on a hard proximity-width
> operator `< [n]` — e.g. `(("nuclear" + "atomic") ^ ("plant" + "plants" + "power")) < [5]`
> — but Cottontail's GCL has **no width operator** (only `<>`/`followed_by` and
> containment). Do we **add a `< [n]` width operator** to the ISA, or rely on
> **cover-length ordering** as the soft substitute (tight covers float to the top without
> a hard cap)? A hard cap buys precision and a smaller candidate set on broad queries; the
> soft version is what the windowing rule above already implies. This is the one concrete
> ISA gap we found against TREC-4.

## 4. The compiler loop

For a question, the agent runs optimization passes over the ISA. The shape is
**triage → mine → reformulate**, repeated:

1. **Parse intent** into facets / entities / constraints.
2. **Emit** a precise cover — `(^ …)` of `(+ …)` facet groups, `<>`/`...` for phrases.
3. **Triage:** `count` for breadth, then `triage(expr, k)`; read the top documents'
   passages plus a deeper sample. Judge relevant / not / why, with quoted evidence.
4. **Mine the winners:** for each good document, `mine(docid, expr)` (and `read` it) to
   pull out *every* relevant passage — for grounding multiple answer sentences and
   covering distinct nuggets.
5. **Reformulate** with a fixed move repertoire:
   - *Precision gap* (mixed triage) → narrow: add a facet, tighten proximity, or
     **carve** with `!>` / `!<` against the false-positive cluster just read — then
     **verify the carve** by reading a sample of what it *removed*, to confirm it did not
     drop relevant material (the safety step a zero-shot author cannot do).
   - *Recall gap* → broaden: add `+` synonyms (including vocabulary discovered while
     reading), relax proximity, drop an over-constraining facet, or split into
     sub-queries per sub-facet.
   - *Ambiguity* → disambiguate with proximity or containment.
6. **Iterate** until a small set of validated queries cleanly isolates the relevant
   material.

**Carving is safe here — that is the point.** The TREC-4 queries used no `NOT`: excluding
material you cannot see is dangerous zero-shot. The agent reads what it excludes, so
exclusion (`!>` / `!<`) becomes a **first-class** precision tool rather than a hazard —
used freely, with the carve-and-verify read-back above. Expect the agent to narrow and
exclude *more* aggressively than a blind author would, not less.

**Recall comes from reformulation, not from exhaustion.** The recall move is to *vary
the query* — narrow, carve, expand from read vocabulary, split facets — not to page a
single broad query to its tail (whose low-proximity tail is exactly the least relevant
material, and whose deep enumeration is the most expensive thing the engine can do).
"Harvest" means *exhaust the space of good queries*, not enumerate one query forever.
Within a confirmed-good document, `mine` then exhaustively pulls the passages — that is
the only place exhaustion is both cheap and worthwhile.

**Read-grounded expansion — and why it is not the CISC expansion we rejected.** When
the agent reads a relevant document and finds vocabulary it did not anticipate, it folds
that term into a `+` group. This is relevance feedback *from reading actual results* —
what a human searcher does — not an automatic thesaurus or a learned query-rewriter. It
is grounded, auditable, and *authored*. That line is the boundary between RISC
discipline and sliding back into CISC.

**Stopping / coverage.** Stop when new queries stop surfacing new relevant documents
(recall saturation across the facet decomposition) or at the compute budget. This maps
directly to nugget coverage in the evaluation.

> **⚑ For Charlie / Mark:** **(a)** do you agree recall is best driven by *reformulation*
> (narrow / vary / carve / expand) rather than exhaustive deep enumeration — and is there
> a regime (known-item, or legal-style high-recall) where you'd want an exhaustive
> corpus-wide cover sweep back in the toolkit? **(b)** We read the absence of `NOT` in the
> TREC-4 queries as a *zero-shot* precaution, now lifted by interactive judging — so the
> agent should use `!>` / `!<` freely, with a carve-and-verify read-back. Any residual
> cautions, or carve idioms you trust (exclusion vs. proximity/containment to kill a bad
> sense)?

## 5. Ranking policy — a research ladder

**First, a guardrail, because two orderings must not be confused.** The **triage
order** (§3, proximity) decides *where the agent reads first* — it is an aid, not a
verdict. The **ranking policy** below decides *what we submit*, and it is the agent's,
built from reading. The failure mode to avoid is letting the triage order's top-k
silently become the submitted run with the LLM rubber-stamping it — that quietly
rebuilds a conventional ranked-retrieval system with an agent decoration on top. Triage
orders where to look; the policy orders what we return.

Ordering the submitted list is an open research question; we climb a cost ladder and
commit only to the bottom rung now:

- **Level 0 — query-tier ordering, judgment as tiebreak (build first).** The agent
  authors a **compound, ordered list of subqueries** per topic, precise→broad — exactly
  the TREC-4 form (`@rank q0 q1 … qN`, where `q0` is the all-facets `^` of `+`-groups, and
  later entries are weaker alternatives and bare-term fallbacks; facets are named
  `+`-groups, e.g. `USbroad = US0 + US1 + US2 + US`). Results fill tier by tier: a precise
  subquery's hits outrank a broader one's; the agent's light read-judgment breaks ties;
  tightest-cover-first is the cheap sub-tiebreak. Chosen for **affordability** — and it is
  the structure Charlie's blind TREC-4 runs already validated.
- **Level 1 — agent read-judgment as the primary signal.** The agent reads and grades
  more passages and orders by grade. More reading, more cost, plausibly higher quality.
- **Level 2 — listwise LLM reranking.** The "ZephyrRank" / RankZephyr / RankGPT family:
  feed a window of passages to the LLM, have it sort them, slide over the candidate set.
- **Level n — beyond:** pairwise preference sorting, judge ensembles, rubric-guided
  judgment, etc.

Each rung is a hypothesis measured on the dev data (§10): is the quality gain worth the
cost?

> **⚑ For Charlie / Mark:** Level 0 mirrors the TREC-4 `@rank` compound list
> (precise→broad). Confirming details: when several subqueries hit a document, it keeps
> its **most-precise** tier (we assume yes); within a tier, order by read-judgment then
> cover-tightness, or did the TREC-4 runs order within a subquery purely by cover density?
> And should the agent **author the whole ordered list up front** (as you did), **grow it
> interactively** as it reads, or both?

## 6. The output compiler

The agent assembles **one structure that is both TREC RAG task outputs**: a
docid-deduplicated list of
`{ docid, the mined cover passage(s) + windowed text, the query + read-evidence that justified it, agent grade }`,
ordered by the active ranking policy (§5). `mine` populates the per-document passages
(windowed per §3).

- **Task R** = the docids in that order → `r_output_…tsv` (rank from 1).
- **Task RAG** = answer sentences grounded in those mined cover passages, cited by
  docid; the ≤125-char quoted-source rule is trivial because covers (and their windows)
  are short.

So the same compiled artifact drives both submissions.

## 7. What we keep and what we drop

**Kept in the agent's hot path:** GCL cover finding; the statistics-free proximity order
as the **triage aid** (§3); document-scoped cover **mining**; `read`; `count`; the
`!>` / `!<` carve operators (now first-class, §4).

**Dropped from the agent's hot path:** proximity/`ssr`/`icover`/BM25 as the **final,
submitted ranker** — the agent's reading is the verdict; these survive only as
**baselines** (`docs/trec-rag-2026-design.md` §6). Also dropped: **corpus-order and
corpus-wide cover enumeration** (triage is better at document level; recall is
reformulation, §4); a neural re-ranker as first-stage; dense / learned-sparse retrieval;
any keyword→Boolean auto-translator; recall fallbacks. (Levels 1–2 of §5 reintroduce
LLM reranking *deliberately and measured* — that is the agent reasoning over read
passages, gated by the harness, not a trained CISC score.)

Net, in Cottontail terms: the genuinely new engine capability is **document-scoped
cover mining** (cheap), plus exposing **`triage`** (≈ the existing `ssr` GCL search) with
a generous depth and the §3 windowed-passage return. No corpus-wide cursor; no new ranker
on the hot path. (A `< [n]` width operator is the one possible addition — open, §3.)

## 8. Cottontail mapping

The engine is already a GCL machine; the work is exposure and a little new code, not new
ranking.

The book's machinery (`docs/cover-density-ranking-from-book.md`) maps one-to-one onto
the engine — same author, same algebra. The inverted-index ADT
`next`/`prev`/`first`/`last` (book §1, Table 2.4) **is** the hopper (`tau`/`uat`), and
the book's `nextCover` (Fig 2.10: `v ← max next(t_i); u ← min prev(t_i, v+1)`) **is**
`Combinational::tau_` for `And` (`*p = L(*q = R(k))`, with `And::R_ = max`,
`And::L_ = min`; `src/gcl.cc:34,62-64`). So `(^ …)` computes the book's covers exactly.

- **`triage`** — the existing `search_gcl` / `ssr` path (`apps/jsonl_core.cc`
  `jsonl_query`; `src/ranking.cc:305` `ssr_ranking`), exposed with a generous/explicit
  `k` and returning docid + a representative passage (windowed per §3) + a little context.
- **`mine(docid, expr)`** — **new**: enumerate the solutions of
  `(<< (^ …) (>> :item (>> :docno "<docid>")))` by iterating the hopper's `tau`, and
  return every cover, proximity-ordered, each with its text windowed per §3. Bounded to
  one document.
- **`read`** — extend `jsonl_get` with an optional window around a span.
- **`count`** — `count_matches` (optionally also a cover count).
- **Carving** uses `!>` / `!<`, already parsed (`src/parse.cc:33-36`) and implemented
  (`NotContaining` / `NotContainedIn`, `src/gcl.h:137,154`).
- **Proximity width (`< [n]`)** — a hard width operator the TREC-4 queries used but GCL
  lacks. If adopted (open question, §3) it is a small new GCL operator; otherwise
  cover-length ordering is the soft substitute. This is the only ISA gap found.
- The ranked **verdict** path (`icover`/`ssr`-as-submitted-ranking) leaves the agent
  surface; `ssr` stays, but as the triage *order*. The ranked rankers plus the book
  `rankProximity` live behind baseline endpoints/flags (design doc §6).
- The agent (`examples/agent/`) re-centers on `triage`/`mine`/`read`/`count`; its prompt
  becomes the compiler loop (§4) and the Level-0 policy (§5). The server
  (`apps/cottontail-jsonl-server.cc`) exposes these tools; `/describe` advertises only
  the ISA; the clone-per-thread pool and auth are unchanged (all requests stateless —
  `mine` is doc-scoped and stateless, no server-side cursor).

## 9. Risks, honestly — and why the bet is reasonable now

- **Cost / latency.** Many LLM calls per topic. Mitigation: it is a *compiler* — once a
  query is validated precise, it trusts it without reading every hit; reading budget is
  spent on triage heads and on mining confirmed-good documents, both bounded. Level-0
  ranking keeps reading minimal.
- **Recall ceiling of pure Boolean.** Real, but mitigated by language reasoning for
  synonyms/senses up front, and read-grounded expansion (§4). The §6/§10 baselines tell
  us if we are leaving recall on the table.
- **Judgment is a proxy.** The agent judging relevance is approximate — but it reasons
  over *actual passages*, and it is the same capability TREC now trusts (UMBRELA is an
  LLM judge). Require quoted evidence so judgments are auditable.
- **Reproducibility.** Log every query, triage, mine, read, and judgment. This is the
  audit trail, the paper's method section, and the debugging surface in one.
- **Upside that justifies it:** exactness (no idf / length-norm / train-test-mismatch
  failure modes), the `!>` scalpel (now safe to use, §4), doc-scoped mining for
  grounding, and — competitively — doing the thing only *this engine + an LLM* can do,
  rather than re-running the neural-IR playbook every other group will submit.

## 10. How we prove it

Use the dev-data fitness function (`docs/trec-rag-2026-design.md` §8: UMBRELA qrels ×3
judges, nuggets, research rubrics). The "system under test" is the **agent's
query-writing + ranking policy** (its prompt, move repertoire, budget, stopping rule,
and §5 rung), not ranker hyperparameters. Run **head-to-head against the §6 baselines**
(tuned BM25, the book's pure `rankProximity`) — that comparison is exactly the
"Boolean-as-a-tool-for-an-LLM beats BM25/dense" claim, tested with significance and
across the three judges.

---

### Open questions for Charlie / Mark

Resolved or refined by Charlie's first round + the TREC-4 queries: the proximity *order*
is a settled idea (`ssr` embodies it; the exact function is a tuning detail, **not** a
decreed pure `1/len`); carve (`!>`/`!<`) is **elevated to first-class** (the TREC-4
`NOT`-avoidance was a zero-shot precaution, lifted by interactive judging); the Level-0
tier model **is** the TREC-4 `@rank` compound list; the returned passage uses Charlie's
window-around-cover rule (§3). Still open:

1. **§1** — Is "proximity = reading order, agent's reading = the verdict" the right
   split, or is a good proximity order trustworthy enough to *be* the answer for most
   short queries (agent intervenes only on the hard ones)?
2. **§3 (ordering)** — Any strong prior on the ordering function (`ssr`'s `K`; best vs.
   summed covers for a document's rank), or leave it to the harness?
3. **§3 (ISA gap)** — Add a hard `< [n]` proximity-width operator to GCL, or rely on
   cover-length ordering as the soft substitute?
4. **§4(a)** — Recall via reformulation, or is there a regime needing an exhaustive
   corpus-wide cover sweep?
5. **§4(b)** — Any residual cautions on free use of carve with carve-and-verify, or carve
   idioms you trust (exclusion vs. proximity/containment)?
6. **§5** — Author the whole precise→broad subquery list up front (TREC-4 style), grow it
   interactively as the agent reads, or both? Confirm "a document keeps its most-precise
   tier."
7. **§6 / §3 (for Mark)** — Default window size `W` for the returned passage, given
   ClimbMix's ~400-word median document (e.g. one ~250-word passage, or smaller)?
