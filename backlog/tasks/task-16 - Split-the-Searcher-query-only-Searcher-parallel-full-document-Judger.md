---
id: TASK-16
title: 'Split the Searcher: query-only Searcher + parallel full-document Judger'
status: To Do
assignee: []
created_date: '2026-06-27 01:53'
updated_date: '2026-06-27 15:13'
labels:
  - python
  - isj
  - searcher
  - judger
dependencies: []
references:
  - isj/isj_agent/agents/searcher.py
  - isj/isj_agent/agents/searcher.md
  - isj/isj_agent/agents/analyst.py
  - isj/isj_agent/orchestrator.py
  - isj/isj_agent/protocol/search.py
  - isj/isj_agent/protocol/results.py
  - isj/isj_agent/engine/base.py
  - isj/isj_agent/engine/fake.py
  - isj/isj_agent/run_output.py
  - isj/README.md
  - docs/searcher-agent-lessons-June-16-2026.md
  - docs/judger-agent-research-notes.md
  - isj/runs/croup
priority: high
ordinal: 30000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

Python, in the `isj/` uv project (package `isj_agent`; run `uv sync --project isj` after
dependency changes). NO C++ changes — the C++ engine/server, the `SearchEngine` Protocol,
and `FakeEngine` are reused as-is. Automated tests use a STUB LLM + the B1 `FakeEngine`
(which already implements `read(cp)` and applies `exclude`) — no network, no real model.

Touched/new files:
- NEW `isj_agent/agents/judger.py` + `judger.md` — the Judger agent + its UMBRELA prompt.
- NEW `isj_agent/controller.py` — the per-intent search/judge loop (paging + streak + budget).
- REWRITE `isj_agent/agents/searcher.py` + `searcher.md` — a thin GCL query proposer (no judging).
- EDIT `isj_agent/orchestrator.py` — call the controller per intent instead of `Searcher.run`;
  split the run-total `max_judgments` into a per-intent `intent_budget` and pass it down.
- EDIT `isj_agent/protocol/results.py` — keep `SearcherResult`/`RankedEntry` (drop `RankedEntry.grade`
  bound to `0-3`); add trace event types.
- EDIT `isj_agent/protocol/search.py` — replace `Judgement{cp,grade,reason}` (for the removed
  batch judge tool) with `Verdict{reason, grade}` (the Judger's guided output; `reason` BEFORE
  `grade`; `grade: Literal[0,1,2,3]`; cp is controller-side — see the schema under "The prompts").
- EDIT `isj_agent/run_output.py` — extend cp->docno rewriting to the new event shapes.
- EDIT `config.example.toml` + `config.toml` — `[agents.judger]` role + new loop knobs.
- EDIT `isj/README.md` — document the Searcher/Judger split.
- NEW `tests/test_judger.py`, `tests/test_controller.py`; update/retire the combined-searcher tests.

## Why (motivation)

The current `Searcher` (TASK-5.6) is ONE LLM loop that both searches and judges, and it
judges the cover-biased **summary**, not the document. Two problems observed in practice
(see `isj/runs/croup`): the agent judges weakly because it never reads the full document,
and it does not reliably "work down a ranked list" — it judges the top page and reformulates,
leaving the tail of each ranked list unexplored. This task SEPARATES the two responsibilities:

- a **Searcher** whose ONLY job is to author a GCL query, and
- a **Judger** that judges the **full document** behind each result, in **parallel**.

The controller (not the model) owns paging down the ranked list, the stop rules, the judgment
budget, and the trace — consistent with the hard lesson from TASK-5.6 that model behavior is
not portable for control flow.

## Architecture

Per question, the Orchestrator runs the Analyst (unchanged) -> per interpretation, the new
controller. `max_judgments` is the TOTAL judgment budget for the whole RUN, split evenly
across the interpretations: the Orchestrator computes `intent_budget = max_judgments //
num_intents` (>=1) and passes it to each controller (so 1000 judgments over 2 intents = 500
each). Unused budget from an intent that ends early (dry / max_queries) is NOT reallocated.
Per intent the controller drives a single coherent LLM conversation with the
Searcher; the Searcher's one tool is the existing `search` (the `judge` tool is REMOVED — no
new tool is introduced), and the controller fills that tool's RESULT with the judged
SUMMARIES of the query's worked-down ranked list. So the conversation history the Searcher
sees IS its own past queries and what they yielded. Results returned to the Searcher EXCLUDE
documents already judged by a previous query — those are reported only as an aggregate (depth
K; J already judged; X relevant / Y non-relevant) so the same docs are not repeated to it
turn after turn (see "De-duplication" below).

