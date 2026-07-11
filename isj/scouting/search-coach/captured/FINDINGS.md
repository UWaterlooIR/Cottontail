# Findings — SearchCoach scout

Raw transcripts live in per-prompt dirs: `captured/prompt-v1/`, `captured/prompt-v2/`
(input passages + model reasoning + raw output). Read the transcripts for the real
behavior; this is the tally + interpretation.

## Prompt versions

- **v1** (`prompt-v1.md` + `schema-v1.json`, guided) — terse relevance-feedback: select + 1-3 sentence observation + terms.
- **v2** (`prompt-v2.md` + `schema-v2.json`, guided) — expert coaching report; FAILED (see below).
- **v3** (`prompt-v3.md`, FREE-TEXT) — coaching report: what's working / hurting / pursue next + "Vocabulary worth pursuing:".
- **v4** (`prompt-v4.md`, FREE-TEXT) — strategist: facet coverage / relevance boundary / next moves (vocab tagged PROVEN vs UNTESTED).

## Run 3 — v3 & v4 free-text (topic 14, intent-00, trace-reconstructed, gpt.oss.120b, temp 0)

Free-text (no guided decoding; selection = handles the report CITES). Fable-5 iteration; see `coach-v3-notes.md`.

| | v3 | v4 |
|---|---|---|
| clean reports | **7/7** | **7/7** |
| parse failures | 0 | 0 |
| harmony leakage | none (q00 raw = clean markdown) | none |
| word count | 302-377 | 395-465 |
| coaching quality | high (names relevant core + shared vocab, diagnoses the sports-medicine drift, flags uncovered facets) | high + more structured (explicit facet-coverage, grade-2/3-vs-1 boundary, PROVEN/UNTESTED vocab) |

**Verdict: free-text works — reliable AND better coaching.** It fixes every v2 failure mode
(no forced field order, no siphoned advice field, no long-prose-in-JSON degradation).

**One real issue — citation consistency.** The model is inconsistent about bracketing
handles: most reports use `[R#]`, but some go entirely bare/bold (`**R26**`): v3 q06 (0
bracketed / 10 bare), v4 q01 (0/19), v4 q02 (0/18). The harness extracts selection via
`\[(R\d+)\]` (brackets only), so those show as "cited 0 / WHIFF" — a diagnostic artifact,
not a coach failure (the reports are good). But it matters in production: selection =
cited handles, so a bare-only report would forward 0 passages.

Fix options: (a) loosen extraction to match `R\d+` bracketed OR bare (validated against the
input handle set, so junk is dropped) -- robust, recommended; and/or (b) reinforce
bracketing in the prompt. The guaranteed floor (top 1-2 by rank) remains the production
backstop for a genuinely under-citing report.

## Run 4 — v5 (self-contained report), topic 14 intent-00

**v5** (`prompt-v5.md`, FREE-TEXT) = v3 + a `## Cited passages` section where the coach
REPRODUCES the cited passages inline (grade + assessor reason), so the report is
self-contained -- no Controller-side handle->summary expansion needed. Also reinforces
SQUARE BRACKETS and caps citations.

- 7/7 clean; ~426-655 words (bigger due to inline passages; still ~700-900 tok/report --
  context-efficient and higher-value than the mechanical top-N dump).
- The `## Cited passages` section WORKS: q00 reproduces `**[R20]** grade 3 - "<reason>"`
  faithfully per cited doc. Achieves the "don't make us mine the passages" goal.
- Bracket drift PERSISTS despite the reinforcement (q04, q05 went bare) -- prompt nudging
  isn't sufficient. But with inline passages this matters less: extraction is now only for
  "which docs were used" logging, not for forwarding text.
