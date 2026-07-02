---
id: TASK-21
title: >-
  atom_counts reports a false 0 for quoted-phrase leaves that actually match
  (tokenizer normalization mismatch)
status: To Do
assignee: []
created_date: '2026-07-01 03:52'
updated_date: '2026-07-02 18:41'
labels:
  - bug
dependencies: []
priority: medium
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
atom_counts reports a FALSE count of 0 for a quoted-phrase leaf that actually matches, because the count path featurizes the leaf AS WRITTEN while the query MATCH path tokenizer-normalizes it (lowercasing). A false 0 tells the Searcher/TieredSearcher a productive term is dead.

## Observed (TASK-19 live testing)
A 5-tier Yellowstone cascade over climbmix-100k-porter returned documents matching the quoted phrase "Yellowstone" (rank 1 came from a tier whose tightest facet was "Yellowstone"), yet the response atom_counts listed `Yellowstone` with count 0. The "count 0 => dead atom, fix it first" signal (taught to the model in TASK-17 / TASK-20) was WRONG: the term matches thousands of documents.

## Cause
atom_counts is built by featurizing each leaf AS WRITTEN: cover_leaves(query) -> featurizer->featurize(leaf), with only the word* case routed through the stemmer (apps/jsonl_core.cc, the cover_search atom loop near line 834-846, and the identical tiered loop added by TASK-19). But the indexing/query MATCH path NORMALIZES tokens: the tokenizer lowercases (src/ascii_tokenizer.cc:95), and a QUOTED phrase is matched by tokenizing its content (cover_rewrite keeps a star-free phrase quoted; expand_phrases then tokenizes it). So a capitalized phrase word ("Yellowstone") is stored and matched as its lowercased feature ("yellowstone"), while the atom count featurizes the raw "Yellowstone" and finds 0. The counted feature is not the feature the query resolves the leaf to.

## Precise scope (an important nuance)
The false 0 is specific to QUOTED-PHRASE leaves, which DO lowercase-match. A BARE (unquoted) GCL term is different: the match path featurizes it raw too, so a bare capitalized term genuinely does NOT match a lowercased index -- there both the match and the count are 0, which is CONSISTENT and CORRECT (a real dead atom). So the fix must:
- make a phrase leaf's count reflect the tokenizer-normalized feature the phrase match path actually uses (so a matching phrase never reports 0 due to case), and
- leave bare-term counts alone, so a genuinely dead bare atom still correctly reports 0 (do not mask real dead atoms).

## Shared code -> both tools benefit
The atom loop is shared logic in apps/jsonl_core.cc: fixing it corrects BOTH cover_search and the TASK-19 tiered_query_search (which reuses the same helper). word* family resolution already goes through the stemmer and is correct -- leave it. Also review jsonl_explain's df computation (apps/jsonl_core.cc near line 1162), which uses the same raw featurize(atom) pattern, and fix it the same way or document it as out of scope.

## Not a TASK-19 regression
This predates TASK-19 in cover_search; TASK-19 inherited it by reusing the helper. It is filed separately because the fix is a general atom_counts correctness change, not tiered-specific.

Key files: apps/jsonl_core.cc (the atom_counts loop shared by cover_search + tiered_query_search, and the explain df loop), a regression test in test/jsonl.cc.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
## Mechanism (live-verified on climbmix-100M-porter; utf8 + porter)

CORRECTION of an earlier note: the count path does NOT featurize the whole raw quoted string,
and NOT every phrase leaf reports 0. cover_leaves (jsonl_core.cc:520) splits a phrase's content
on WHITESPACE and emits each WORD as a leaf; the atom loop then counts each leaf via
idx->count(featurize(word)), with a trailing word* routed through the stemmer. So a clean
lowercase multi-word phrase is already counted correctly per word; the 0s appear only for a word
the real tokenizer would FOLD (Yellowstone) or SPLIT on punctuation (hi-tech, u.s.a.).

What already works (single feature -> cheap, correct): a bare lowercase token and a word* stem
family each resolve to ONE feature, and idx->count is a directory/header lookup (SimpleIdx::count_:
locate in the in-memory feature directory + read one PstRecord 'n', memoized) -- effectively free,
NOT a search.

The '*' subtlety (why Part 1 is not a naive tokenizer->split): whitespace-splitting PRESERVES a
trailing '*', and the atom loop resolves it, so "dog sled*" already reports dog (exact) + sled*
(stem family). A naive tokenizer->split of the whole phrase would EAT the '*' (Po punctuation),
turning sled* into exact sled and losing the family. So the decomposition must whitespace-split
FIRST, then per word decide star vs tokenizer-normalize.

