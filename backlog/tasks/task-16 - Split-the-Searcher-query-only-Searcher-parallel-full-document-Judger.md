---
id: TASK-16
title: 'Split the Searcher: query-only Searcher + parallel full-document Judger'
status: To Do
assignee: []
created_date: '2026-06-27 01:53'
updated_date: '2026-06-27 13:55'
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
- EDIT `isj_agent/protocol/results.py` — keep `SearcherResult`/`RankedEntry`; add trace event types.
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
  the `judge` tool. There is NO 0-4 scale in the Searcher.
- It keeps IMMEDIATE error self-correction: a malformed query (EngineError) or a zero-result
  query comes straight back as the next `search` tool result, in-thread, so it reformulates
  right away (same behavior as today's engine_error / dry feedback).

### Judger (parallel, full-document) — `agents/judger.py` + `judger.md`
- INPUT: the intent, and for each **NEW** candidate (NOT judged by any prior query) the
  surfaced Hit (summary, score, cp) PLUS the FULL document text (`engine.read(cp)`), truncated
  to `max_doc_chars`. Already-judged docs are NEVER re-sent to the Judger.
- OUTPUT: a `Judgement { cp, grade (0-4), reason }` per candidate, guided-decoded via
  `Judgement.model_json_schema()` (the same json-schema pattern the Analyst uses), so grades
  are constrained to 0-4.
- ONE LLM call judges ONE document. The Judger runs up to `judge_concurrency` calls
  simultaneously via a `ThreadPoolExecutor`. `judger.md` carries the UMBRELA 0-4 umbrella
  judging scheme (the 0-4 rubric currently inlined in `searcher.md` moves here and is expanded
  into a proper umbrella prompt that frames the passage + full document against the intent);
  the draft is under "The prompts" below.

### Controller (the per-intent loop) — `controller.py`
Owns paging, the streak stop, the judgment budget, error self-correction routing, and the
trace. Returns the EXISTING `SearcherResult { ranked_list, events, error }` so C2/C3 and the
run-output layout are unchanged.

## The prompts (drafts to embed)

These are the starting drafts for `searcher.md` and `judger.md`. The Searcher's GCL block is
the LOAD-BEARING text from the current `searcher.md` (TASK-5.6 /
`docs/searcher-agent-lessons-June-16-2026.md`) — keep it close to verbatim; the rest is
reframed for query-only exploration. The Judger is an UMBRELA-style full-document assessor on
the project's 0-4 scale.

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
query surfaced — each already graded for you (0-4) with a short reason — plus a note of how
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

### `judger.md` (Judger — UMBRELA-style full-document assessor)

```
You are a relevance assessor. Given a QUESTION and a DOCUMENT, decide how well the document
satisfies the information need behind the question, and assign an integer grade on this scale:
  0 — Irrelevant: does not address the question.
  1 — Marginal: an on-topic mention, but no information that helps answer it.
  2 — Related: some useful information, but partial or tangential.
  3 — Relevant: directly answers the question with useful, on-topic information.
  4 — Highly relevant: a focused, complete answer to the question.

Work in steps:
1. Infer the underlying intent of the question — what would actually satisfy the searcher.
2. Read the DOCUMENT and measure how well its content meets that intent — coverage,
   directness, specificity. Judge it on the information it ACTUALLY contains, not on keyword
   overlap or topical vibe.
3. Choose the single best-fitting grade above.

Return ONLY the structured result: an integer `grade` (0-4) and a one-sentence `reason`
that justifies it.

QUESTION: {intent}

A representative matching passage (to orient you — judge the FULL document, not just this):
{summary}

DOCUMENT:
{document}
```

`{intent}`, `{summary}` (the surfaced cover-biased summary), and `{document}` (the full body
via `engine.read(cp)`, truncated to `max_doc_chars`) are filled by the controller per
candidate; the `grade`/`reason` are guided-decoded from `Judgement.model_json_schema()`.

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
        verdicts = judger.judge(intent, [(h, engine.read(h.cp)) for h in new_hits])  # parallel; keyed by cp
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

- `[agents.judger]` — `class`, `llm` (a `[llm.*]` profile; may differ from the Searcher's),
  and `concurrency`.
- `[agents.searcher]` — `fetch_k` (the LARGE per-request batch size, default 200; see "Fetching
  the ranked list"), `window`, `max_queries` (default 100), `max_query_retries`.
- Loop knobs (controller): `nonrelevant_streak` (default 5), `max_judgments` (default 1000 —
  the RUN-TOTAL judgment budget; the Orchestrator splits it evenly into a per-intent
  `intent_budget`), `judge_concurrency`, `max_doc_chars` (truncate large ClimbMix docs for judging),
  `relevant_grade_threshold`, and an optional `max_list_depth` (per-query descent safety cap;
  default None/off).
- **OPEN DECISION — `relevant_grade_threshold` has NO agreed default.** Wire it as an explicit,
  configurable knob with a clearly-marked PROVISIONAL value and a `# TODO: decide` flag (do NOT
  silently bake in a default); the streak rule's "non-relevant" definition depends on it.

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

## Out of scope

C++ engine/server changes; the `SearchEngine` Protocol; `FakeEngine`; the Analyst; the
run-output directory layout; RRF/fusion (still dropped); deciding the final
`relevant_grade_threshold` value (left as a flagged config knob for eval).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Searcher keeps the EXISTING single `search{query}` tool (no new tool; the `judge` tool is REMOVED; tool use FORCED so it always searches) and has NO 0-4 scale; given an intent plus its running history it emits one precise GCL boolean query per turn
- [ ] #2 Judger judges ONE (surfaced passage + full document via engine.read(cp)) per LLM call, returning Judgement{cp,grade 0-4,reason} guided-decoded to 0-4; up to judge_concurrency calls run in parallel via a thread pool; deterministic under a stub client in tests
- [ ] #3 Judging input is the FULL document text (truncated to max_doc_chars), not the cover summary
- [ ] #4 Controller fetches a LARGE batch per query (top_k=fetch_k, default 200) in ONE cover_search request and descends that TRUE ranked list client-side; only if the streak is not reached by the end of the batch does it continue with exclude=seen (this query's already-received cps, NOT the global judged set) to pull the NEXT batch; prior-judged docs still appear at their ranks and are counted; it stops the list on nonrelevant_streak in rank order or when the list goes dry (optional max_list_depth safety cap)
- [ ] #5 The non-relevant streak is computed in rank order over the TRUE list — including prior-judged docs, which contribute via their STORED grade — even though parallel judging of the NEW docs completes out of order
- [ ] #6 A document judged in a prior query is never re-sent to the Judger, never re-read, and never re-recorded; on re-encounter it is only COUNTED (it drives the streak via its stored grade and rolls into the query's already-judged aggregate)
- [ ] #7 A malformed query (EngineError) or a zero-result query is fed back to the Searcher immediately as the search tool result, and the Searcher reformulates within the same conversation
- [ ] #8 What the Searcher sees back is the NEW docs only (cover-biased SUMMARIES + grade + reason; NEVER full text), PLUS an aggregate for the prior-judged docs at those ranks: judged to depth K, of which J were already judged (X relevant, Y non-relevant) and are NOT relisted
- [ ] #9 An intent stops ONLY when its recorded judgments reach its per-intent intent_budget or the max_queries backstop (default 100) trips; there is no Searcher-decline/no-tool-call stop (the search tool is forced)
- [ ] #10 max_judgments (default 1000) is the RUN-TOTAL judgment budget; the Orchestrator splits it evenly into intent_budget = max_judgments // num_intents (>=1) and passes it to each controller (1000 over 2 intents = 500 each); budget unused by an intent that ends early is NOT reallocated
- [ ] #11 Config adds [agents.judger] (class, llm, concurrency) and loop knobs fetch_k (large per-request batch, default 200), window, max_queries (default 100), nonrelevant_streak (default 5), max_judgments (RUN-TOTAL budget, default 1000), judge_concurrency, max_doc_chars, optional max_list_depth, and relevant_grade_threshold (PROVISIONAL value, flagged # TODO: decide — no silent default)
- [ ] #12 Controller returns the existing SearcherResult{ranked_list,events,error}; the run-output directory layout and cp-native/docno-on-disk boundary are unchanged; run_output rewrites cp->docno for the new judge/revisit/search/list_exhausted event shapes
- [ ] #13 Trace stays heavy/detailed: per-query propose, per-page search, per-NEW-doc judge (cp+grade+reason), per-revisit revisit (cp+grade), list_exhausted (with depth K), bounce (engine_error/zero-result), and stop(reason) events, plus llm_call per round-trip; a caught mid-loop LLM failure yields a partial result and is never dropped
- [ ] #14 Tests (FakeEngine + stub LLMs, no network) cover: Judger parallel/stub judging; one large fetch descended client-side with a continuation fetch (exclude=seen) when the streak is not reached; prior-judged docs counted-not-rejudged; streak over the true list in rank order; the depth-K / J / X / Y aggregate; the run-total budget split evenly across intents and the per-intent intent_budget stop; and malformed-query + zero-result self-correction
- [ ] #15 isj/README.md documents the Searcher/Judger split, the de-duplication rule, the run-total judgment budget split across intents, and the new loop
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Create this Backlog task (done). 2. Judger: agents/judger.py + judger.md (UMBRELA prompt), parallel ThreadPoolExecutor, guided-decoded Judgement; tests/test_judger.py. 3. Rewrite Searcher: searcher.py thin query author over the EXISTING search tool (remove the judge tool) + searcher.md (GCL guidance minus judging; job = devise precise boolean queries to explore relevant docs). 4. controller.py: per-intent loop (paging via exclude, full-doc fetch, parallel judge, rank-order streak, max_judgments budget, error self-correction, trace; Searcher sees summaries+grades+reasons only); tests/test_controller.py. 5. Wire orchestrator.py to the controller; add trace event types in protocol/results.py; extend run_output._event_dict. 6. Config: [agents.judger] + loop knobs in config.example.toml and config.toml (relevant_grade_threshold flagged TODO). 7. Update/retire combined-searcher tests; run uv run --project isj pytest tests/. 8. Update isj/README.md. 9. Open PR off the searcher-judger branch.
<!-- SECTION:PLAN:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 uv run --project isj pytest tests/ passes
- [ ] #2 relevant_grade_threshold is present as a configurable knob with a # TODO: decide marker (default not baked in)
<!-- DOD:END -->