### Searcher (query author) — `agents/searcher.py` + `searcher.md`
- INPUT: one intent (an Analyst interpretation) + the running conversation (its prior
  queries and their judged outcomes).
- TOOLS: the existing `search { query: string }` is its ONLY tool — NO new tool is added; the
  `judge` tool is REMOVED. Tool use is FORCED (`tool_choice` pins `search`) so the Searcher
  ALWAYS issues a query — there is NO decline / finish / no-tool-call path.
- WHAT IT SEES BACK: the `search` tool result is the cover-biased **summaries** of the
  **NEW** docs (those not judged by a previous query), each with its **grade + reason** from
  the Judger, PLUS an **aggregate** for the already-judged docs at those ranks (depth K; J
  already judged; X relevant / Y non-relevant) — the already-judged docs are NOT re-listed.
  The Searcher NEVER receives full document text — full docs go ONLY to the Judger. From the
  Searcher's point of view it simply searches and, next turn, sees those results already judged.
- PROMPT (`searcher.md`, drafted under "The prompts" below): its job is to **devise precise
  boolean (GCL) queries to explore the space of relevant documents** — formulating different, precise covers to find relevant
  material, paying close attention to what the previous queries' judged results revealed
  (which facets/terms surfaced relevant vs. non-relevant material). REUSE the load-bearing GCL
  guidance from the current `searcher.md` (TASK-5.6 /
  `docs/searcher-agent-lessons-June-16-2026.md`), MINUS everything about judging, grades, and
  the `judge` tool. There is NO relevance scale in the Searcher (the 0-3 rubric lives only in
  the Judger).
