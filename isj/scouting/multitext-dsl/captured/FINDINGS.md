# Findings — MultiText-DSL tiered queries (2026-07-01)

**Question.** Can gpt-oss-120b write tiered "faceted GCL" queries the way TREC-4 MultiText humans
(and ChatGPT) do — and can we make it reliable? This is the alternative to the JSON-tool tiered
designs, which produced runaway generation, facet-reference bugs, and 30–50-term over-enumeration
(see [`../../tool-variants/captured/`](../../tool-variants/captured/) and
[`../../tiered-factorial/captured/FINDINGS.md`](../../tiered-factorial/captured/FINDINGS.md)).

## The key realization: Cottontail already compiles this DSL

`src/mt.cc` (`Mt::infix_expression`) parses the exact MultiText syntax — `name = expr` macros,
`+` (OR), `^` (AND), `<>` (followed-by), `( expr ) < [N]` (proximity), quoted literals — and emits
Cottontail GCL, returning a bool + error for validity. `apps/mt.cc` already drives macro
definitions + `@rank` tier lines into `tiered_ranking` (the same cascade TASK-19 exposed). So the
LLM's program is **native input** — no DSL compiler to build. We added `//apps:mt-compile`
(`apps/mt-compile.cc`), a warren-free validity oracle, for scouting.

The DSL's variable/token separation is **native**: **tokens are quoted, macros are bare** — no
sigil, no JSON structure needed. That is what made the earlier JSON-tool attempts unnecessary.

## Setup

- `librarian-prompt.md` — role + a short language primer + one worked example.
- `run.py` — per TREC-4 topic: prompt gpt-oss (STREAMING, capturing the `reasoning` channel and
  `content` separately), extract the program, compile it via `mt-compile`, record everything.
- 10 TREC-4 topics: 203, 207, 211, 214, 220, 224, 229, 238, 244, 249 (208 is the worked example).
- gpt-oss-120b, temperature 0.

## What we found

### 1. gpt-oss writes valid MultiText — like ChatGPT
ChatGPT's exact topic-201 program compiled with 0 errors. On the first pass (old prompt, high
effort), **5/9** finished programs compiled clean.

### 2. The real problem was pathologically bloated REASONING
At `reasoning_effort=high` with the TREC `<top>` markup in the prompt, the reasoning ran
**18 K–92 K chars (median 35 K)** — 10–50× the ~2 K program. Reading the reasoning streams showed
it was **not** query craft but **degenerate loops**:
- **Repetition loop** (topic 211): `"trend" + "trend" + "trend" + …` hundreds of times — never
  escaped, never emitted a program → 180 s timeout with zero output.
- **Compulsive verification loop** (topic 249): `Now we need to ensure we have quotes for "X".
  Already.` one line per term, dozens of times — finished, but burned 92 K chars.
- **Format deliberation** (topic 207): agonizing over whether to echo the `<top>/<num>/<desc>`
  block and "which channel to output in."

The triggers were **our own prompt**: the TREC markup (format deliberation) and, plausibly, the
"ALWAYS quote" rule (the verification loop), amplified by high effort.

### 3. Compile failures were few and all bounce-fixable
The baseline's 4 failures clustered into: **undefined symbol** (a macro reference that doesn't
resolve — 207), **`< [N]` chaining** rejected as *"Extra characters at the end"* (220, 238, 244 —
the model wrote `A < [2] + B < [2]` instead of parenthesizing each term), and a **paren mismatch**
(238). Every one is a one-line compiler diagnostic the model could self-correct from with a bounce.

### 4. Clean prompt + medium effort fixed everything
Removing the `<top>` markup (single-statement intent + an explicit *output-only* contract +
topic-free `@rank`) and dropping `reasoning_effort` to **medium**:

```
topic |   BASELINE (old prompt, high)   |  CLEANED (new prompt, medium)
      |   compiled  reason_c    s       |   compiled  reason_c   s
 203  |     True     60,103   120.5     |     True      2,986    6.4
 207  |    False     90,367   141.2     |     True      2,160    4.9
 211  |     -(TO)    73,351   180.0     |     True      2,508    5.7
 214  |     True     29,077    50.2     |     True      2,277    4.5
 220  |    False     33,145    56.3     |     True      2,621    5.5
 224  |     True     37,899    68.2     |     True      2,947    6.4
 229  |     True     32,914    58.0     |     True      3,282    6.6
 238  |    False     17,904    29.7     |     True      2,354    5.0
 244  |    False     21,275    35.1     |     True      1,735    3.8
 249  |     True     91,768   140.0     |     True      3,295    6.2

BASELINE:  clean 5/9   timeouts 1   reasoning median 35,522  max 91,768   total 879 s
CLEANED:   clean 10/10 timeouts 0   reasoning median  2,564  max  3,295   total  55 s
```

