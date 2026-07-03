---
id: TASK-23
title: >-
  Star-containing quoted phrase drops punctuation-split words -> query matches
  nothing (e.g. "hi-tech gear*")
status: Done
assignee: []
created_date: '2026-07-02 18:28'
updated_date: '2026-07-02 19:43'
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
- [x] #1 A quoted phrase containing a word* marker AND a punctuation-split or capitalized word (e.g. "hi-tech gear*", "Dog sled*") compiles so each non-star word is tokenizer-normalized (fold + punctuation split), and the query matches the documents it should -- parity with the star-free phrase's tokenization ("hi-tech gear*" currently returns 0)
- [x] #2 A regression test in test/jsonl.cc builds a porter burrow and asserts a star-containing phrase with a hyphenated/punctuated non-star word matches the expected documents (guards the total_matches=0 regression)
- [x] #3 bazel test //test:jsonl_test and the isj pytest suite pass
- [x] #4 Star-free and star-containing quoted phrases decompose their words identically (same tokenizer case-fold + punctuation split), so equivalent queries match equivalently; word* stem-family resolution for star words is unchanged
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
## Root cause (confirmed in code)
cover_rewrite's emit_phrase (apps/jsonl_core.cc:274-313) handles a STAR-CONTAINING quoted phrase by
whitespace-splitting it and calling emit_cover_term per word. emit_cover_term passes a NON-star word
through RAW (apps/jsonl_core.cc: `*out += t`). So a non-star word that the tokenizer would fold/split
(e.g. "hi-tech", "Dog") becomes a single non-existent atom, and the compiled adjacency
`(>> (# 2) (... hi-tech porter:gear))` can never match -> total_matches = 0. Star-FREE phrases avoid
this because emit_phrase keeps them quoted and parse.cc expand_phrases tokenizes them
(tokenizer->split, fold+split). The two phrase decomposers are inconsistent; only the star-containing
one is wrong.

Scope: cover_search + tiered_query_search only (both call cover_rewrite: lines ~824 and ~943).
cover_rewrite is file-local (not in jsonl_core.h, no test/other callers), so the signature change is
contained to this file. The direct search_gcl path (hopper_from_gcl only, no cover_rewrite) does not
do word* stemming at all and is out of scope.

## The fix
Make emit_phrase tokenize its NON-star words exactly as the star-free path does, and size the window
by the TOTAL number of resulting atoms.

### Step 1 -- thread the tokenizer into cover_rewrite
emit_phrase needs the warren tokenizer (cover_rewrite currently gets only the stemmer). Add a
`std::shared_ptr<Tokenizer> tokenizer` parameter:
- `bool cover_rewrite(const std::string &gcl, std::shared_ptr<Stemmer> stemmer,
                       std::shared_ptr<Tokenizer> tokenizer, std::string *out, std::string *error)`
- Update the two callers to pass `warren->tokenizer()`:
  - jsonl_cover_search (~824): `cover_rewrite(spec.query, stemmer, warren->tokenizer(), &rewritten, error)`
  - jsonl_tiered_query_search (~943): `cover_rewrite(spec.tiers[i], stemmer, warren->tokenizer(), &rw, &inner)`
Tokenizer is already included/used in this file (warren->tokenizer()->split at line ~185), so no new include.

### Step 2 -- extract a shared decomposition helper (AC#2)
Add a file-local helper that both emit_phrase and (optionally) the star-free path can share:
```
// Decompose a quoted phrase into its ordered GCL atoms: whitespace-split, then per word:
//   trailing word* -> stem family atom (resolve_family_atom); else -> tokenizer->split(word) tokens.
bool phrase_atoms(const std::string &phrase, std::shared_ptr<Stemmer> stemmer,
                  std::shared_ptr<Tokenizer> tokenizer,
                  std::vector<std::string> *atoms, std::string *error);
```
Per word: if it has a valid trailing `*` (reuse emit_cover_term / resolve_family_atom) push the ONE
stem atom; else push each token from `tokenizer->split(word)` (0+ atoms; folds case, splits
punctuation). This is what makes "hi-tech" -> hi, tech and "Dog" -> dog.

### Step 3 -- rebuild emit_phrase on the helper
Replace the per-word loop (lines 295-311) with:
```
std::vector<std::string> atoms;
if (!phrase_atoms(phrase, stemmer, tokenizer, &atoms, error)) return false;
if (atoms.empty()) return true;                       // all-punctuation phrase -> nothing
if (atoms.size() == 1) { *out += atoms[0]; return true; }
*out += "(>> (# " + std::to_string(atoms.size()) + ") (...";   // width = TOTAL atoms
for (const auto &a : atoms) *out += " " + a;
*out += "))";
return true;
```
Key: `(# N)` uses the total atom count AFTER tokenization (e.g. "hi-tech gear*" -> 3 atoms ->
`(>> (# 3) (... hi tech porter:gear))`), matching the star-free path's width convention
(expand_phrases uses tokenizer->split(phrase).size()). Verified target: identical to "hi tech gear*".