- It keeps IMMEDIATE error self-correction: a malformed query (EngineError) or a zero-result
  query comes straight back as the next `search` tool result, in-thread, so it reformulates
  right away (same behavior as today's engine_error / dry feedback).

### Judger (parallel, full-document) — `agents/judger.py` + `judger.md`
- INPUT: the intent, and for each **NEW** candidate (NOT judged by any prior query) the
  cover-biased summary (orientation) PLUS the FULL document text (`engine.read(cp)`), truncated
  to `max_doc_chars`. The cp is NOT sent to the model — it is only the controller's handle on
  which document it asked about. Already-judged docs are NEVER re-sent to the Judger.
- OUTPUT: a `Verdict { reason, grade (0-3) }` per candidate — **NO cp**. The controller already
  knows which document each call was for, so it pairs the returned Verdict with that cp itself;
  burdening the model with the cp adds nothing and risks a transposed/hallucinated id. Guided-
  decoded via `Verdict.model_json_schema()` (the same json-schema pattern the Analyst uses), so
  the grade is constrained to the four levels 0-3. **Field order matters: `reason` is declared
  BEFORE `grade`** — under guided JSON decoding the model fills properties in declaration order,
  so the justification is generated before the grade is committed. (`Verdict` replaces the old
  `Judgement{cp,grade,reason}`, which existed only for the now-removed batch `judge` tool; see
  the schema under "The prompts" below.)
- SCALE: the canonical UMBRELA / TREC **0-3** scale (NOT 0-4) — for calibration and direct
  comparability with TREC DL qrels. `judger.md` decomposes the judgment into steps inside ONE
  call (intent -> topical match -> **trust** -> scope -> grade) rather than a single holistic
  leap, and — because ClimbMix is open-web, mixed-quality text — a TRUST step lets low
  credibility (spam, fabrication, promotional filler, contradiction) CAP the grade. The `reason`
  must cite a concrete span/detail, not just assert. No persona ("You are a relevance assessor"
  framing is dropped — topicality + steps carry it).
- ONE LLM call judges ONE document. The Judger runs up to `judge_concurrency` calls
  simultaneously via a `ThreadPoolExecutor`; the draft prompt + schema are under "The prompts".
- REASONING-MODEL serving (both candidate models — gpt-oss-120b, Gemma 4 — reason before
  answering): guided decoding must constrain ONLY the post-thinking / `final`-channel output,
  **never the thinking trace** (constraining the whole completion strangles the decomposition).
  The four-step reasoning happens in the model's thinking; `reason` is only the surfaced
  one-to-three-sentence justification — do NOT add a scratchpad/analysis field. `reasoning_effort`
  (gpt-oss: medium/high) / thinking-mode (Gemma 4) is a quality<->throughput knob (it trades
  against `judge_concurrency`).

### Controller (the per-intent loop) — `controller.py`
Owns paging, the streak stop, the judgment budget, error self-correction routing, and the
trace. Returns the EXISTING `SearcherResult { ranked_list, events, error }` so C2/C3 and the
run-output layout are unchanged.

## The prompts (drafts to embed)

These are the starting drafts for `searcher.md` and `judger.md`. The Searcher's GCL block is
the LOAD-BEARING text from the current `searcher.md` (TASK-5.6 /
`docs/searcher-agent-lessons-June-16-2026.md`) — keep it close to verbatim; the rest is
reframed for query-only exploration. The Judger is an UMBRELA-style full-document assessor on
the canonical UMBRELA / TREC 0-3 scale, with a trust step for open-web (ClimbMix) text.

### `searcher.md` (Searcher — query author)

```
You are a search analyst exploring a large text collection to find every document
relevant to ONE question. You do NOT judge documents — a separate assessor grades them.
Your job is to DEVISE PRECISE BOOLEAN QUERIES that uncover the relevant material.

Write queries in GCL, a Boolean cover language. Use PREFIX form ONLY — never infix,
never the words AND/OR/NOT.
  (^ A B C)  all of A,B,C appear together
  (+ A B C)  any of A,B,C
  "a b c"    the exact phrase
  (!> A B)   an A that does NOT contain B  (carve out a wrong sense of a word)

Three ways to write a term:
  black      a bare word matches EXACTLY — use for proper nouns and the question's
             defining words.
  bear*      a word followed by * matches that word AND its whole family (bear/bears,
             attack/attacked/attacking). Write the FULL ordinary word then * — e.g.
             statistics*, injury* — NEVER a shortened stem. The system expands it.
             Use it for ordinary content words (not proper nouns/defining terms).
  (+ X Y Z)  is for SYNONYMS — distinct words for one concept — NOT inflections of one word.

Build each query as a COVER: one facet per concept, AND-ed with ^. Example for
'Do I need to worry about black bear attacks while hiking in the woods?':
  (^ black bear* attack*)
Broaden a facet by SYNONYM, e.g. (+ attack* maul* encounter*) — never by adding plurals.

Each turn, issue ONE query with the `search` tool. You then see the NEW documents your
query surfaced — each already graded for you (0-3) with a short reason — plus a note of how
many results at those ranks had ALREADY been judged by your earlier queries.

Use what you see to choose the next query:
- Notice which facets/terms produced RELEVANT vs non-relevant documents, and mine the
  language of the relevant passages for sharper terms.
- Aim each new query at relevant material you have NOT yet found — vary the facets, senses,
  and synonyms of the question.
- If a query mostly retreads already-judged documents, it overlaps your earlier queries;
  switch to a different facet or sense.
- If a query returns nothing, or your GCL is malformed, you are told immediately — fix it
  and try again.

Keep devising new, precise queries to cover the question's whole space of relevant documents.
```

### `judger.md` (Judger — UMBRELA-style full-document assessor, 0-3 + trust)

Decomposed (intent -> topical -> trust -> scope -> grade), trust-capped, evidence-anchored, no
persona. The "Return ONLY..." tail is intentionally absent — guided decoding owns the output
format (the per-field rubric/reason guidance lives in the `Verdict` schema below).

```
You are assessing how well a DOCUMENT satisfies the information need behind a search
query, on a 0–3 relevance scale:
  0 — Irrelevant: the document has nothing to do with the query.
  1 — Related: on the query's topic, but does not answer it.
  2 — Partial: some of the answer, but incomplete, unclear, or buried among unrelated material.
  3 — Perfectly relevant: dedicated to the query, with a complete and direct answer.

Reason through these steps before grading:
1. Intent — what would actually satisfy the searcher: the need behind the query, not its
   surface words.
2. Topical match — how well the content the document ACTUALLY contains meets that need
   (coverage, directness, specificity). Grade on substance, never on keyword overlap or
   topical resemblance; a document can repeat the query's terms and answer nothing.
3. Trust — whether the content is credible enough to rely on (watch for spam, fabrication,
   promotional filler, internal contradiction, unsupported claims). Untrustworthy content
   does not satisfy the need however on-topic it appears; let low trust cap the grade.
4. Scope — judge the FULL document text below (it may be truncated). The representative
   passage is cover-biased orientation only; do not let one strong passage lift the grade if
   the rest of the document is thin.

QUESTION / INTENT:
{intent}

REPRESENTATIVE PASSAGE (orientation only — judge the full document, not just this):
{summary}

DOCUMENT:
{document}
```

`{intent}`, `{summary}` (the surfaced cover-biased summary), and `{document}` (the full body
via `engine.read(cp)`, truncated to `max_doc_chars`) are filled by the controller per
candidate; no `cp` appears in the prompt. The `reason`/`grade` are guided-decoded from the
`Verdict` schema (next), which carries the per-field rubric.

### `Verdict` (Judger output schema — `protocol/search.py`)

`reason` BEFORE `grade` (guided decoding fills properties in declaration order, so the
justification is generated before the grade is committed); grade constrained to 0-3.

```python
from typing import Literal
from pydantic import BaseModel, Field

class Verdict(BaseModel):
    reason: str = Field(
        description=(
            "One to three sentences. Name the searcher's intent, how well the document's "
            "ACTUAL content meets it (coverage, directness, specificity), and trust if it "
            "affected the grade. Cite a specific span or concrete detail from the document; "
            "judge on substance, not keyword overlap."
        )
    )
    grade: Literal[0, 1, 2, 3] = Field(
        description=(
            "0 = irrelevant; 1 = related but does not answer; 2 = partial (some answer, "
            "incomplete/unclear/buried); 3 = perfectly relevant (dedicated, complete, direct). "
            "Low trust caps the grade."
        )
    )
```

> Decoder note: this relies on the backend preserving DECLARATION order (vLLM / Outlines
> `guided_json` does). If a layer canonicalizes keys alphabetically, `grade` (g) sorts before
> `reason` (r) and you silently get grade-first again — confirm on the deployed stack. And the
> guided constraint must scope to the model's post-thinking / `final`-channel output only, NOT
> the thinking trace.

## The per-intent loop (pseudocode)

```
def run(intent, intent_budget) -> SearcherResult:   # intent_budget = max_judgments // num_intents
    msgs = [system(searcher.md), user(f"Question: {intent}")]
    judged: dict[int, Verdict] = {}       # GLOBAL: cp -> {grade, reason} judged in ANY prior query
    recorded: list[RankedEntry] = []      # one entry per NEW judgment, across all queries this intent
    events = []
    queries = 0
    while len(recorded) < intent_budget and queries < cfg.max_queries:
        # 1) ask the Searcher for ONE query via its `search` tool (records llm_call + propose).
        #    tool use is FORCED -> the Searcher always issues a query (no decline path).
        m = llm(msgs, tools=[search], tool_choice=force(search)); append assistant(m)
        query = m.tool_calls[0].query; queries += 1

        # 2) descend this query's TRUE ranked list, judging only NEW full docs in parallel,
        #    until a consecutive non-relevant streak or the list goes dry.
        outcome = page_and_judge(query, judged, recorded, events)   # see below

        # 3) feed the outcome back as the tool RESULT -> becomes the Searcher's history
        append tool_result(m.tool_calls[0], outcome)   # malformed/zero-result -> error/empty payload
    else:
        emit("stop", reason="intent_budget" if len(recorded) >= intent_budget else "max_queries")
    return SearcherResult(ranked_list=compile(intent, recorded), events=events)

def page_and_judge(query, judged, recorded, events, intent_budget):
    streak = 0                  # consecutive non-relevant, over the TRUE list in rank order
    seen = set()                # cps consumed in THIS query's descent -> the engine exclude (NOT global judged)
    depth = 0                   # K: ranks descended this query
    again = []                  # prior-judged cps re-encountered this query (count only)
    fresh = []                  # NEW (hit, verdict) judged this query -> returned to the Searcher
    while len(recorded) < intent_budget:
        try:
            # Fetch a LARGE batch (fetch_k). exclude = only what we've consumed THIS query:
            # EMPTY on the first request; on a CONTINUATION it returns the NEXT unseen batch
            # without re-shipping the first. (Every request re-ranks ALL matches regardless --
            # no early termination -- so a big batch keeps the request count low; exclude saves
            # the summary-build + transfer of the prior batch, not the re-rank.) Prior-judged
            # docs are NOT excluded, so they still appear at their ranks and we count them.
            resp = engine.search(query, top_k=cfg.fetch_k, exclude=sorted(seen), window=cfg.window)
        except EngineError as e:                 # malformed query: bounce back to the Searcher
            emit("bounce", kind="engine_error", query=query, message=str(e))
            return {"error": str(e)}             # <- Searcher reformulates immediately
        emit("search", query=query, total=resp.total_matches, returned=len(resp.results), ...)
        if not resp.results:                     # list exhausted / dry
            break
        new_hits = [h for h in resp.results if h.cp not in judged]   # only NEW docs go to the Judger
        docs = [(h.summary, engine.read(h.cp)) for h in new_hits]    # the Judger sees summary + full doc, NOT cp
        verdicts = { h.cp: v for h, v in zip(new_hits, judger.judge(intent, docs)) }  # parallel Verdict{grade,reason}
        # judger.judge returns one Verdict per item IN INPUT ORDER; the MODEL emits NO cp -- the
        # controller pairs each verdict with the cp it asked about (the zip above).
        for h in resp.results:                    # SCAN IN RANK ORDER (new-doc judging finished out of order)
            seen.add(h.cp); depth += 1
            if h.cp in judged:                    # PRIOR judgment: count only -- no re-read, no Judger, no record
                g = judged[h.cp].grade; again.append((h.cp, g)); emit("revisit", cp=h.cp, grade=g)
            else:                                 # NEW: judge + record
                j = verdicts[h.cp]; judged[h.cp] = j
                recorded.append(record(h, j, query)); fresh.append((h, j))
                emit("judge", cp=h.cp, grade=j.grade, reason=j.reason); g = j.grade
            streak = 0 if relevant(g) else streak + 1
            if streak >= cfg.nonrelevant_streak:
                emit("list_exhausted", query=query, depth=depth, streak=streak)
                return summarize(query, depth, again, fresh)
        if len(recorded) >= intent_budget: break
    return summarize(query, depth, again, fresh)
```

`relevant(grade)` := `grade >= cfg.relevant_grade_threshold`. The streak runs over the TRUE
list (new AND prior-judged docs, in rank order); a prior-judged doc uses its STORED grade.
Descent is finite (bounded by the streak, the list going dry, or `intent_budget`; an optional
`max_list_depth` is an extra safety cap). `summarize(query, depth, again, fresh)` is the
payload the Searcher sees as history:
```
{ query,
  depth_judged: K,                                   # how deep we worked this query's list
  already_judged: { count: J, relevant: X, non_relevant: Y },   # prior-judged docs at those ranks (NOT relisted)
  new_results: [ {rank, score, grade, reason, summary} ... ] }  # the K-J NEW docs: SUMMARIES only, never full text
```
i.e. "you ran X; we judged this list to depth K; J of those we'd already judged before
(X relevant, Y non-relevant) so they're omitted; here are the K-J new passages and our
grades + reasons." This keeps already-judged docs from being repeated to the Searcher (and
to the Judger) turn after turn, while still telling it how relevant-dense the list was.

