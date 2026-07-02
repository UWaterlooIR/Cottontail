---
id: TASK-23
title: >-
  Star-containing quoted phrase drops punctuation-split words -> query matches
  nothing (e.g. "hi-tech gear*")
status: To Do
assignee: []
created_date: '2026-07-02 18:28'
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
