---
id: TASK-21
title: >-
  atom_counts reports a false 0 for quoted-phrase leaves that actually match
  (tokenizer normalization mismatch)
status: To Do
assignee: []
created_date: '2026-07-01 03:52'
updated_date: '2026-07-01 03:52'
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

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 atom_counts for a term inside a quoted phrase reflects the tokenizer-normalized feature the phrase match path actually resolves it to, so a phrase leaf that matches documents never reports count 0 due to case (e.g. the quoted phrase "Yellowstone" reports its true nonzero occurrence count)
- [ ] #2 The fix lives in the shared atom-count computation in apps/jsonl_core.cc, so BOTH cover_search and tiered_query_search report corrected counts from the one change; word* family resolution via the stemmer is left unchanged
- [ ] #3 Bare (unquoted) GCL terms are unchanged: a bare capitalized term that genuinely cannot match the lowercased index still reports count 0, so real dead atoms are not masked
- [ ] #4 A regression test in test/jsonl.cc builds a porter burrow containing a capitalized proper noun, confirms a quoted-phrase query matches documents, and asserts its atom_counts entry is greater than 0 and equals the true occurrence count
- [ ] #5 jsonl_explain's df computation (the same raw featurize(atom) pattern) is either fixed the same way or explicitly documented as out of scope with a reason
- [ ] #6 bazel test //test:jsonl_test and the isj pytest suite pass
<!-- AC:END -->