- Nuance: the section reproduces the assessor's REASON (judge's words); confirm it also
  carries enough of the passage EXCERPT (the doc's own words) for vocabulary mining.

## Run 5 — v6 (verbatim excerpts), topic 14 intent-00

**v6** (`prompt-v6.md`, FREE-TEXT) = v5 with the `## Cited passages` section rewritten to
demand the EXCERPT copied VERBATIM from the input `summary:` (word for word; no paraphrase,
summarize, shorten, or complete). Fixes v5's failure to show the actual passage text.

- 7/7 clean; `kept_top` on all 7; citations tight (5-7).
- **Faithfulness: 39/40 cited passages reproduce the input summary WORD-FOR-WORD.** The one
  exception is a 2-word title input ("Social Justice") cited inline but not reproduced --
  effectively 100%. The verbatim wording works.
- Cost: reports grew to ~720-1300 words (~1-1.8k tok) because full excerpts are now inline.
  That is the passage text the searcher needs anyway (the mechanical scheme forwards the
  same summaries), so it is comparable context cost + the coaching, and still bounded over
  ~20 turns. v6 is the current best free-text candidate: reliable, faithful, self-contained.

## Run 6 — v6 WIDENED (topic 31 cover + multitext/14)

Confirming v6 holds beyond topic-14 cover. (Filenames now `method-topic-intent`, e.g.
`gcl-cover-14-...`, `multitext-14-...`, after a run.py fix so cover/multitext runs of the
same topic no longer collide.)

- **gcl-cover/31 intent-00** (dense-relevant pool, 1 query): clean, kept_top; but with 12
  grade-3s to reproduce it cited 16 and ran **1461 words**.
- **multitext/14 intent-00** (12 queries, tiered cascade): **12/12 clean, kept_top on all**;
  faithfulness **73/78 (94%) verbatim** (misses are short/title summaries + probe
  sensitivity, not real divergence).

**Verdict:** v6 is reliable and faithful across cover AND multitext, topics 14 and 31.

**Confirmed concern -- report size / over-citation (design's `max_selected` gap).** Citation
count swings 4-23; on dense-relevant or many-marginal sets the coach over-cites and reports
balloon: cover/31 q00 = 1461 words; multitext q07 cited 23; **multitext q10 cited 19 ->
3135 words (~4.5k tokens for ONE turn's feedback)**. Fix in production: enforce a
`max_selected` cap (Controller forwards the top-N cited by grade) and/or firm up the
citation cap in the prompt. Measure before choosing.

## v1 vs v2 head-to-head (topic 14, intent-00, trace-reconstructed, gpt.oss.120b, temp 0)

| | v1 (RF) | v2 (coach report) |
|---|---|---|
| parsed cleanly | **7/7** | **5/7** (q01, q06 failed) |
| failure mode | none | long markdown prose in the guided-JSON string -> `U+202F` whitespace loop / truncation |
| selection size | tight (3-8) | bloated (cited 10-26; q03 cited all 26) |
| kept top-grade doc | 7/7 | 5/7 that parsed |
| coaching quality when it parses | n/a (terse) | high -- e.g. v2 q00 cleanly separates scholarly socio-economic passages from the medical/clinical bulk and names the generic terms pulling junk in |

**Read:** v2's coaching content is genuinely better *when it works*, but the current
guided-JSON-with-a-long-free-text-field setup makes it unreliable (2/7 parse failures,
selection bloat, occasional query-syntax leak). Next prompt version (v3) should force
short PLAIN prose (no markdown/headers/backticks), cap citations, and restate "no query
syntax"; if plain-prose-in-JSON still flakes, move the report out of guided decoding.

## Run 2 — topic 14, intent-00 (gcl-cover), trace-reconstructed, gpt.oss.120b, temp 0

Slices are now the **faithful top-25-by-rank from the trace**, including already-judged
**revisits** with their cached grades (the earlier json-based run under-fed retread-heavy
queries — see Run 1 note below). `gmax` = max grade in the slice; `kept_top` = the coach
kept a doc at that max grade.

| slice | fed | revisits | gmax | selected | grades | kept_top | kept top-2 by rank |
|---|---|---|---|---|---|---|---|
| q00 | 26 | 0  | 3 | 5 | 3,3,2,2,2 | yes | yes |
| q01 | 26 | 1  | 3 | 5 | 3,3,2,2,1 | yes | yes |
| q02 | 25 | 3  | 3 | 3 | 3,3,0     | yes | no |
| q03 | 26 | 20 | 3 | 5 | 3,2,2,2,2 | yes | no |
| q04 | 26 | 24 | 3 | 5 | 3,2,2,2,2 | yes | no |
| q05 | 27 | 1  | 3 | 5 | 3,3,3,2,0 | yes | no |
| q06 | 26 | 3  | 3 | 5 | 3,2,2,2,0 | yes | yes |

## Findings

1. **The coach never drops the best material.** `kept_top = yes` on all 7 slices — it
   always keeps a top-grade (grade-3) doc.
2. **A rank-based floor is the WRONG floor — it would hurt.** The coach frequently skips
   the top-2 *by rank*, correctly:
   - q03 (20/26 revisits): ranks 1–9 are all **grade-1** revisits; the coach ignored them
     and pulled the **grade-3 at rank 52**. A rank floor would have forced two marginal
     docs in and displaced that deep nugget.
   - q02: R1/R2 are grade-2, but the coach chose the two **grade-3s** (ranks 4, 15) plus a
     **grade-0 "trap"** example (the prompt invites an informative non-relevant pick).
   The coach's selection is **grade/informativeness-driven, not rank-driven** — which is
   what we want. Keep any safety **grade-based** (top-1 by grade), which the coach already
   does unprompted; do **not** add the rank floor.
3. **Retreads are handled well.** The heavy-revisit queries (q03, q04) still surfaced the
   deep grade-3 rather than getting stuck on the already-judged grade-1 pile at the top —
   the exact case the json-based scout could not test.
4. **Real (minor) risk: over-aggressive pruning.** q02 forwarded only **3 of 25**, dropping
   ~20 grade-2 relevant docs. The concern is under-forwarding relevant *vocabulary*, not
   dropping the best. If we want a floor, the right one is a **minimum-relevant-forwarded**
   lever, not a rank floor — decide via the A/B.

## Tentative verdict on the design's "guaranteed floor"

Drop the top-1-2-**by-rank** floor from the design; it conflicts with the coach's (good)
relevance-based selection. The coach reliably keeps the top-grade doc on its own. If any
insurance is wanted, make it grade-based, and consider a separate min-relevant-forwarded
knob to bound the aggressive-pruning case. Confirm across more topics/intents (topic 31,
multitext) before finalizing.

## Run 1 note (superseded)

The first pass reconstructed slices from the compiled `intent-NN.json`, which lists each
doc only under the query that first *recorded* it — so retread-heavy queries looked tiny
(5 and 1 passages) because their re-found, already-judged docs were absent. Fixed by
reconstructing from the trace (this run).