## Fetching the ranked list (one large batch; exclude only to continue)

Cottontail's ssr ranking has **NO early termination** — every `cover_search` request
re-scores ALL matching containers regardless of `top_k` or `exclude` (confirmed in
`apps/jsonl_core.cc`: the ranking pass visits every match to score it and count
`total_matches`). So the cost to minimize is the **number of requests**, not the size of
each. The controller therefore fetches a **large batch** (`fetch_k`, e.g. default 200) in ONE
request and descends it client-side. Only when a query stays relevant-dense **past rank
`fetch_k`** (no streak by the end of the batch) does it request again — and then
`exclude = seen` returns the NEXT batch without re-building/re-shipping the docs already
received. `exclude` does NOT save the re-rank (unavoidable here); it saves the summary-build +
transfer of the prior batch and hands back exactly the next unseen slice. The first request
uses an EMPTY exclude.

## De-duplication (don't repeat judged docs)

A document judged in any prior query is judged ONCE per intent. The global `judged` map
(cp -> verdict) is the source of truth:
- **Engine exclude is per-query, not global.** Each query descends its TRUE ranked list; the
  engine `exclude` is only the cps consumed during THIS query's descent (`seen`), so a
  prior-judged doc still appears at its real rank. (Contrast: passing the global judged set as
  `exclude` would hide those docs and make the depth/already-judged report impossible.)
