---
id: TASK-23
title: >-
  Star-containing quoted phrase drops punctuation-split words -> query matches
  nothing (e.g. "hi-tech gear*")
status: To Do
assignee: []
created_date: '2026-07-02 18:28'
updated_date: '2026-07-02 19:20'
labels:
  - bug
dependencies: []
references:
  - apps/jsonl_core.cc
priority: medium
ordinal: 37000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A quoted phrase that CONTAINS a word* family marker is decomposed DIFFERENTLY from a
star-free phrase, and the difference is a MATCH-correctness bug: the query silently
matches nothing.

## Observed (live, climbmix-100M-porter)
- "hi-tech gear*"  -> total_matches = 0   (atom_counts: hi-tech=0, gear*=4,228,494)
- "hi-tech" (star-free, for contrast) -> total_matches = 24,433

The star-containing phrase returns ZERO even though "hi-tech" clearly matches on its own.

## Cause
Two different phrase decomposers, inconsistent:
- STAR-FREE phrase: cover_rewrite keeps it quoted; hopper_from_gcl -> expand_phrases ->
  tokenizer->split (FOLD + punctuation SPLIT). So "hi-tech" -> (>> (# 2) (... hi tech)), matches.
- STAR-CONTAINING phrase: cover_rewrite's emit_phrase (apps/jsonl_core.cc) splits on WHITESPACE
  and passes each non-star word to emit_cover_term RAW (no tokenizer split). So "hi-tech gear*"
  -> (>> (# 2) (... hi-tech porter:gear)); the atom "hi-tech" is featurize("hi-tech") = 0 postings
  (the index split it into hi + tech), so the adjacency can never fire -> 0 matches.

Same failure for a capitalized word in a star phrase (case not folded): e.g. "Dog sled*".

## Fix direction
Make star-containing phrase decomposition tokenizer-normalize its NON-star words the same way a
star-free phrase already is. Per whitespace word in emit_phrase: if trailing * -> stem family
(unchanged); else -> tokenizer->split into the adjacency (fold + punctuation split). Then
"hi-tech gear*" -> (>> (# 3) (... hi tech porter:gear)) and matches. Ideally factor a SINGLE
shared phrase-decomposition helper used by expand_phrases (match, star-free), emit_phrase
(match, star-containing), and cover_leaves (atom_counts).

## Relation to TASK-21
Shares the root cause (whitespace-split + raw per-word) with TASK-21's atom_counts fix, but this
one changes what queries MATCH (results), so it is higher-risk and filed separately. A shared
decomposition helper would fix both consistently. TASK-21 Part 1 fixes the COUNT decomposition;
this task fixes the MATCH decomposition for star-containing phrases.

Key files: apps/jsonl_core.cc (cover_rewrite / emit_phrase / emit_cover_term), src/parse.cc
(expand_phrases), a regression test in test/jsonl.cc.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A quoted phrase containing a word* marker AND a punctuation-split or capitalized word (e.g. "hi-tech gear*", "Dog sled*") compiles so each non-star word is tokenizer-normalized (fold + punctuation split), and the query matches the documents it should -- parity with the star-free phrase's tokenization ("hi-tech gear*" currently returns 0)
- [ ] #2 Star-free and star-containing phrase decomposition are made consistent, ideally via a single shared phrase-decomposition helper used by expand_phrases (src/parse.cc) and emit_phrase (apps/jsonl_core.cc); word* stem-family resolution for star words is unchanged
- [ ] #3 A regression test in test/jsonl.cc builds a porter burrow and asserts a star-containing phrase with a hyphenated/punctuated non-star word matches the expected documents (guards the total_matches=0 regression)
- [ ] #4 bazel test //test:jsonl_test and the isj pytest suite pass
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
## Illustrative comparison (live, climbmix-100M-porter)

The bug is specifically about a NON-star word that contains tokenizer-split punctuation. Hold the
concepts fixed (hi, tech, gear) and vary only the spelling of the word forms:

| query | compiles to | total_matches |
|---|---|---|
| `"hi tech gear"`  | `(>> (# 3) (... hi tech gear))`        | 74 |
| `"hi tech gear*"` | `(>> (# 3) (... hi tech porter:gear))` | 77 (gear* family adds gears/gearing) |
| `"hi-tech gear*"` | `(>> (# 2) (... hi-tech porter:gear))` | **0** <- BUG |

Same three concepts, same trailing `*`, but the hyphenated form returns 0 while the space-separated
form returns 77. The ONLY difference: `emit_phrase` whitespace-splits the star-containing phrase and
passes `hi-tech` RAW, so `featurize("hi-tech") = 0` kills the adjacency; the space-separated `hi` and
`tech` are real tokens and match fine. So the star-in-phrase path is not broken for clean words -- it
breaks precisely when a non-star word needs tokenizer folding/splitting.

The fix is therefore exactly to tokenizer-split (fold + punctuation) the non-star words of a
star-containing phrase, the same way the star-FREE path already does via expand_phrases:
`"hi-tech gear*"` should compile to `(>> (# 3) (... hi tech porter:gear))` and then match like
`"hi tech gear*"` (77).
<!-- SECTION:NOTES:END -->
