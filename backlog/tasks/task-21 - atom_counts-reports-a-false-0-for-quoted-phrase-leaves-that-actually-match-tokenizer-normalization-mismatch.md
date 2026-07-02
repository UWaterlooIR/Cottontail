---
id: TASK-21
title: >-
  atom_counts reports a false 0 for quoted-phrase leaves that actually match
  (tokenizer normalization mismatch)
status: To Do
assignee: []
created_date: '2026-07-01 03:52'
updated_date: '2026-07-02 19:17'
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
- [ ] #1 PART 1 (code). In the shared atom_counts computation (apps/jsonl_core.cc: cover_leaves + the atom loop used by BOTH cover_search and tiered_query_search), decompose a quoted phrase by WHITESPACE into words, then PER WORD: a trailing word* resolves to its stem family (unchanged); otherwise normalize the word with warren->tokenizer()->split() (the same case-fold + punctuation split the match path uses) into its true index atom(s). NOT a naive tokenizer->split of the whole phrase -- that would eat the * markers (e.g. turn sled* into exact sled)
- [ ] #2 PART 1. Each resulting atom is a single index feature counted with the cheap idx->count lookup (no phrase walk). A quoted phrase contributes one atom_counts entry per resolved atom: e.g. "Yellowstone" -> yellowstone (nonzero); "hi-tech" -> hi, tech; "u.s.a." -> u, s, a; "dog sled*" -> dog, sled*. A phrase leaf that matches never reports a spurious 0 from case or punctuation
- [ ] #3 PART 1 NON-GOAL (decided): do NOT compute or report a whole-phrase (adjacency) occurrence count -- no walking the phrase hopper to count results. atom_counts stays cheap per-feature index lookups only (a phrase count would be a walk; see docs/design/phrase-search-performance-and-proposal.md)
- [ ] #4 PART 1. Bare (unquoted) terms unchanged (featurized raw), so a genuinely dead bare atom still reports 0 (do not mask real dead atoms); word* stem-family resolution unchanged
- [ ] #5 PART 1. Regression test in test/jsonl.cc: a porter burrow with a capitalized proper noun AND a hyphenated/punctuated term; assert a quoted-phrase query matches, and its atom_counts are the tokenizer atoms with correct nonzero counts (single-word case-folded == that token's occurrence count; punctuated/multi-word -> multiple atom entries)
- [ ] #6 PART 1. jsonl_explain's df computation (same raw featurize pattern) is fixed the same way or explicitly documented out of scope with a reason
- [ ] #7 PART 1. bazel test //test:jsonl_test and the isj pytest suite pass
- [ ] #8 PART 2 (prompts). Inform the searcher agents to only use lowercase, and when they want to consider word forms that contain punctuation (e.g. u.s.a. or hi-tech), that they should quote those words and also search for a collapsed version, e.g. (+ "u.s.a." usa) and (+ "hi-tech" hitech)
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
All tables below are LIVE-VERIFIED on climbmix-100M-porter (default utf8 tokenizer + porter).

## How the index normalizes (the reason for everything below)
- utf8 tokenizer CASE-FOLDS via a Unicode fold table (Yellowstone -> yellowstone) and SPLITS on
  any non-letter/number/mark codepoint, so punctuation (. - / etc.) is a SEPARATOR:
  "hi-tech" -> hi, tech ; "u.s.a." -> u, s, a.
- --stem porter adds a co-located stem feature per word, namespaced "porter:<stem>", only when the
  word actually stems. The porter wrapper lowercases its input first (porter.h), so the stem path
  is case-INSENSITIVE.
- idx->count(feature) is a directory/header lookup (SimpleIdx::count_: locate in the in-memory
  feature directory + read one PstRecord 'n', memoized) -- effectively FREE, not a search.

## Three query-term normalization paths (the crux)
| form | example | resolves to | case | punctuation |
|---|---|---|---|---|
| bare exact | `yellowstone` | featurize(raw) -- ONE feature | SENSITIVE | literal (NOT split) |
| family `word*` | `yellowstone*` | porter stem -> `porter:yellowston` | INSENSITIVE | n/a |
| phrase `"..."` | `"Yellowstone"` | tokenizer split (fold+split) -> `(>> (# N) (...))` | INSENSITIVE | SPLIT |