- **Prior-judged docs are counted, not re-judged.** On re-encounter: no `engine.read`, no
  Judger call, no new `recorded` entry; the stored grade drives the streak and the doc rolls
  into the query's `already_judged` aggregate (J / X / Y).
- **The Searcher sees new docs only + the aggregate** — never the already-judged docs again.
  This is the "don't repeat judged documents over and over" requirement: the Searcher still
  learns the list was J-deep in retread (a strong signal to diversify) without re-reading it.

## Stopping rules

- **A single ranked list is exhausted** when `nonrelevant_streak` consecutive non-relevant
  docs occur in RANK ORDER over the TRUE list (new + prior-judged), or the list goes dry (a
  page returns no results). Descent is finite (bounded by the streak, dry, or `intent_budget`;
  optional `max_list_depth` safety cap).
- **The intent is done** when its recorded judgments reach `intent_budget` (= `max_judgments
  // num_intents`; e.g. 1000 total over 2 intents = 500 each) — this is the "we no longer need
  the Searcher" condition. A `max_queries` backstop (DEFAULT 100) is the ONLY other stop.
  (There is no Searcher-decline stop — tool use is forced.)
- **`max_judgments` (DEFAULT 1000) is a RUN total**, distributed evenly across intents by the
  Orchestrator. Unused budget from an intent that ends early is NOT reallocated.

