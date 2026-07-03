# TASK-16 Judger — recommended spec adjustments

**Audience:** Claude Code, editing `task-16 - Split-the-Searcher...md` and the files it touches.
**Scope of this brief:** the **Judger only** (`agents/judger.py`, `judger.md`, the `Verdict`
schema in `protocol/search.py`, and the `[agents.judger]` / loop knobs). It does **not** touch
the Searcher, controller loop, paging, de-duplication, budget, or trace design — those are
sound and out of scope here.

These recommendations are grounded in the LLM-relevance-judgment literature (see
**Evidence basis** at the end). Two design decisions were settled by the spec owner before
this brief was written:

1. **Relevance scale:** switch from the current **0–4** to the canonical UMBRELA / TREC
   **0–3** scale (for calibration and direct comparability with TREC DL qrels).
2. **Corpus:** the Judger runs over **open-web / mixed-quality** documents (ClimbMix), so a
   **trust / credibility** dimension is included in the rubric.

---

## Change 1 — Scale: 0–4 → 0–3 (consistency-critical)

The spec currently says "0-4" in many places, and the guided-decode constraint, the rubric,
and several acceptance criteria all encode 5 levels. Switching the scale means changing
**every** occurrence; a mismatch where the schema still permits `4` while the rubric describes
0–3 lets the decoder emit an undefined grade the prompt never anchors.

**Locations to update:**

- `judger.md` rubric — replace the five 0–4 levels with the four 0–3 levels in **Change 2**.
- `protocol/search.py` — `Verdict.grade` constraint (see **Change 3**: `Literal[0, 1, 2, 3]`).
- Judger section: `Verdict { grade (0-4), reason }` → `Verdict { grade (0-3), reason }`, and
  "grades are constrained to 0-4" → "constrained to 0-3".
- Judger section: "the UMBRELA **0-4** umbrella judging scheme (the **0-4** rubric currently
  inlined in `searcher.md`...)" → "0-3".
- `searcher.md` draft: "each already graded for you **(0-4)**" (appears twice) → "(0-3)".
- **AC #1** — "has NO 0-4 scale" → "has NO relevance scale (the 0–3 rubric lives only in the
  Judger)".
- **AC #2** — "Verdict{grade **0-4**, reason} guided-decoded to **0-4**" → "0-3".
- **Implementation Plan, step 2** — "guided-decoded **Judgement**" is stale wording; it should
  read **`Verdict`** (the rest of the spec already uses `Verdict`). Fix while here.

### 1a — `relevant_grade_threshold` semantics shift with the scale

The spec correctly leaves `relevant_grade_threshold` as a flagged `# TODO: decide` knob with
no silent default — **keep it that way.** But note the binarization point on the new scale
moves, and the streak rule's "non-relevant" definition depends on it. On the UMBRELA 0–3
semantics, grades **2–3 carry an answer** (2 = some answer; 3 = complete) and **0–1 do not**
(0 = unrelated; 1 = on-topic but no answer). The natural cut is therefore **≥ 2**, which also
matches the standard TREC DL / MS MARCO binarization (labels 2–3 = relevant).

**Recommendation:** set the *provisional* value to `relevant_grade_threshold = 2` on the 0–3
scale, still flagged `# TODO: decide` for eval. This is guidance for the placeholder, not a
bake-in — the knob stays explicit and configurable per the spec's open decision.

---

## Change 2 — Rewrite `judger.md`

The current `judger.md` draft is a clean prompt but is holistic (one leap to a grade), omits
the trust dimension, uses 0–4, and frames the model with a strong "You are a relevance
assessor" persona. The literature points in four concrete directions, all incorporated below:

- **Decompose the judgment** into explicit sub-steps rather than one holistic grade — the
  single change most consistently rewarded across studies (LLMJudge winner, Farzi & Dietz,
  RULERS). Kept inside one LLM call (no architecture change): intent → topical match → trust →
  scope → grade.
- **Restore trust** as a step that *caps* the grade (not a separate score — keeps the
  `Verdict{reason, grade}` output minimal). Thomas et al.'s best Bing configuration scored a
  trust aspect alongside topicality; it matters on open-web data.
