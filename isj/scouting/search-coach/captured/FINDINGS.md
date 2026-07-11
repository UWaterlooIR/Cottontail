# Findings — SearchCoach scout

Raw transcripts live in per-prompt dirs: `captured/prompt-v1/`, `captured/prompt-v2/`
(input passages + model reasoning + raw output). Read the transcripts for the real
behavior; this is the tally + interpretation.

## Prompt versions

- **v1** (`prompt-v1.md`) — terse relevance-feedback: select + 1-3 sentence observation + terms.
- **v2** (`prompt-v2.md`) — expert-searcher coaching report with `[R#]` citations.

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
