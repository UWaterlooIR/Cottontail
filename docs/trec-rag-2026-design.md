# TREC RAG 2026 — Cottontail track integration, baselines, and evaluation

**Status:** proposed / draft. Track dates and several specifics are still TBD
(monitor https://trec-rag.github.io/). Not yet an approved implementation task list.

**The primary system is the RISC agentic-GCL searcher specified in
`docs/agentic-gcl-search-spec.md`** — an LLM that compiles Boolean covers, reads
results, judges relevance, and compiles a ranked passage list with docids. *This*
document owns the track-facing concerns: corpus/task facts and output formats, docid
parity, the **CISC baselines we aim to beat**, the dev-data evaluation harness, and
the build plan.

## 1. Goal and thesis

Win the TREC 2026 RAG track (Retrieval task **R** and RAG task **RAG**) over the
**ClimbMix** corpus.

**Thesis (RISC):** *relevance-by-reading replaces relevance-by-scoring.* The engine
localizes (enumerate Boolean covers precisely); a tireless, language-fluent agent
adjudicates (read, judge, reformulate with set-algebra precision) and compiles the
ranked list. We are betting — Charlie's "grep is all you need" — that Boolean covers
with proximity, **used as a tool by an LLM in a loop**, can rival or beat BM25 and
dense retrieval. Full method: `docs/agentic-gcl-search-spec.md`.

This reframes the earlier plan: the lexical-fusion + neural-re-rank pipeline is no
longer our system — it is the **baseline we measure against** (§6). The neural
re-ranker, dense/learned-sparse arms, and ranker hyperparameter tuning are off the
critical path.

## 2. Track facts that constrain the design

- **Corpus:** ClimbMix, Pyserini index name `climbmix-400b` (~400B tokens). The same
  corpus this repo indexes (`scripts/build-climbmix-burrow.sh`; the
  `/share/.../climbmix-…utf8-porter.burrow` builds). Replaces 2025's MS MARCO V2.1.
- **Two tasks** (the 2025 "AG-only" task is discontinued — do **not** submit AG):
  - **Retrieval (R):** ranked ClimbMix docids. `r_output_trec_rag_2026.tsv`, six
    whitespace columns `topic_id Q0 docid rank score run_id`; rank restarts at 1 per
    topic; scores non-increasing; **ClimbMix docids only**; participant-chosen depth.
  - **RAG:** retrieve evidence *and* return a grounded, cited answer.
    `rag_output_trec_rag_2026.jsonl` (schema §7).
- **Topics** (`trec_rag_2026_queries.jsonl`): `id`, `title` (keyword phrase — default
  query), `narrative` (detailed description — drives query expansion and evidence
  selection). Preserve `id`/`title`/`narrative` in outputs. (Dev topics, §8, carry a
  narrative but **no title** — the agent must handle narrative-only input.)
- **Evaluation:** RAG is judged by **blind system-by-system battles** — randomized
  pairwise comparisons on *usefulness, factual accuracy, coverage, grounding,
  citation validity* — with a **nugget / AutoNuggetizer** diagnostic. R metrics are
  TBD; a deep-research track rewards **diverse, high-recall** coverage of nuggets, not
  single-document precision.
- **Pyserini BM25 is a baseline, not our system.** The track provides a hosted
  Pyserini REST API (base `http://99.251.12.72:8081`;
  `GET /v1/climbmix-400b/search?query=…&hits=N`; `GET /v1/climbmix-400b/doc/{docid}`;
  auth `PYSERINI_API_TOKEN`; response `rank, docid, score, doc`). It exposes only
  `query`/`hits` (no `k1`/`b`), so its BM25 is pinned at defaults (`k1=0.9, b=0.4`) —
  the setting `docs/revisiting-bm25.md` finds worst on long docs. For a *fair, strong*
  baseline we self-host an Anserini index over the official corpus JSONL and tune
  `k1≈10, b≈1` (§6). The hosted API and any self-host both key on the official `id`,
  so either yields canonical docids (parity oracle, §3).
- **External-service note (repo boundary):** the hosted Pyserini API is an external
  host; the token lives in `PYSERINI_API_TOKEN` (never a flag, never logged), and
  calling it needs the usual explicit go-ahead. The self-hosted index is local.

## 3. Docid namespace and parity — the gating risk

**Everything depends on emitting the official ClimbMix docids.** Canonical scheme
(`trec-rag-climbmix-corpus-creation` skill):

```
docid = shard_XXXXX_YYYYY
  XXXXX = zero-padded *Parquet* shard number of karpathy/climbmix-400b-shuffle
  YYYYY = zero-based row number within that shard (when the row has no id field)
```

Hard rule: *do not reshuffle, repartition, deduplicate, filter, or reorder before
assigning docids* — the id is a function of the source Parquet filename + zero-based
row number.

Cottontail emits `shard_XXXXX_YYYYY`-shaped ids and carries the input id to `:docno`
(`apps/jsonl_core.cc`, `add_text(docid) → :docno`). **But matching the *format* is not
matching the *values*.** Parity holds only if (1) the JSONL under
`/share/corpora/climbmix-400b-corpus-jsonl/` carries the official `id` (Parquet
shard/row order preserved), and (2) `cottontail-jsonl-index` keys `:docno` on that
`id`, not on JSONL-local order.

**Verification (do first; cheap; gates the entry):** fetch sampled docids from the
Pyserini API and confirm byte-identical text from our burrow
(`cottontail-jsonl-query --get <docid>`), across low and high shard numbers. Two
token-free oracles also exist: the self-hosted Anserini index (§6) built from the same
corpus JSONL must agree docid→text with the burrow; and **every dev-data qrels docid
(e.g. `shard_02293_61021`, §8) must resolve in our burrow**, or retrieval scores as
all-misses regardless of quality.

## 4. The primary system (RISC) — summary

Full spec: `docs/agentic-gcl-search-spec.md`. In brief, per topic the agent:

1. parses the question into facets/entities/constraints;
2. emits precise GCL covers — `(^ …)` of `(+ …)` facet groups, `<>`/`...` for phrases;
3. **triages** — `count` for breadth, then proximity-ordered `triage` to surface
   candidate documents; reads the top plus a deeper sample and judges relevance with
   quoted evidence;
4. **mines** each confirmed-good document (`mine`, scoped to that docid) for all of its
   relevant covers — for grounding and nugget coverage;
5. **reformulates** to drive recall — broaden (`+`, relax proximity, split sub-queries),
   narrow (add facet, tighten), or **carve** false-positive clusters with `!>` / `!<` —
   folding read-discovered vocabulary into `+` groups (recall comes from better queries,
   not from paging one query deep);
6. compiles a docid-deduped ranked list of `{docid, cover passage, justification,
   grade}` that serves **both** Task R (docids) and Task RAG (grounding).

The engine orders covers by a statistics-free proximity prior — a *reading aid*, not the
verdict; the **submitted** ranking is the agent's, per the policy of §5.

## 5. Ranking policy — a research ladder

Ordering the compiled list is an open research question; we climb a cost ladder and
commit only to the bottom rung now (`agentic-gcl-search-spec.md` §5):

- **Level 0 — query-tier ordering, judgment as tiebreak (baseline; build first).**
  Precise-query covers outrank broad-query covers (agent-authored tiers, the MultiText
  compound-query idea); light read-judgment breaks ties; proximity (shorter cover
  first) is the cheap sub-tiebreak. Chosen for **affordability**.
- **Level 1 — agent read-judgment as a primary signal (next).** Read and grade more;
  order by grade.
- **Level 2 — listwise LLM reranking (further).** The "ZephyrRank" / RankZephyr /
  RankGPT family: feed a window of passages, have the LLM sort them, slide over the
  candidate set.
- **Level n — beyond:** pairwise preference sorting, judge ensembles, rubric-guided
  judgment, etc.

Each rung is a hypothesis measured on the dev data (§8): is the quality gain worth the
cost?

## 6. Baselines to beat (the demoted CISC pipeline)

These are comparison points, **not our submission**. We build them to (a) calibrate
the RISC agent on the dev data and (b) report head-to-head in the TREC paper.

- **BM25 (self-hosted Anserini, tuned).** Index the official ClimbMix corpus JSONL;
  BM25 at `k1≈10, b≈1`. Official docids by construction; also a parity oracle (§3).
  The hosted Pyserini API (default params) is the *as-provided* baseline.
- **Cover density — the book's pure `rankProximity`.** Büttcher/Clarke/Cormack §2.2.2,
  Eq 2.15: `score(d) = Σ 1/(v−u+1)` summed over a document's covers — statistics-free,
  no `K`, no idf (`docs/cover-density-ranking-from-book.md`). This is the faithful
  "what does cover density alone get?" baseline, and it is **distinct from both**
  rankers already in the tree: `icover` (`src/ranking.cc:389`; idf-weighted, keeps the
  best cover) and `ssr` (smoothed `1/(K+q−p)`, `K=42`). It is a ~30-line loop over the
  existing `And`-cover iteration (`nextCover` ↔ `(^ …)`). Report the book's pure form
  as the honest baseline (and `icover`/`ssr` too, if cheap).
- **(Optional) the full CISC pipeline** — RRF fusion of BM25 + `icover` + GCL-facet
  `tiered`, then a monoT5-3B re-rank on cover passages — i.e. the deep-research
  paper's recipe (`docs/revisiting-bm25.md`). Build only if we want to show the RISC
  agent beats a *strong* conventional system, not just a plain one. Not on the
  critical path.

If the RISC agent cannot beat tuned BM25 and `icover` on the dev qrels, that is the
signal to revisit the thesis — which is exactly why these baselines exist.

## 7. RAG task — agentic grounded generation

The agent (`examples/agent/search_agent.py`) + HTTP server
(`apps/cottontail-jsonl-server.cc`) generate the answer from the **compiled passage
list** of §4. Output schema (`rag_output_trec_rag_2026.jsonl`, one object per topic):

```jsonc
{
  "team_id": "...", "run_id": "...", "type": "automatic" | "manual",
  "narrative_id": "<topic id>", "title": "...", "narrative": "...",
  "prompt": "...(optional)...",
  "references": ["shard_00459_61697", "..."],     // cited ClimbMix docids ONLY
  "answer": [
    { "text": "A grounded sentence.", "citations": [0, 2] },  // 0-indexed into references
    ...
  ]
}
```

Rules: every sentence cites ≥1 doc; every citation indexes a valid `references`
position; every `references` entry is cited ≥1; no uncited references; no unsupported
claims; ≤125 characters of quoted source per item.

Pipeline:

1. **Evidence = the compiled list (§4).** The covers the agent already validated and
   read *are* the grounding; no separate retrieval pass.
2. **Synthesize cited sentences**, each grounded in a specific cover passage; quotes
   ≤125 chars (covers are short).
3. **Validation + grounding pass (pre-submission):** enforce the schema rules and
   verify each cited passage entails its sentence (lightweight NLI / LLM check); drop
   or repair weak citations; recompute `references` as exactly the cited set. Maximizes
   *grounding* and *citation validity*; guards *factual accuracy* against over-claiming.
4. **Coverage self-check:** "does every facet of the narrative get a grounded
   sentence?" Revise before emit — *coverage* is a battle axis and the nugget
   diagnostic. Order each sentence's citations strongest-first.

## 8. Dev-data fitness function and experimentation loop

The track ships a **development set with an automatic, multi-signal fitness function**
(`trec-rag-data/.../development-data`), so we can decompose the thesis into testable
sub-hypotheses and let an agent validate/refute each.

**The fitness function:**

- **Topics.** `topics/rag25-topics-dev.tsv` — **24** RAG topics (`id <TAB> narrative`;
  no title). `topics/research-rubrics-topics-dev.tsv` — a separate rubric-graded set.
- **Retrieval gold — UMBRELA qrels.**
  `rag25-dev-umbrela-qrels/rag25-climbmix-umbrela-{codex-gpt5.5, ministral-3-14b, qwen3.5-9b}.qrels`:
  TREC `topicid 0 docid grade`, graded **0–4**, official `shard_*` docids. **Three
  independent LLM judges** — require agreement, never optimize to one → `trec_eval`
  nDCG@10/@20, Recall@100, MAP.
- **Answer coverage — nuggets.** `rag25-dev-nuggets/rag25-dev-nuggets.jsonl`: per
  `qid`, `{text, mapped_sub_narrative, importance: vital|okay, source}` → vital-weighted
  nugget recall (entailment: does the answer assert each nugget?).
- **Answer quality — research rubrics.**
  `researchrubrics-dev-rubrics/research-rubrics-dev-rubrics.jsonl`: per `qid`,
  `{domain, …, rubrics:[{criterion, weight (±), axis}]}` → weighted rubric score
  (LLM judges each criterion; negative weights penalize).

**The dev set is tiny (24 topics; ≈7–9 with nuggets), so the loop must not overfit:**

- **Significance, not deltas** — accept a change only if a paired
  bootstrap/randomization test is significant **and** holds across all three UMBRELA
  judges.
- **Held-out split / k-fold**; report held-out.
- **Prior-plausibility weighting** — prefer mechanistic, spec-grounded changes; an
  unexplained dev win is an overfitting smell.
- **Goodhart guard** — the gold is itself LLM-generated and the real eval is *human*
  battles; cross-judge agreement narrows but does not close the gap. Hard-gate
  acceptance on significance + plausibility; do not squeeze the last 0.005.
- **Cost-aware** — optimize metric-per-cost.

**The loop** (substrate → agent cycle → search): a typed config of the agent's policy
(prompt, move repertoire, budget, stopping rule, §5 rung); content-hash caching of
queries/reads/judge-calls so iteration is cheap and reproducible (temperature 0);
an append-only ledger. A controller agent proposes a structured hypothesis
(`claim, rationale, config delta, predicted metric, cost`), realizes it (usually a
prompt/policy delta; sometimes a code change), runs it on dev, scores it on all three
signals across all three judges with k-fold, significance-tests vs the best, updates
the frontier, and repeats under budget. Strategy: one-factor ablations → coordinate
ascent → successive halving. **The system under test is the agent's query-writing +
ranking policy, not ranker hyperparameters.** Head-to-head against the §6 baselines is
the core experiment: does Boolean-as-an-LLM-tool beat BM25 and cover-density?

## 9. Build plan (prioritized)

RISC-first; most is simplification + orchestration around existing components.

- **P0 — Docid parity check (§3).** Gates everything.
- **P0 — Expose the RISC ISA** (`agentic-gcl-search-spec.md` §8): make `search_gcl`
  return covers in corpus/proximity order, page deep (`offset`/`limit`), and include
  cover text + context; confirm `count_matches` and `get_document` suffice for the
  rest. Lift `icover`/`ssr` ranking out of the agent path.
- **P0 — The compiler-loop agent** (`examples/agent/`): re-center tools on the ISA;
  system prompt = the compiler loop (§4) + Level-0 ranking (§5); output = the compiled
  list (§6).
- **P1 — Dev-data eval harness (§8):** `trec_eval` over UMBRELA qrels + nugget recall
  + rubric scorer; the ledger. Stand up early; it gates every policy choice.
- **P1 — Baselines (§6):** a self-hosted tuned-BM25 index and a book cover-density
  (`rankProximity`, Eq 2.15) run, scored on the same harness for head-to-head.
- **P1 — RAG formatter + validator (§7):** emit exact `rag_output…jsonl`; enforce
  schema; NLI grounding pass.
- **P2 — Ranking ladder rungs (§5):** Level 1 (read-judgment), then Level 2 (listwise
  LLM rerank), each added only if the harness says the gain beats the cost.
- **P3 (optional) — the full CISC pipeline (§6)** as a strong baseline, if we want to
  show the agent beats a fusion+re-rank system and not just a plain one.

## 10. Risks, open questions, immediate actions

- **Docid parity (highest).** All-misses if `:docno` keys on JSONL-local order. Verify
  per §3 first.
- **RISC cost / latency.** Many LLM calls per topic; mitigated by compiler-style budget
  allocation and Level-0 ranking (`agentic-gcl-search-spec.md` §9).
- **Recall ceiling of pure Boolean.** Mitigated by LLM language reasoning +
  read-grounded expansion; the §6 baselines tell us if we are leaving recall on the
  table.
- **Goodhart on LLM-judged dev gold (§8).** Hard-gate on significance + cross-judge
  robustness + plausibility.
- **Open:** hosted Pyserini API paging/rate limits (only matters for the as-provided
  baseline); R-task metric (assume recall/nugget-weighted); compute for any §5 Level-2
  reranker; timeline (topics/deadline TBD — build + tune on dev now).

**Immediate actions:** (1) verify docid parity (§3); (2) expose the RISC ISA + stand up
the compiler-loop agent (§4, §9); (3) stand up the dev-data harness (§8); (4) build the
tuned-BM25 and book-cover-density baselines (§6) for head-to-head.