## "Yellowstone" four ways (total_matches / atom_count)
| query | resolves to | matches | atom_count |
|---|---|---|---|
| `yellowstone` (bare) | featurize("yellowstone") | 89,215 | 260,925 |
| `Yellowstone` (bare) | featurize("Yellowstone") | **0** | 0 |
| `yellowstone*` | porter:yellowston | 89,271 | 261,162 |
| `Yellowstone*` | porter:yellowston (porter lowercases) | 89,271 | 261,162 |
| `"Yellowstone"` (phrase) | fold -> yellowstone | 89,215 | **0** <- BUG |

Only bare-capitalized misses; adding `*`, quoting, OR lowercasing all fix it (three different
mechanisms). The last row is the bug: phrase matches 89,215 docs but atom_count reports 0.

## Punctuation (bare terms silently die; quoting rescues matching but not the count)
| query | index reality | matches | atom_count |
|---|---|---|---|
| `hi-tech` (bare) | index has hi + tech; "hi-tech" is not a token | **0** | 0 |
| `(^ hi-tech stereo)` | dead atom zeros the whole cover (stereo alone = 221,582) | **0** | hi-tech=0, stereo=496,148 |
| `"hi-tech"` (phrase) | `(>> (# 2) (... hi tech))` | 24,433 | **0** <- BUG |
| `u.s.a.` (bare) | index has u,s,a; "u.s.a." not a token | **0** | 0 |
| `"u.s.a."` (phrase) | `(>> (# 3) (... u s a))` | 75,241 | **0** <- BUG |
| `usa` (bare) | a real, punctuation-free token | 1,165,515 | 1,813,792 |

## Stem families and a `*` INSIDE a phrase
| query | resolves to | matches | atom_counts |
|---|---|---|---|
| `(+ dog* sled*)` | porter:dog + porter:sled | 4,106,344 | dog*=37,483,853, sled*=221,829 |
| `"dog sled"` | `(>> (# 2) (... dog sled))` | 4,227 | dog=22,999,296, sled=152,187 |
| `"dog sled*"` | `(>> (# 2) (... dog porter:sled))` | 8,498 | dog=22,999,296, sled*=221,829 |
| `"hi-tech gear*"` | `(>> (# 2) (... hi-tech porter:gear))` | **0** (MATCH bug) | hi-tech=0, gear*=4,228,494 |

`"dog sled*"` is correct today: whitespace-splitting PRESERVES the trailing `*` and the atom loop
resolves it. That is exactly why Part 1 must NOT run a naive `tokenizer->split` on the whole phrase
(it would eat the `*`, turning `sled*` into exact `sled`). The last row (`"hi-tech gear*"` -> 0) is
a MATCH-path correctness bug, filed separately as TASK-23.

## Cost
- Atom (single feature) count = free directory lookup. word* and bare-exact each resolve to ONE
  feature -> already cheap and correct.
- Phrase (adjacency) count = a hopper WALK, not free (see
  docs/design/phrase-search-performance-and-proposal.md) -> the NON-GOAL below.

---

## PART 1 -- fix the atom decomposition (code; cheap; low risk)
In the shared atom_counts helper (apps/jsonl_core.cc: cover_leaves + the atom loop used by BOTH
cover_search and tiered_query_search): whitespace-split a phrase into words, then PER WORD:
- trailing `*` -> stem family (unchanged, e.g. sled* -> porter:sled),
- else -> `warren->tokenizer()->split()` (the SAME fold + punctuation split the match path uses)
  into the true index atom(s).
Each atom is one feature -> the same cheap idx->count. Bare terms and word* stay as they are.
NON-GOAL: never walk the phrase hopper to report a whole-phrase count; atom_counts stays free.

## PART 2 -- what to teach the Search agents (searcher.md, tiered_searcher.md, MultiText/librarian)
Inform the searcher agents to only use lowercase, and when they want to consider word forms that
contain punctuation, e.g. u.s.a. or hi-tech, that they should quote those words and also search for a
collapsed version, e.g. (+ "u.s.a." usa) and (+ "hi-tech" hitech).
<!-- SECTION:NOTES:END -->