- **Compile 5/9 → 10/10** — every prior failure (207, 220, 238, 244) *and* the timeout (211) now clean.
- **Reasoning median 35.5 K → 2.6 K (~14×); max 92 K → 3.3 K (~28×)** — the loops are gone.
- **Timeouts 1 → 0; total wall-clock 879 s → 55 s (~16×).**

### 5. Query quality held up — the programs are good, not thin
The cleaned programs are well-scoped faceted tiered queries with sensible synonym sets, correct
precise→broad ladders, and idiomatic DSL (`<>` adjacency for phrase variants, macros composed) —
*cleaner* than the JSON tool's 30–50-term over-enumeration. Two examples:

```
TOPIC 214 (self-hypnosis techniques)
  tech    = technique/method/approach/procedure/strategy (+ plurals)
  selfhyp = "self-hypnosis" + (self <> hypnosis) + (auto <> hypnosis) + autohypnosis
  create  = create/generate/produce/develop/establish (+ forms)
  q1 = tech ^ selfhyp ^ create      q0 = tech ^ selfhyp      @rank q1 q0

TOPIC 249 (rainforest -> world weather)
  rf = (rainforest phrases) ^ (deforestation/destruction/depletion/logging)
  wt = (weather/climate) + (temperature/precipitation/storm/drought)
  im = impact/effect/influence      gw = world/global/planetary/earth
  q0 = rf ^ im ^ wt ^ gw   q1 = rf ^ wt   q2 = rf0 ^ rf1 ^ wt0   @rank q0 q1 q2
```

## Conclusion

The MultiText-DSL path — **the librarian writes the program; Cottontail's `Mt` compiles + validates
it; `tiered_ranking` runs the cascade** — with a **clean prompt + medium effort**, gives on this
10-topic scout: **100% compile validity, 0 timeouts, ~16× faster, ~14–28× less reasoning, and good
query craft.** It decisively beats the JSON-tool tiered designs this investigation worked through
(bare-list runaways, V4 facet-reference bugs, 30–50-term bloat). It is the strongest candidate for
the real TieredSearcher.

## Caveats / not yet tested

- **Retrieval quality is UNTESTED.** The programs *compile*; we have not run the cascade + judged
  the results to confirm they *retrieve* well. This is the next step.
- **n = 10 topics, single run.** temperature 0 but gpt-oss is nondeterministic on batched inference.
  TREC-4 descriptions stand in for the real Analyst intents (a few are multi-part, not truly
  single-statement).
- **Prompt and effort changed together.** The clean prompt and high→medium effort were applied at
  once, so their individual contributions aren't separated (a "clean prompt + high" cell would
  isolate them — not run). The improvement is the combined effect.

## Data + code

- Baseline (old prompt, high): [`2026-07-01-baseline-oldprompt-high.jsonl`](2026-07-01-baseline-oldprompt-high.jsonl)
- Cleaned (new prompt, medium): [`2026-07-01-cleaned-newprompt-medium.jsonl`](2026-07-01-cleaned-newprompt-medium.jsonl)
  (each record holds the full `reasoning` + `content` + `program` + `compile` result)
- Prompt: [`../librarian-prompt.md`](../librarian-prompt.md); harness: [`../run.py`](../run.py); README: [`../README.md`](../README.md)
- Validity oracle: `//apps:mt-compile` (`apps/mt-compile.cc`) — warren-free MultiText compile check.
- Cottontail's DSL compiler + driver: `src/mt.{h,cc}`, `apps/mt.cc`.

## Next

1. **Retrieval check** — wire `Mt`-compiled tiers into the enriched tiered cascade (the TASK-19
   handler) and judge results on a few topics via the live stack.
2. **Formalize** — rework the TieredSearcher (TASK-20) onto the MultiText-DSL path: the librarian
   prompt, a program-carrying tool, server-side `Mt` compile (bounce compile errors) + the cascade.
   Worth a dedicated backlog task.