## Config knobs (config.example.toml + config.toml)

- `[agents.judger]` — `class`, `llm` (a `[llm.*]` profile; may differ from the Searcher's —
  recommend a STRONG judge, default gpt-oss-120b; treat small edge models e.g. Gemma 4 E2B/E4B
  as a validate-first tier, not a drop-in swap), and `concurrency`. NOTE: `reasoning_effort`
  (gpt-oss medium/high) / thinking-mode (Gemma 4) is a quality<->throughput knob — higher
  reasoning improves judging but trades against `judge_concurrency`.
- `[agents.searcher]` — `fetch_k` (the LARGE per-request batch size, default 200; see "Fetching
  the ranked list"), `window`, `max_queries` (default 100), `max_query_retries`.
- Loop knobs (controller): `nonrelevant_streak` (default 5), `max_judgments` (default 1000 —
  the RUN-TOTAL judgment budget; the Orchestrator splits it evenly into a per-intent
  `intent_budget`), `judge_concurrency`, `max_doc_chars` (truncate large ClimbMix docs for judging),
  `relevant_grade_threshold`, and an optional `max_list_depth` (per-query descent safety cap;
  default None/off).
- **OPEN DECISION — `relevant_grade_threshold` stays a flagged `# TODO: decide` knob.** Wire it
  as an explicit, configurable knob; the streak rule's "non-relevant" definition depends on it.
  PROVISIONAL value `2` on the 0-3 scale (grades 2-3 "carry an answer" and count as relevant;
  0-1 do not — the standard TREC DL / MS MARCO binarization). This is a placeholder for eval to
  confirm, NOT a bake-in.

## Trace (research artifact — stays heavy/detailed)

Reuse the `TraceEvent` (`extra="allow"`) machinery. Event types: `llm_call` (every LLM
round-trip — Searcher proposals AND each Judger call — with `purpose`, verbatim request,
usage), `propose` (the query the Searcher chose), `search` (each engine page: query, counts,
atom_counts, returned hits, latency), `judge` (each NEW per-doc `{cp, grade, reason}`),
`revisit` (a prior-judged doc re-encountered: `{cp, grade}`, counted not re-judged),
`list_exhausted` (streak hit + depth K), `bounce` (`engine_error` / zero-result), `stop`
(`intent_budget` / `max_queries`), `error` (caught mid-loop LLM failure
-> partial result, never drop the trace). `run_output._event_dict` must rewrite `cp -> docno`
for the new `judge`/`revisit`/`search`/`list_exhausted` shapes (mirroring the current handling).

## Downstream compatibility

The controller returns the existing `SearcherResult`; `RankedEntry` already carries
`cp, grade, score, summary, reason, surfacing_query`. The run-output directory layout
(`intents.json`, `intent-NN.json`, `intent-NN.trace.jsonl`, `errors.log`) and the cp-native /
docno-on-disk boundary are UNCHANGED. The Analyst is unchanged.

## Judging design — keep / future (from the LLM-judgment literature)

KEEP (deliberate — do not "improve"): **pointwise graded** judging (one doc per call ->
`Verdict.grade`) — it aligns best with SYSTEM-ranking correlation (Arabzadeh & Clarke), which
is exactly this system's use (grades drive the rank-order streak + the per-intent ranked list);
pairwise would also break the parallel one-doc-per-call design. **No cp in the Judger output.**
**Controller-owns-control-flow.**

FUTURE (out of scope here, candidates for later tasks): a calibration pass before trusting
labels (Cohen's κ vs TREC DL qrels + system-ranking Kendall τ; the Waterloo
`Narabzad/llm-relevance-judgement-comparison` harness is near drop-in); a strict-comparability
mode that drops the trust step (step 3) for clean apples-to-apples vs TREC DL qrels;
ensembling (JudgeBlender-style, e.g. across `reasoning_effort`) if label stability becomes the
bottleneck; full per-query criteria-generation (TRUE / Farzi-Dietz) if the inline 4-step
decomposition underperforms. Evidence basis: Thomas et al. 2024 (arXiv:2309.10621), UMBRELA
(2406.06519), Arabzadeh & Clarke 2025 (2504.12558), Farzi & Dietz 2025 (2507.09488), LLMJudge
(2408.08896).

## Out of scope

C++ engine/server changes; the `SearchEngine` Protocol; `FakeEngine`; the Analyst; the
run-output directory layout; RRF/fusion (still dropped); deciding the final
`relevant_grade_threshold` value (provisional `2` on 0-3, left as a flagged config knob for eval).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Searcher keeps the EXISTING single `search{query}` tool (no new tool; the `judge` tool is REMOVED; tool use FORCED so it always searches) and has NO relevance scale (the 0-3 rubric lives only in the Judger); given an intent plus its running history it emits one precise GCL boolean query per turn
- [ ] #2 Judger judges ONE document per LLM call from the cover-biased summary + FULL document text, returning a Verdict{reason, grade} guided-decoded to the canonical UMBRELA/TREC 0-3 scale — reason declared BEFORE grade, grade Literal[0,1,2,3], NO cp (the controller pairs the verdict with the cp it asked about); up to judge_concurrency calls run in parallel; deterministic under a stub client in tests
- [ ] #3 judger.md is a decomposed UMBRELA-style 0-3 prompt: steps intent -> topical match -> trust -> scope -> grade, with low TRUST capping the grade (open-web ClimbMix text), a reason that cites a concrete span/detail, and NO persona; guided decoding constrains ONLY the post-thinking / final-channel output, never the thinking trace
- [ ] #4 Judging input is the FULL document text (truncated to max_doc_chars), not the cover summary; the cp is never sent to the Judger model
- [ ] #5 Controller fetches a LARGE batch per query (top_k=fetch_k, default 200) in ONE cover_search request and descends that TRUE ranked list client-side; only if the streak is not reached by the end of the batch does it continue with exclude=seen (this query's already-received cps, NOT the global judged set) to pull the NEXT batch; prior-judged docs still appear at their ranks and are counted; it stops the list on nonrelevant_streak in rank order or when the list goes dry (optional max_list_depth safety cap)
- [ ] #6 The non-relevant streak is computed in rank order over the TRUE list — including prior-judged docs, which contribute via their STORED grade — even though parallel judging of the NEW docs completes out of order
- [ ] #7 A document judged in a prior query is never re-sent to the Judger, never re-read, and never re-recorded; on re-encounter it is only COUNTED (it drives the streak via its stored grade and rolls into the query's already-judged aggregate)
- [ ] #8 A malformed query (EngineError) or a zero-result query is fed back to the Searcher immediately as the search tool result, and the Searcher reformulates within the same conversation
- [ ] #9 What the Searcher sees back is the NEW docs only (cover-biased SUMMARIES + grade + reason; NEVER full text), PLUS an aggregate for the prior-judged docs at those ranks: judged to depth K, of which J were already judged (X relevant, Y non-relevant) and are NOT relisted
- [ ] #10 An intent stops ONLY when its recorded judgments reach its per-intent intent_budget or the max_queries backstop (default 100) trips; there is no Searcher-decline/no-tool-call stop (the search tool is forced)
- [ ] #11 max_judgments (default 1000) is the RUN-TOTAL judgment budget; the Orchestrator splits it evenly into intent_budget = max_judgments // num_intents (>=1) and passes it to each controller (1000 over 2 intents = 500 each); budget unused by an intent that ends early is NOT reallocated
- [ ] #12 Config adds [agents.judger] (class; llm — recommend a strong judge, default gpt-oss-120b, with small edge models e.g. Gemma 4 E2B/E4B as a validate-first tier; a reasoning_effort/thinking-mode quality<->throughput note; concurrency) and loop knobs fetch_k (default 200), window, max_queries (default 100), nonrelevant_streak (default 5), max_judgments (RUN-TOTAL, default 1000), judge_concurrency, max_doc_chars, optional max_list_depth, and relevant_grade_threshold (PROVISIONAL 2 on the 0-3 scale, flagged # TODO: decide)
- [ ] #13 Controller returns the existing SearcherResult{ranked_list,events,error}; the run-output directory layout and cp-native/docno-on-disk boundary are unchanged; run_output rewrites cp->docno for the new judge/revisit/search/list_exhausted event shapes
- [ ] #14 Trace stays heavy/detailed: per-query propose, per-page search, per-NEW-doc judge (cp+grade+reason), per-revisit revisit (cp+grade), list_exhausted (with depth K), bounce (engine_error/zero-result), and stop(reason) events, plus llm_call per round-trip; a caught mid-loop LLM failure yields a partial result and is never dropped
- [ ] #15 Tests (FakeEngine + stub LLMs, no network) cover: Judger parallel/stub judging returning cp-less 0-3 Verdicts paired by the controller; one large fetch descended client-side with a continuation fetch (exclude=seen) when the streak is not reached; prior-judged docs counted-not-rejudged; streak over the true list in rank order; the depth-K / J / X / Y aggregate; the run-total budget split evenly across intents and the per-intent intent_budget stop; and malformed-query + zero-result self-correction
- [ ] #16 isj/README.md documents the Searcher/Judger split, the 0-3 trust-aware Judger, the de-duplication rule, the run-total judgment budget split across intents, and the new loop
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Create this Backlog task (done). 2. Judger: agents/judger.py + judger.md (UMBRELA-style 0-3 prompt: decomposed intent->topical->trust->scope->grade, evidence-anchored reason, no persona), Verdict{reason,grade: Literal[0,1,2,3]} in protocol/search.py (reason BEFORE grade), parallel ThreadPoolExecutor, guided-decode scoped to the post-thinking/final output only; tests/test_judger.py. 3. Rewrite Searcher: searcher.py thin query author over the EXISTING search tool (remove the judge tool) + searcher.md (GCL guidance minus judging; job = devise precise boolean queries to explore relevant docs). 4. controller.py: per-intent loop (large fetch_k batch + exclude=seen continuation, full-doc fetch, parallel judge, rank-order streak over the true list, intent_budget, error self-correction, trace; Searcher sees summaries+grades+reasons only); tests/test_controller.py. 5. Wire orchestrator.py to the controller (split run-total max_judgments into intent_budget); add trace event types in protocol/results.py (RankedEntry.grade 0-3); extend run_output._event_dict. 6. Config: [agents.judger] (+ reasoning_effort/thinking note) + loop knobs in config.example.toml and config.toml (relevant_grade_threshold provisional 2, flagged TODO). 7. Update/retire combined-searcher tests; run uv run --project isj pytest tests/. 8. Update isj/README.md. 9. Open PR off the searcher-judger branch.
<!-- SECTION:PLAN:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 uv run --project isj pytest tests/ passes
- [ ] #2 relevant_grade_threshold is a configurable knob flagged # TODO: decide (provisional 2 on the 0-3 scale, not a committed final value)
<!-- DOD:END -->