- **Evidence-anchored reason** — require the reason to cite a concrete span/detail, not just
  assert (RULERS' 2026 argument against unverifiable free-form rationales).
- **Drop the persona** — Thomas et al.'s best configuration (`-DNA-`) had the role instruction
  **off**; topicality + narrative + aspects carried the performance.

**Drop-in replacement for the `judger.md` code block** (0–3, trust included; the output-format
tail is removed because guided decoding owns the format — see Change 3):

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

`{intent}`, `{summary}`, `{document}` are filled per candidate exactly as the spec already
describes (full body via `engine.read(cp)` truncated to `max_doc_chars`; no `cp` in the
prompt). The per-field reason/grade instructions now live in the `Verdict` schema (Change 3),
so the prompt needs no "Return ONLY..." tail.

> **Note on `{intent}` richness.** The decomposition (steps 1 and 3 especially) assumes
> `{intent}` is a *rich* need statement — an Analyst interpretation, not a bare keyword query.
> Both the description and narrative fields independently improved accuracy in Thomas et al.
> If the Analyst interpretation handed to the Judger is terse, enriching it is higher-leverage
> than any further prompt tuning.

---

## Change 3 — `Verdict`: field order + grade type (silent-failure risk)

The spec declares `Verdict { grade, reason }` — **grade first**. Under guided JSON decoding the
model fills properties in **schema declaration order**, so a `grade`-first schema emits the
integer *before* generating any justification tokens — the opposite of the reason-then-grade
ordering the rewritten prompt intends. This fails **silently**: the output is valid JSON and
looks correct; you simply don't get the ordering you designed for. **Declare `reason` before
`grade`.**

> Both candidate models are reasoning models (Change 4), so the grade is largely shaped in the
> thinking trace and this ordering matters *less* than it would for a non-reasoning model — but
> it is free to keep `reason` first, and it keeps the surfaced reason honest. Keep it.

**Decoder gotcha to verify:** this relies on the backend preserving *declaration* order. vLLM /
Outlines `guided_json` does. If any layer canonicalizes keys alphabetically, `"grade"` sorts
before `"reason"` (g < r) and you silently get grade-first again regardless of declaration.
Confirm on the deployed stack.

**Drop-in `Verdict`** (replaces the `Judgement{cp,grade,reason}` removal target; constrains to
0–3; carries the rubric and reason guidance in `Field` descriptions where each property is
generated):

```python
from typing import Literal
from pydantic import BaseModel, Field

class Verdict(BaseModel):
    # reason BEFORE grade: under guided JSON decoding the model fills properties in
    # declaration order, so the justification is generated before the grade is committed.
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

`Literal[0, 1, 2, 3]` gives the decoder a clean four-token set and emits a plain int; an
`IntEnum` works equally if named members are preferred. The `model_json_schema()` /
guided-decode wiring the spec describes is unchanged — only the property order and the grade
domain change.

---

## Change 4 — Reasoning-model serving config (both candidate models)

The spec says the Judger is "guided-decoded via `Verdict.model_json_schema()` (the same
json-schema pattern the Analyst uses)." That pattern must be **reasoning-aware** here, because
both models under consideration reason before answering:

- **gpt-oss-120b** (planned) — an open-weight *reasoning* model using the **harmony** format.
  It reasons in an `analysis` channel and emits the answer in a `final` channel, with
  configurable `reasoning_effort` (low/medium/high). Structured Outputs apply to the `final`
  channel.
- **Gemma 4 E2B / E4B** (considered) — also a reasoning family, with configurable **thinking
  modes** and native structured JSON output. (Note: these are the small *edge* sizes — 2B/4B
  effective — see Change 5.)

**Implications:**

1. **The terse one-sentence `reason` is correct; do NOT add a scratchpad/`analysis` field.**
   The four-step decomposition executes in the model's *thinking trace* before the constrained
   JSON; `reason` is only the surfaced justification. (This reverses an earlier consideration
   that assumed a non-reasoning model would need a reasoning field — moot, since both candidates
   reason natively.)
2. **Guided decoding must constrain ONLY the post-thinking output, never the thinking.** If the
   JSON schema is applied to the entire generation (including the `analysis` channel /
   thinking segment), it strangles the reasoning and you lose the decomposition. Verify the
   "Analyst json-schema pattern" scopes the constraint to the `final` channel (gpt-oss) / the
   answer after thinking (Gemma 4), not the whole completion.
3. **Reasoning budget is a quality knob.** For gpt-oss-120b set `reasoning_effort` to
   **medium or high** for judging (accuracy scales with reasoning length); for Gemma 4 enable
   thinking mode. This trades against `judge_concurrency` throughput — worth surfacing as a
   note next to the `[agents.judger]` config so the latency/quality trade is explicit.
4. `[agents.judger].llm` already allows a profile distinct from the Searcher's — keep that;
   it's exactly the seam needed to run a strong judge behind a cheaper query author.

---

## Change 5 — Model choice for the Judger (recommendation)

The two candidates are **not** the same quality tier, and relevance judging is sensitive to the
axis that separates them (model capability). The literature finding is direct: good
UMBRELA-style graded judging needs large models (Farzi & Dietz report GPT-4-class is required
for optimal UMBRELA results).

- **gpt-oss-120b** (~o4-mini-class reasoning) is the appropriate Judger and the right default.
- **Gemma 4 E2B/E4B** are edge models chosen for footprint/latency, not judgment quality. The
  parts of the rewritten prompt most likely to degrade on a 2–4B model are the **subtle** ones:
  the trust-capping (step 3) and holding full-document scope against the cover-biased summary
  without over-anchoring (step 4). Treat them as a **different quality tier requiring
  validation**, not a drop-in swap for gpt-oss-120b. They may be acceptable as a first-pass
  filter, but their grades should not be assumed equivalent.

**Caveat on gpt-oss-120b specifically:** it has been reported to have a relatively high
hallucination rate. The evidence-anchored `reason` (cite a span) is a *weak* verifier — a
hallucination-prone model can fabricate the cited span too. If label trust is critical, the
literature's answer is ensembling (average across `reasoning_effort` settings or across models,
JudgeBlender-style), which buys more than further single-prompt tuning. See **Optional** below.

---

## Affirmations — what to KEEP (do not "improve" these)

- **Pointwise graded judging (one doc per call → `Verdict.grade`) is the right choice for this
  architecture.** The benchmarking literature (Arabzadeh & Clarke) finds pairwise preferences
  align best with *human preference*, but pointwise graded (UMBRELA-style) aligns best with
  *system ranking* — and this system uses grades to drive a rank-order streak and compile a
  per-intent ranked list, which is the system-ranking use case. Pairwise would also break the
  parallel one-doc-per-call design and the streak logic. Do **not** switch to pairwise.
- **No `cp` in the Judger output is correct** — the controller pairs verdicts by the cp it
  asked about; the prompt rewrite never mentions a cp, so there is no transposition surface.
- **Controller-owns-control-flow** (paging, streak, budget, de-dup) is unaffected and correct.

---

## Optional / future (not required for this task)

- **Strict-comparability mode.** Including trust (step 3) means on spammy-but-on-topic
  documents the Judger will grade *lower* than pure-topical TREC DL qrels would — correct for
  an open-web judge, but it will register as disagreement if you benchmark grades directly
  against TREC DL. If a clean apples-to-apples validation run is wanted, expose trust as a
  config flag (or a second prompt variant) and drop step 3 for that run.
- **Validation before trusting labels.** Prompt-paraphrase sensitivity (Thomas et al.) means
  this rewritten prompt **cannot** be assumed to behave like UMBRELA or like the original 0–4
  prompt until checked against gold labels. A small calibration pass on TREC DL (Cohen's κ vs
  qrels, and system-ranking Kendall τ) is cheap insurance. The
  **`github.com/Narabzad/llm-relevance-judgement-comparison`** harness (Arabzadeh & Clarke,
  University of Waterloo — same institution as Cottontail) is close to drop-in for this.
- **Ensembling** (`JudgeBlender`-style) if label stability becomes the bottleneck.
- **Full criteria-based decomposition** (per-query generated rubric, TRUE / Farzi–Dietz style)
  is the strongest-performing direction in the literature but is a heavier, two-stage change
  (generate criteria, then grade against them). The inline 4-step decomposition above captures
  most of the benefit within the existing one-call design; full rubric-generation is a
  candidate for a *later* task if eval shows the inline version underperforming.

---

## Evidence basis

- **Thomas et al., "Large language models can accurately predict searcher preferences"**
  (SIGIR 2024; arXiv:2309.10621) — origin of the Bing prompt. Best config `-DNA-`
  (description + narrative + aspects, role **off**); aspects = topicality + trust; "split into
  steps" CoT; labels shift unpredictably under semantics-preserving paraphrase.
- **Upadhyay et al., UMBRELA** (arXiv:2406.06519) — open reproduction; canonical 0–3 scale.
- **Arabzadeh & Clarke, "Benchmarking LLM-based Relevance Judgment Methods"** (SIGIR 2025;
  arXiv:2504.12558) — pairwise best aligns with human preference; binary/graded (UMBRELA) best
  for system-ranking correlation. Public comparison harness linked above.
- **Farzi & Dietz, "Criteria-Based LLM Relevance Judgments"** (ICTIR 2025; arXiv:2507.09488) —
  criteria decomposition; optimal UMBRELA needs large (GPT-4-class) models.
- **Rahmani et al., LLMJudge / "Judging the Judges"** (arXiv:2408.08896, 2502.13908) — shared
  task; 4-point scale = UMBRELA 0–3 semantics; ensembling (JudgeBlender, arXiv:2412.13268).
- **RULERS** (2026; arXiv:2601.08654) — locked rubrics + extractive, evidence-anchored
  reasoning over free-form rationales; post-hoc score calibration.
- **Model facts** — gpt-oss-120b model card (arXiv:2508.10925): reasoning model, harmony
  channels, configurable reasoning effort, Structured Outputs. Gemma 4 (Google, Apr 2026):
  reasoning family with configurable thinking modes; E2B/E4B = 2B/4B effective edge sizes.

---

## Edit checklist (for Claude Code)

- [ ] Replace the `judger.md` rubric + steps with the Change-2 block (0–3, trust, evidence-anchored, no persona).
- [ ] Replace `Judgement{cp,grade,reason}` target with the Change-3 `Verdict` (`reason` before `grade`; `Literal[0,1,2,3]`).
- [ ] Verify the guided-decode pattern constrains only the post-thinking / `final` output, not the thinking trace.
- [ ] Update all "0-4" references in the spec body + **AC #1, #2** to "0-3"; fix Plan step 2 "Judgement" → "Verdict".
- [ ] Set provisional `relevant_grade_threshold = 2` (0–3 scale), keep `# TODO: decide` flag.
- [ ] Add a config note: `reasoning_effort` (gpt-oss) / thinking mode (Gemma 4) is a quality↔throughput knob under `[agents.judger]`.
- [ ] (Recommendation, non-blocking) default the Judger `[agents.judger].llm` to gpt-oss-120b; treat Gemma 4 E2B/E4B as a validate-first tier.