### Consistency note (AC#2 wording)
A LITERAL helper shared with parse.cc's expand_phrases is impractical: expand_phrases lives in the
core library and has no stemmer / no porter: namespace knowledge (all `*` resolution happens in the
app-layer cover_rewrite before parse). We instead achieve behavioral consistency by having emit_phrase
tokenize with the SAME warren tokenizer expand_phrases uses -- tokenizer->split of the whitespace words
is token-identical to tokenizer->split of the whole phrase (whitespace is a token separator). Suggest
rewording AC#2 to "consistent tokenization (shared helper within jsonl_core.cc)". OPTIONAL upgrade:
route the star-FREE branch through phrase_atoms too (drop the keep-quoted case) so cover queries have a
single decomposer; low value, slightly higher risk (changes a currently-working path) -- defer.

## Regression test (AC#3) -- test/jsonl.cc
Use the existing build_rows helper (defaults to the utf8 tokenizer, which splits hyphens; pass
stemmer "porter"):
```
const std::vector<std::string> rows = {
  R"({"docid":"h-1","contents":"the hi-tech gear was on sale"})",   // "hi-tech" -> hi, tech ; gear
  R"({"docid":"h-2","contents":"low tech sandals"})",               // negative control
};
ASSERT_TRUE(build_rows("star_phrase", rows, "porter", &burrow, &error)) << error;
// open warren, run cover_search
CoverSpec spec; spec.query = "\"hi-tech gear*\""; spec.top_k = 10;
CoverResponse resp;
ASSERT_TRUE(jsonl_cover_search(w, spec, &resp, &error)) << error;
EXPECT_GT(resp.total_matches, 0);            // was 0 before the fix (the regression guard)
// parity: the space-separated form matches the same doc
spec.query = "\"hi tech gear*\""; CoverResponse resp2;
ASSERT_TRUE(jsonl_cover_search(w, spec, &resp2, &error)) << error;
EXPECT_EQ(resp.total_matches, resp2.total_matches);
```
Model the warren-open + assertions on the existing cover_search / atom_count tests (test/jsonl.cc
~790-808). Optionally add a case-fold case ("Dog sled*" style) if a suitable fixture is cheap.

## Verification
- `bazel test //test:jsonl_test` (new test + existing green) and the isj pytest suite.
- Live sanity on the running 100M server: `"hi-tech gear*"` should go 0 -> ~77 (parity with
  "hi tech gear*"=77); spot-check "Dog sled*" folds; confirm star-free phrases and (+ dog* sled*)
  are unchanged.
- Confirm tiered_query_search benefits (same helper) with a tier containing a hyphenated star phrase.

## Risks / edge cases
- Width change: ensure `(# N)` uses post-tokenization atom count, not word count (the whole point).
- Empty atoms (phrase of only punctuation) -> emit nothing (preserve current behavior).
- Single-atom phrase (e.g. "gear*") -> emit the bare atom, no >> wrapper (preserve).
- Does NOT touch bare terms, word* atoms, or star-free phrases -> those paths and their tests must
  stay green (guard against accidental behavior change).
<!-- SECTION:PLAN:END -->

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

IMPLEMENTED. apps/jsonl_core.cc: added phrase_atoms() (whitespace-split -> per word: a valid word* -> its stem-family atom via emit_cover_term; else -> tokenizer->split, fold+punctuation); rebuilt emit_phrase's star-containing branch on it with width = TOTAL atom count; threaded warren->tokenizer() through cover_rewrite (signature + both callers jsonl_cover_search and jsonl_tiered_query_search). Star-FREE phrases still keep-quoted for the expand_phrases pass, whose tokenizer->split yields the identical tokens (AC#4 consistency). test/jsonl.cc: new TEST(JsonlCover, StarPhraseTokenizesNonStarWords) on a utf8+porter burrow -- "hi-tech gear*" now matches (was 0), equal to "hi tech gear*", and the star-free "hi-tech gear" matches too. Verified: bazel //test:tests + //test:jsonl_test green; isj pytest 118 passed / 1 skipped. Live 100M check deferred (would require restarting the running warm server; the unit test is definitive).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Star-containing quoted phrases no longer drop case/punctuation on the MATCH path. emit_phrase now tokenizer-normalizes its non-star words (new phrase_atoms helper; tokenizer threaded into cover_rewrite), so e.g. "hi-tech gear*" compiles to (>> (# 3) (... hi tech porter:gear)) and matches instead of returning 0 -- benefiting both cover_search and tiered_query_search. Regression test added; //test:tests, //test:jsonl_test, and isj pytest all pass.
<!-- SECTION:FINAL_SUMMARY:END -->