Live evidence (cover_search total_matches / atom_counts):
  (+ dog* sled*)   4,106,344   dog*=37,483,853  sled*=221,829   (stem families -- correct today)
  "dog sled"           4,227   dog=22,999,296   sled=152,187    (whitespace ok for clean words)
  "dog sled*"          8,498   dog=22,999,296   sled*=221,829   (whitespace preserves *, star resolved -- correct)
  "hi-tech"           24,433   hi-tech=0                        (WRONG: not tokenizer-split)
  "Yellowstone"       89,215   Yellowstone=0                    (WRONG: not case-folded)
  "u.s.a."            75,241   u.s.a.=0                         (WRONG: not punctuation-split)

## Decision (2026-07-02): two parts, one explicit non-goal

PART 1 (code, cheap): fix the atom decomposition in the shared atom_counts helper. Whitespace-split
the phrase into words, then per word: trailing '*' -> stem family (unchanged); else ->
warren->tokenizer()->split() (the SAME fold + punctuation split the match path uses) into the true
index atom(s). Each atom is one feature -> the same cheap idx->count. A phrase then contributes one
atom_counts entry per resolved atom (e.g. "hi-tech" -> hi, tech; "u.s.a." -> u, s, a;
"Yellowstone" -> yellowstone; "dog sled*" -> dog, sled*).

PART 2 (prompts): teach the Search agents to form better queries (lowercase; quote + OR a
punctuation-collapsed variant for punctuated forms).

NON-GOAL (decided): do NOT report a count of the whole phrase (the adjacency). We will not run the
phrase hopper to count its occurrences for reporting -- that is a walk, not a free lookup (see
docs/design/phrase-search-performance-and-proposal.md). atom_counts stays cheap per-feature lookups;
the searcher learns "these atoms exist / how common", not "how often the phrase occurs"
(total_matches already gives whole-query size).

OUT OF SCOPE here (separate bug -> TASK-23): the same whitespace-split + raw-per-word decomposition
also afflicts the MATCH path for STAR-CONTAINING phrases -- "hi-tech gear*" compiles to
(>> (# 2) (... hi-tech porter:gear)) and matches 0 documents. That changes query RESULTS (higher
risk) and is filed as TASK-23. A single shared phrase-decomposition helper would fix both.
<!-- SECTION:NOTES:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 PART 1 (code). In the shared atom_counts computation (apps/jsonl_core.cc: cover_leaves + the atom loop used by BOTH cover_search and tiered_query_search), decompose a quoted phrase by WHITESPACE into words, then PER WORD: a trailing word* resolves to its stem family (unchanged); otherwise normalize the word with warren->tokenizer()->split() (the same case-fold + punctuation split the match path uses) into its true index atom(s). NOT a naive tokenizer->split of the whole phrase -- that would eat the * markers (e.g. turn sled* into exact sled)
- [ ] #2 PART 1. Each resulting atom is a single index feature counted with the cheap idx->count lookup (no phrase walk). A quoted phrase contributes one atom_counts entry per resolved atom: e.g. "Yellowstone" -> yellowstone (nonzero); "hi-tech" -> hi, tech; "u.s.a." -> u, s, a; "dog sled*" -> dog, sled*. A phrase leaf that matches never reports a spurious 0 from case or punctuation
- [ ] #3 PART 1 NON-GOAL (decided): do NOT compute or report a whole-phrase (adjacency) occurrence count -- no walking the phrase hopper to count results. atom_counts stays cheap per-feature index lookups only (a phrase count would be a walk; see docs/design/phrase-search-performance-and-proposal.md)
- [ ] #4 PART 1. Bare (unquoted) terms unchanged (featurized raw), so a genuinely dead bare atom still reports 0 (do not mask real dead atoms); word* stem-family resolution unchanged
- [ ] #5 PART 1. Regression test in test/jsonl.cc: a porter burrow with a capitalized proper noun AND a hyphenated/punctuated term; assert a quoted-phrase query matches, and its atom_counts are the tokenizer atoms with correct nonzero counts (single-word case-folded == that token's occurrence count; punctuated/multi-word -> multiple atom entries)
- [ ] #6 PART 1. jsonl_explain's df computation (same raw featurize pattern) is fixed the same way or explicitly documented out of scope with a reason
- [ ] #7 PART 1. bazel test //test:jsonl_test and the isj pytest suite pass
- [ ] #8 PART 2 (prompts). Update the search-agent prompts (isj_agent/agents/searcher.md, tiered_searcher.md, and the MultiText/librarian prompt) to instruct: (a) write all query terms in lowercase; (b) for a word form containing punctuation the tokenizer splits on (e.g. u.s.a., hi-tech), QUOTE it AND OR a punctuation-collapsed variant -- e.g. (+ "u.s.a." usa), (+ "hi-tech" hitech) -- because a bare punctuated term is one nonexistent token that matches nothing and zeros any (^ ...) it is in
<!-- AC:END -->
