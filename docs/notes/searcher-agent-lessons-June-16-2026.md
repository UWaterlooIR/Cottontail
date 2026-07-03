# The Searcher agent — a design grounded in live scouting

**Status:** working design notes, not yet an approved spec. This documents the
**Searcher** (the per-intent ISJ worker for the TREC RAG 2026 entry) at the level
of detail we expect to spec — the loop, the prompt, the tools, the message flow,
the controller, the output — with **each design choice explained by what we
learned probing a live model.** A chronological record of the probes (§8) backs
every claim.

**Date:** 2026-06-16/17
**Models under test:** `openai/gpt-oss-120b` (served as `gpt.oss.120b`) for Probes
1–6, and `Qwen/Qwen3.6-27B` (served as `Qwen3.6.27B`, `--tool-call-parser
qwen3_coder --reasoning-parser qwen3`) for the portability re-run (Probe 7) — both
via vLLM at `http://127.0.0.1:8000/v1`. Probes were one-off Python scripts run
through the `isj` venv (`openai` client); no files were added for them.

**Related:** `docs/agentic-isj-investigation-planner.md` (the over-built spec we
are deliberately simplifying away from), `docs/cormack-sigir-1998.md` and
`docs/multitext.md` (the source ISJ / shortest-substring method),
`backlog/docs/doc-3` (per-intent retrieval + RRF fusion, which consumes the
Searcher's output), `docs/stemming.md` (the per-term stemming mechanism).

---

## 1. What the Searcher is

The Searcher plays the role of **one 1998 ISJ human searcher**, as an LLM driving
a small tool loop. One *intent* in (one of the Analyst's interpretations of the
question, per `isj_agent/protocol/intents.py`), a **ranked, graded passage list**
out. RRF later fuses those per-intent lists into the question's final ranking.

The design commitments, and why each is what it is:

- **One LLM agent, one prompt, no sub-roles.** No INP/CM/IP, no separate
  Query-Author / Judge / Bookkeeper. Everything the over-built spec turned into
  typed artifacts, the LLM does in-context. *Why:* the spec spiralled precisely
  because it decomposed the searcher into typed parts; the antidote is to let one
  model **be** the searcher.
- **The loop is the ISJ loop, faithfully:** write a Boolean (GCL) query → read the
  proximity-ranked passages → judge them → reformulate using what was read → stop
  when results go fruitless or the budget is spent.
- **Judging and reformulation *are* the loop, not add-ons.** A Searcher that
  authors one query and returns the engine's ranking is just the cover-density
  baseline with no searcher in it. *Consequence:* there is no useful "retrieval
  skeleton without judging"; the smallest honest first version is the **whole
  loop, bounded by a small budget.**
- **The only state outside the LLM is a per-(run, topic, intent) `judged_set`** —
  the MultiText "Next" button, so the model never re-judges a document.
  Everything else (queries tried, vocabulary learned) lives in the message
  history, i.e. in the model's context.

---

## 2. The loop, concretely — a turn-by-turn trace

Intent being searched (an interpretation of *"Do I need to worry about black bear
attacks while hiking in the woods?"*):

> *"Assess the risk of black bear attacks on people hiking in forests."*

Every turn is the same API call; only `messages` grows. We append each assistant
turn, run its tool call, and append a `role:"tool"` result. (Annotations in
**[brackets]** point to the lesson behind each behavior.)

**Start.**
```jsonc
[
 {"role":"system","content":"<the prompt in §3>"},
 {"role":"user","content":"Information need: assess the risk of black bear attacks on people hiking in forests."}
]
```

**Turn 0 — the model writes a facet cover and searches.**
```jsonc
{"role":"assistant","content":"Start broad with the core facets.",
 "tool_calls":[{"id":"c1","type":"function","function":{
    "name":"search","arguments":"{\"query\":\"(^ \\\"black bear\\\" attack* hike* forest*)\"}"}}]}
```
**[§3 facet-cover shape + `word*` stemming; valid prefix GCL — Probes 4 & 6.
One tool call per turn — Probe 1.]** We run `search` and append:
```jsonc
{"role":"tool","tool_call_id":"c1","content":
 "{\"total_matches\":50,
   \"atom_counts\":{\"\\\"black bear\\\"\":611,\"attack*\":9004,\"hike*\":880,\"forest*\":5200},
   \"results\":[
     {\"docid\":\"b1\",\"text\":\"Black bear attacks on humans are rare; most encounters end without injury.\"},
     {\"docid\":\"b2\",\"text\":\"Grizzly bear attacks are far more dangerous than black bear encounters.\"},
     {\"docid\":\"b3\",\"text\":\"Bear-resistant food containers are required at many campsites.\"}]}"}
```
**[`total_matches` lets the model gauge breadth and detect dryness; per-atom
`atom_counts` make a zero-posting atom (over-stem, typo, bad stem) visible instead
of silent — Probes 3 & 5.]**

**Turn 1 — the model reads the passage text and judges, in ONE batch call.**
```jsonc
{"role":"assistant","content":"b1 directly answers; b2 is about grizzlies; b3 is off-topic.",
 "tool_calls":[{"id":"j1","type":"function","function":{
    "name":"judge","arguments":"{\"judgements\":[
      {\"docid\":\"b1\",\"grade\":3,\"reason\":\"Directly addresses black bear attack risk on humans.\"},
      {\"docid\":\"b2\",\"grade\":1,\"reason\":\"Grizzly-focused; mentions black bear only in contrast.\"},
      {\"docid\":\"b3\",\"grade\":0,\"reason\":\"Food storage, not attack risk.\"}]}"}}]}
```
**[`judge` is a single BATCH call carrying all three verdicts — because the model
cannot emit parallel tool calls (Probe 1: it silently dropped the second). One ack
back; `judged_set` now {b1,b2,b3}.]**
```jsonc
{"role":"tool","tool_call_id":"j1","content":"{\"ok\":true,\"judged_total\":3}"}
```

**Turn 2 — reformulate using words read, broaden by synonym.**
```jsonc
{"role":"assistant","content":"Add synonyms for the attack and place facets I saw.",
 "tool_calls":[{"id":"c2","type":"function","function":{
    "name":"search","arguments":"{\"query\":\"(^ black bear* (+ attack* encounter* incident*) (+ hike* trail* forest* backcountry*))\"}"}}]}
```
**[`(+ …)` holds SYNONYMS, not inflections — the `word*` marker already covers
plurals/tenses (Probes 5 & 6). `search` excludes the three judged docids, returns
b4, b5.]** Judge them next turn (b4=3, b5=0).

**Turn 4 → 5 — the guardrail in action.** A search returns one passage (`b6`); the
model tries to search *again* before judging it:
```jsonc
{"role":"assistant","content":"Chase fatality statistics.",
 "tool_calls":[{"id":"c4","type":"function","function":{
    "name":"search","arguments":"{\"query\":\"(^ black bear* attack* fatal* statistic*)\"}"}}]}
```
The loop controller **refuses** it and returns an error instead of searching:
```jsonc
{"role":"tool","tool_call_id":"c4","content":
 "{\"error\":\"Judge these passages before searching again: [b6]\"}"}
```
**[Judge-before-search is ENFORCED by the controller, not trusted to the prompt —
the model skipped it under recall pressure (Probe 3 lost a passage this way);
Probe 4 showed it recovers cleanly when bounced.]** The model then judges `b6` and
continues.

**Stop.** After two searches that return `total_matches:0`, the model ends the
need by returning an assistant message with **no tool call**:
```jsonc
{"role":"assistant","content":"Searches are now dry; the relevant set looks saturated."}
```
**[Termination is NOT model-portable: gpt-oss signals completion by not calling a
tool (and otherwise composes a prose summary — Probe 1), while Qwen never stops and
instead spins on empty `judge []` calls (Probe 7). So the CONTROLLER owns stopping —
stop-on-dry, a no-progress guard, and the hard budget cap (§5) — and treats "no tool
call" as just one acceptable stop among several. Trailing prose is discarded.]**

The Searcher returns the accumulated `judge` calls, compiled (grade desc, then
proximity, dedup by docid) into the per-intent ranked list (§6).

---

## 3. The system prompt (the validated artifact)

This is the prompt that produced clean behavior in Probe 6. Each block is
annotated with the lesson that put it there. **The prompt text itself is
load-bearing** — Probe 3 proved that compressing it or dropping the worked example
collapses GCL quality.

```
You are a search analyst exploring a large text collection to answer ONE question.
You find the passages relevant to it and grade each 0-3.

Write queries in GCL, a Boolean cover language. Use PREFIX form ONLY — never infix,
never the words AND/OR/NOT.
  (^ A B C)  all of A,B,C appear together
  (+ A B C)  any of A,B,C
  "a b c"    the exact phrase
  (!> A B)   an A that does NOT contain B  (carve out a false sense you have READ)

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

Loop, ONE tool call per turn:
1. `search` a GCL query.
2. JUDGE every returned passage (one `judge` call) before searching again.
3. Reformulate using words learned from passages.
4. `search` reports total_matches; if it returns 0 or only grade-0 passages the query
   is DRY. After at most 2 dry searches in a row, STOP.
5. At most 8 searches. When done, STOP: no tool call, output nothing.
```

Annotations:

- **"PREFIX form ONLY — never … AND/OR/NOT"** and **the full operator list** —
  without these (and the worked example), the model regresses to Lucene-style
  `(a OR b)` infix that is not valid GCL (Probe 3).
- **The three-way term model** (bare / `word*` / `(+ …)`) is the heart of it.
  - `word*` rather than `porter:` — *the single most important wording choice in
    the prompt.* `porter:` linguistically cues the model to emit a (often wrong)
    stem like `porter:stat`, which silently misses; `word*` makes it write the
    full word and lets the tool stem (Probes 5 → 6).
  - "Write the FULL ordinary word then * … NEVER a shortened stem" is stated with
    examples because the failure it prevents is silent.
  - "`(+ …)` is for SYNONYMS … NOT inflections" stops the model from spelling out
    `(+ bear bears)` now that the stemmer handles that (Probes 5 & 6).
  - "keep bare/exact for proper nouns and defining words" preserves precision and
    avoids over-stemming (`university`/`universe`).
- **"Build each query as a COVER … one facet per concept, AND-ed with ^"** is
  Charlie Clarke's canonical shape `(^ (+ …) (+ …) …)`. The worked example is the
  lever that fixes idiom: the model copies whatever the example shows (it imitated
  Charlie's hand-enumeration, then `porter:`, then `word*` in turn).
- **The loop rules** — judge-before-search, stop-after-2-dry, the search budget,
  "STOP: no tool call, output nothing" — each maps to a probed failure
  (skipped judging; non-termination; prose-summary-instead-of-stopping). The
  prompt *requests* them; the controller (§5) *enforces* the ones it can.

`black bear` collapsing to `(^ black bear*)` vs. the phrase `"black bear"` is the
model's call; it used the exact phrase unprompted in Probe 6 — good precision we
did not have to ask for.

---

## 4. The tools

Four function schemas, passed on every call. (`finish` is intentionally absent —
see the stop rule.)

**`search`** — run a GCL query; returns proximity-ranked passages not yet judged.
```jsonc
{"name":"search","description":"Run a GCL query; returns proximity-ranked passages NOT yet judged.",
 "parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}
```
Result shape (engine/controller fills it):
```jsonc
{"total_matches": 50,
 "atom_counts": {"attack*": 9004, "hike*": 880, ...},   // per-leaf posting counts
 "results": [{"docid":"...","text":"...windowed, highlighted..."}, ...],
 "note": ""}                                            // e.g. "no matches — broaden or stop"
```
- `total_matches` and `note` are what the model uses to detect dryness and stop
  (Probes 3–6).
- `atom_counts` exposes a zero-posting atom so an over-stem / typo / bad-stem miss
  is visible, not silent (motivated by Probe 5's stem-guessing).
- The controller widens each cover to a presentation window and excludes
  `judged_set` members before returning.

**`judge`** — record relevance judgements for the passages just read.
```jsonc
{"name":"judge","description":"Record relevance judgements for the passages you just read.",
 "parameters":{"type":"object","properties":{
    "judgements":{"type":"array","items":{"type":"object","properties":{
       "docid":{"type":"string"},"grade":{"type":"integer","enum":[0,1,2,3]},
       "reason":{"type":"string"}},"required":["docid","grade","reason"]}}},
    "required":["judgements"]}}
```
- **It takes an ARRAY.** This is the workaround for no parallel tool calls — one
  call records a whole search's worth of verdicts (Probe 1: parallel calls drop
  work; a single array-arg call fills cleanly; confirmed again on Qwen, Probe 7).
  Each judged docid enters `judged_set`; the judgement enters the accumulator that
  becomes the output.
- **An empty or all-duplicate `judge []` is a no-op** and the controller counts it
  toward a no-progress limit — Qwen spins on empty `judge []` instead of stopping
  (Probe 7), so a no-op judge must not be mistaken for work.

**`read_document`** — more context around a passage, or the full document.
```jsonc
{"name":"read_document","description":"Return more context around a passage, or the full document.",
 "parameters":{"type":"object","properties":{
    "docid":{"type":"string"},"window":{"type":"integer"}},"required":["docid"]}}
```
- For when a passage is promising but needs context before grading. (Not exercised
  heavily in the probes; carried from the ISJ spec's `read`.)

---

## 5. The loop controller (a guardrail, not a pass-through)

The controller is the kernel that holds `messages`, `judged_set`, the judgement
accumulator, and the budgets — and **enforces the invariants the model violates
under pressure.** Pseudocode:

```python
def run_searcher(intent, engine, budget):
    msgs = [system_prompt(), user(intent)]
    judged, accum, pending = set(), [], []   # pending = surfaced-but-unjudged docids
    searches, dry_streak, no_progress = 0, 0, 0
    while searches < budget.max_searches:
        m = llm(msgs, TOOLS)                 # one create() call
        msgs.append(assistant(m))
        if not m.tool_calls:                 # one accepted STOP (gpt-oss); discard any prose
            break
        call = m.tool_calls[0]               # exactly one per turn (no parallel)
        if call.name == "search":
            if pending:                                  # GUARDRAIL 1: judge first
                msgs.append(tool_error(call, f"Judge these first: {pending}"))
                continue
            err = validate_gcl(call.query)               # GUARDRAIL 2: valid prefix GCL
            if err:
                msgs.append(tool_error(call, f"Invalid GCL: {err}. Use prefix form ..."))
                continue
            res = engine.search(stem_and_scope(call.query), exclude=judged)  # word*->porter, <<:item
            pending = [r.docid for r in res.results]
            searches += 1
            dry_streak = dry_streak + 1 if res.total_matches == 0 else 0
            no_progress = 0
            msgs.append(tool_result(call, res))
            if dry_streak >= 2:              # GUARDRAIL 3: stop on dryness (prompt also says stop)
                break
        elif call.name == "judge":
            new = [j for j in call.judgements if j.docid not in judged]
            for j in new:
                judged.add(j.docid); accum.append(j)
            pending = [d for d in pending if d not in judged]
            no_progress = no_progress + 1 if not new else 0   # empty/dup judge = no progress
            msgs.append(tool_result(call, {"ok": True, "recorded": len(new)}))
        elif call.name == "read_document":
            msgs.append(tool_result(call, engine.read(call.docid, call.window)))
        if no_progress >= 2:                 # GUARDRAIL 4: model spinning (Qwen empty judge[]) -> stop
            break
    return compile_ranked_list(accum)        # §6
```

Each guardrail is justified by a probe:
- **`validate_gcl` + bounce** — Probe 3 regressed to invalid GCL; Probe 4 showed
  the model fixes it when handed the parse error. (Real impl: `SExpression::from_string`.)
- **judge-before-search + bounce** — Probe 3 silently dropped a surfaced passage;
  Probe 4 showed clean recovery when the premature `search` is refused.
- **stop-on-dry + no-progress break** — termination is not model-portable: gpt-oss
  stops by emitting no tool call, but Qwen (Probe 7) never does and spins on empty
  `judge []`. The controller stops after 2 dry searches and after 2 no-progress
  turns, treating "no tool call" as only one acceptable stop among several.
- **`max_searches` cap** — the model does not reliably self-terminate (Probes 3, 7);
  the cap also bounds context, cost, and latency.
- **`stem_and_scope`** — translates `word*` atoms to the stemmed feature and wraps
  the cover in `(<< … :item)`; the agent never writes either (§7).

---

## 6. The output type (what crosses the boundary to RRF)

The compiled per-intent ranked list — grade desc, then proximity (cover length)
asc, dedup by docid keeping its best passage:

```jsonc
{
  "intent": "Assess the risk of black bear attacks on people hiking in forests.",
  "entries": [
    {"rank": 1, "docid": "b1", "grade": 3,
     "passage": {"text": "Black bear attacks on humans are rare; ...", "start": 0, "end": 0},
     "surfacing_query": "(^ \"black bear\" attack* hike* forest*)",
     "reason": "Directly addresses black bear attack risk on humans."},
    {"rank": 2, "docid": "b4", "grade": 3, "passage": {...},
     "surfacing_query": "(^ black bear* (+ attack* encounter* incident*) ...)",
     "reason": "Hiker risk-reduction for black bear attacks."}
  ]
}
```
- `grade` / `reason` come straight from the `judge` calls — populated, because
  judging is *in* the loop (this is why the earlier "skeleton with grade=null" cut
  was wrong).
- RRF (doc-3) is rank-based, so it only needs the ordering; `passage` and `reason`
  carry the evidence the later RAG Writer will ground on.

---

## 7. Engine work this implies

Most of the loop maps onto the shipped `search_gcl` / `get_document` / `count`
surface. The genuinely new capability, all on the tool/engine side:

1. **Selective per-atom stemming: `word*` → `porter:` + `Porter(word)`** (with the
   existing symmetric exact-fallback for unstemmable words), leaving bare atoms
   exact. Unlike the shipped whole-query `--stem`, which stems *every* term. This
   is what lets the agent write full words and never touch `porter:`.
2. **Per-atom posting counts** in `search` results (extend what `--explain`
   computes per leaf).
3. **`total_matches`** (cover / `:item` count) on `search` results.
4. The **`(<< … :item)` document-scoping wrapper**, supplied by the tool, not the
   agent (Charlie's containment form; our marker is `:item`).
5. Per-(run, topic, intent) **`judged_set`** filtering — per-request injection vs.
   server-side session is an open call (ISJ spec §4.2.1).

---

## 8. The scouting record (chronological)

Every decision above traces to one of these. All ran against the live
`gpt.oss.120b` with canned engine responses.

**Probe 1 — tool-calling mechanics.**
- *Parallel tool calls are NOT supported.* Asked for weather in Paris *and* Tokyo
  with a one-city tool, the model emitted one call and **silently dropped Tokyo**.
- *A batch/array-arg tool works perfectly* (`cities:["Paris","Tokyo"]` in one
  call). → `judge` is a batch tool.
- *The loop works*, one call/turn, alternating.
- *No `finish` call:* the model ended by returning a markdown summary with no tool
  call. → "no tool call" is the stop signal; forbid the summary.

**Probe 2 — GCL authoring (full cheatsheet, `porter:` example).**
- *gpt-oss authors valid prefix GCL*, with phrases and `porter:`, keeping proper
  nouns exact.
- *Per-term stemming landmine articulated:* the stemmed feature is `porter:` +
  *Porter stem*; the model wrote both `porter:validate` and `porter:validated`.
  → the stem must be computed tool-side, not by the model.

**Probe 3 — tightened prompt, but compressed GCL cheatsheet.**
- *GCL regressed to invalid* (`(a OR b)` infix) once the worked example was
  dropped. → the example/cheatsheet is load-bearing.
- *Judge-before-search violated* — a surfaced passage was never graded. → enforce
  alternation in the controller.
- *Stop-on-dry worked* (two `total_matches:0` → stop). → keep `total_matches`.

**Probe 4 — guardrails + Charlie's bear example (full cheatsheet).**
- *All green:* valid GCL every turn; the judge-before-search guardrail fired once
  and the model **recovered**; nothing left unjudged; clean stop.
- *But 0 `porter:` use* — it copied Charlie's hand-enumerated `(+ bear bears)`.
  → the model imitates the example's idiom.

**Charlie's email (mid-stream).** Gave the canonical shape
`(<< (^ (+ A B C) (+ D E F)) :)` — facet cover scoped to a document. We adopt the
inner cover as the agent's job and let the tool supply `(<< … :item)`. Mark noted
Charlie hand-enumerates plurals because *his system has no stemmer* — ours does.

**Probe 5 — stemmer-aware (`porter:` bear example, three-way term model).**
- *Adopted `porter:` and reserved `(+ …)` for synonyms* — good.
- *NEW landmine:* the model **guesses Porter stems** (`porter:incid`,
  `porter:stat`, `porter:injur`) — truncated, not natural words — which silently
  miss under tool-side stemming. The string `porter:` is itself the trap.

**Probe 6 — `word*` family marker (the fix).**
- *Cleanest run.* Every starred token a full natural word (`attack*`, `bear*`,
  `incident*`, `statistic*`, `maul*`); **0 `porter:` leakage, 0 hand-enumerated
  inflections, 0 invalid GCL, 0 guardrail trips, nothing unjudged, clean stop.**
  Kept `"black bear"` as a phrase and `black` exact, unprompted.
- → Stemming is safe for the LLM iff the marker is a full-word suffix the tool
  translates, never the engine's `porter:`. Mark's fallback (hide stemming from
  the LLM) is not needed.

**Probe 7 — the `word*` scout re-run on `Qwen3.6.27B` (portability check).**
- *GCL and stemming ported perfectly:* valid prefix GCL every turn, full-word
  `word*` markers, `(+ …)` synonyms-only, `black` exact; **0 `porter:` leakage, 0
  inflection enumeration, 0 invalid GCL, 0 premature-search, no parallel calls,
  nothing unjudged.** The `word*` / facet-cover / guardrail design is model-portable.
- *New failure — termination is NOT portable.* After two dry searches Qwen never
  emitted the no-tool-call stop; it **spun on empty `judge []` for eight turns**
  until the budget cap. (gpt-oss instead writes a prose summary.) → the controller
  must own termination (stop-on-dry + no-progress guard + hard cap, §5); "no tool
  call" is just one acceptable stop.
- *Aside:* Qwen graded the grizzly passage `b2` a 2 vs. gpt-oss's 1 — grades are
  not model-invariant (cf. cross-judge agreement in the dev-data design).

### Three meta-lessons

1. **The worked example controls the model's idiom more than the rules do.** It
   copied Charlie's hand-enumeration, then `porter:`, then `word*` — each time
   matching the example. Choose the example to demonstrate exactly the behavior
   you want.
2. **Guardrail, don't trust.** The model violates soft rules under pressure
   (skips judging, regresses GCL, guesses stems, won't stop). Where a violation is
   detectable (parse validity, alternation, zero-posting atoms, no-progress spin),
   enforce it in the controller and let the model self-correct — which it does well
   against injected tool errors.
3. **What is portable is not what you'd guess.** The fragile-seeming parts (GCL
   syntax, per-term stemming) ported cleanly across two model families once the
   prompt was right; the *termination* convention did not. Validate behavior
   per-model, and let the controller — not a prompt convention — own stopping.

---

## 9. What is still open

- **Live model only, mocked engine.** Every probe used canned passages; the loop
  has not run against a real burrow, so recall/precision on real ClimbMix text is
  unmeasured. The first implementation task stays mock-only (deterministic, like
  the Analyst task); real-engine binding is a follow-on.
- **Budget / stop numbers** (≤~8–12 searches, ≤~60 judgements, ≤2 dry) are
  placeholders to tune on dev data.
- **Grade scale:** probes used 0–3; align with UMBRELA 0–4?
- **Cost/latency floor:** no parallelism ⇒ ≥2 model calls per query cycle; the
  budget cap bounds it.
- **`(<< … :item)` ownership and `judged_set` transport** are engine/server design
  points carried from the ISJ spec.
- **Model portability.** Validated on `gpt-oss-120b` and `Qwen3.6.27B`: the GCL /
  stemming / guardrail design ported, but termination did not (now controller-owned).
  Re-run the §8 scout against any new serving model before trusting it.

---

## 10. Next step

Draft the Backlog task for the **single-agent bounded Searcher loop**:
`isj_agent/agents/searcher.py` + bundled `searcher.md` (the §3 prompt), a
`Searcher ↔ engine` Protocol it calls, the guardrailed controller (§5), and the
rich graded result type (§6) — tested against a **mock engine** with no live calls
(deterministic, like the Analyst task). The `word*`→Porter + per-atom-count
**engine** changes (§7), the real Cottontail tool binding, and the RRF/orchestrator
wiring (doc-3) are explicit follow-on tasks. The §3 prompt and §4/§5/§8 rationale
go into the task so a future agent need not re-derive them.
