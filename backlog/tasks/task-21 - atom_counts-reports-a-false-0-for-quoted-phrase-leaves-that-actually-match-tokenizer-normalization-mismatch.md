---
id: TASK-21
title: >-
  atom_counts reports a false 0 for quoted-phrase leaves that actually match
  (tokenizer normalization mismatch)
status: To Do
assignee: []
created_date: '2026-07-01 03:52'
updated_date: '2026-07-02 20:32'
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
- [ ] #1 PART 1 (remove). Remove jsonl_explain and its full surface: jsonl_explain(), gcl_terms() (used only by explain), ExplainResult/ExplainLeaf, explain_json(), the --explain CLI mode (cottontail-jsonl-query.cc), and the /tools/explain server endpoint + its describe/schema entry. No remaining code references explain and the build is green
- [ ] #2 PART 1 (remove). Remove the explain tests (JsonlExplain + df_of/leaf_of in test/jsonl.cc; the "explain" schema assertion in test/jsonl_cli.cc) and drop explain from the LIVE reference-spec docs (cottontail-jsonl-cli-spec.md, cottontail-search-server-spec.md, stemming.md, running-the-search-stack.md); archived docs left as-is
- [ ] #3 PART 2 (fix). cover_leaves gains the tokenizer and becomes the single phrase-aware leaf extractor: a quoted phrase is whitespace-split (trailing '*' survives) then PER WORD a word* marker is kept as-is else tokenizer->split (case-fold + punctuation) into true index token(s); bare words kept as-written; operators dropped; deduped. Used by BOTH cover_search and tiered atom loops
- [ ] #4 PART 2 (fix). atom_counts reports the RESOLVED atom as the displayed term -- the folded token for a plain phrase word (yellowstone; hi, tech), the word* marker for a family (NEVER porter:word), the exact string for a bare term -- counted via cheap idx->count. A matching phrase leaf never reports a spurious 0 from case or punctuation
- [ ] #5 PART 2 NON-GOAL. No whole-phrase (adjacency) count and no phrase-hopper walk; atom_counts stays cheap per-feature idx->count lookups
- [ ] #6 PART 2 (fix). Bare (unquoted) terms unchanged (raw featurize -> a genuinely dead bare atom still reports 0); word* resolution unchanged; the porter:-never-shown invariant preserved (a family term stays "bear*")
- [ ] #7 PART 2 (fix). Regression test in test/jsonl.cc (porter burrow): "Yellowstone" -> single leaf yellowstone with count > 0 (was 0); "hi-tech" -> hi & tech both > 0; "u.s.a." -> u,s,a; "dog sled*" -> dog & sled*; bare "Yellowstone" still 0; no "porter:" term ever appears
- [ ] #8 PART 2 (fix). bazel test //test:jsonl_test and //test:tests, and the isj pytest suite, pass
- [ ] #9 PART 3 (prompts). Update the search-agent prompts (searcher.md, tiered_searcher.md, MultiText/librarian) to instruct: only use lowercase; for word forms containing punctuation (e.g. u.s.a., hi-tech) quote those words AND also search for a collapsed version, e.g. (+ "u.s.a." usa) and (+ "hi-tech" hitech)
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Three ordered steps: (1) REMOVE jsonl_explain, (2) FIX atom_counts decomposition, (3) PROMPT updates.
Order matters: removing explain deletes gcl_terms, leaving cover_leaves as the single phrase-aware leaf
extractor that Part 2 then fixes.

## Root cause (the Part 2 bug)
atom_counts (apps/jsonl_core.cc:857 cover_search loop, ~964 tiered loop) iterates cover_leaves(query),
which whitespace-splits a quoted phrase and featurizes each WORD raw. A phrase word the tokenizer would
FOLD (Yellowstone) or SPLIT on punctuation (hi-tech, u.s.a.) is a non-existent feature -> count 0, even
though the phrase matches. Bare terms and word* are already correct.

=====================================================================================================
## PART 1 -- REMOVE jsonl_explain (do FIRST)
Why: jsonl_explain (the "--explain dry-run df / validate-a-query" tool) is superseded by atom_counts
(TASK-17, returned inline by cover_search/tiered) and is never called by the ISJ agents. Removing it
also deletes gcl_terms (its only user), so Part 2's cover_leaves becomes the sole phrase extractor.

Delete:
- apps/jsonl_core.{cc,h}: jsonl_explain(), gcl_terms(), and the ExplainResult / ExplainLeaf types
  (wherever declared).
- apps/jsonl_json.{h,cc}: explain_json() and the "explain" entry in the tool-schema/describe list
  (jsonl_json.cc:226).
- apps/cottontail-jsonl-query.cc: the --explain flag, its mode block (:229-231), the usage line
  (:34), and now-unused includes (explain_json, ExplainResult).
- apps/cottontail-jsonl-server.cc: the svr.Post("/tools/explain", ...) handler (:398-417), the
  ExplainResult using-decl (:29), and "explain" in the file header comment (:7).
- test/jsonl.cc: the JsonlExplain tests (TextDocumentFrequencies, GclParse, the stem_explain test) and
  the df_of/leaf_of helpers.
- test/jsonl_cli.cc: the names.count("explain")==1 assertion (:294) -- drop it and fix the expected
  tool-name set / count.
- Docs (LIVE specs only; leave docs/design/archive/* alone): remove explain from
  cottontail-jsonl-cli-spec.md (the --explain flag row, the --explain usage, and 4.5 explain schema),
  cottontail-search-server-spec.md (/tools/explain + explain_json rows), stemming.md (the
  "--explain stream labeling" notes), and running-the-search-stack.md (the --explain example).

Verify Part 1: the recommended build (//... minus the Boost apps) and //test:tests //test:jsonl_test
//test:jsonl_cli_test are green; a repo grep for "explain" (excluding archive/ and prose uses) is empty.

=====================================================================================================
## PART 2 -- FIX the atom_counts decomposition

### 2a. cover_leaves gains the tokenizer + phrase-aware decomposition
```
// Countable leaves of a GCL expression: drop operators / parens / :tags. A BARE word (including a
// word* marker) is kept AS-WRITTEN; a QUOTED phrase is decomposed like the match path -- whitespace-
// split so a trailing '*' survives, then PER WORD: a word* marker kept as-is, else tokenizer->split
// (case-fold + punctuation) into its true index token(s). Deduped, first-seen order.
std::vector<std::string> cover_leaves(const std::string &gcl,
                                      std::shared_ptr<Tokenizer> tokenizer);
```
- Preserve the trailing '*' by whitespace-splitting a phrase BEFORE tokenizing a word (TASK-23 lesson);
  a valid word* stays a leaf ("sled*") for the loop to resolve, NOT run through tokenizer->split.
- Keep the existing is_gcl_nonterm operator/`:tag` drop and the dedup `seen` set.
- Distinguishes bare-vs-phrase by WHERE a word sits (inside quotes -> tokenize; outside -> raw), so the
  atom loops need no bare/phrase branching.

### 2b. atom loops: signature only, logic UNCHANGED
Pass warren->tokenizer() to cover_leaves at both call sites (~857, ~964). The per-leaf loop is
unchanged: trailing '*' -> resolve_family_atom (term = leaf e.g. "bear*", count = porter:bear); else ->
featurize(leaf) (term = leaf, count = leaf). Because phrase words now arrive folded, this AUTOMATICALLY
yields: "Yellowstone" -> {yellowstone: N}; "hi-tech" -> {hi},{tech}; "u.s.a." -> {u},{s},{a};
"dog sled*" -> {dog},{sled*}. Preserves: bare terms raw (dead atoms still 0), word* counts, and the
porter:-never-shown invariant (family term stays "bear*").
NON-GOAL: no whole-phrase adjacency count / no phrase-hopper walk; atom_counts stays cheap idx->count.

### 2c. tests
test/jsonl.cc AtomCounts (extend, porter burrow): "Yellowstone" -> single leaf "yellowstone",
count == that token's count (was 0); "hi-tech" -> leaves hi & tech both > 0; "u.s.a." -> u,s,a;
"dog sled*" -> dog & sled*; bare "Yellowstone" still 0 (dead-atom preserved); assert no "porter:" term
ever appears. Verify: //test:jsonl_test + //test:tests green; isj pytest green.

=====================================================================================================
## PART 3 -- PROMPTS
Update isj_agent/agents/searcher.md, tiered_searcher.md, and the MultiText/librarian prompt with the
confirmed guidance: only use lowercase; for word forms containing punctuation (e.g. u.s.a., hi-tech)
quote those words AND also search for a collapsed version, e.g. (+ "u.s.a." usa) and (+ "hi-tech" hitech).

=====================================================================================================
## Verification (whole task)
- Unit tests above (Parts 1 & 2).
- Live on the 1M server (:8081): after rebuild, "Yellowstone" phrase atom_count 0 -> nonzero;
  "hi-tech"/"u.s.a." phrase leaves nonzero; bare "Yellowstone" stays 0; /tools/explain is gone (404).

## Risks / edge cases
- Preserve the trailing '*' in a phrase (whitespace-split first) -- no naive whole-phrase tokenize.
- dedup key = the (folded) leaf string.
- No change to bare-term counts, word* counts, the porter:-never-shown invariant, or total_matches.
- Part 1 must leave NO dangling references (query CLI describe list, server tool list, schema tests).
<!-- SECTION:PLAN:END -->

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

## Decisions (the three steps -- remove, fix, prompts -- live in the Implementation Plan)
- Remove jsonl_explain FIRST (YAGNI; superseded by atom_counts; also deletes gcl_terms, leaving
  cover_leaves as the sole phrase-aware extractor).
- atom_counts displays the RESOLVED atom: the folded token for a plain phrase word (yellowstone;
  hi, tech), the `word*` marker for a family (NEVER porter:word), the exact string for a bare term.
  The count is the real feature's cheap idx->count.
- Bare terms and word* unchanged (a genuinely dead bare atom still reports 0). NON-GOAL: never walk
  the phrase hopper for a whole-phrase count.
<!-- SECTION:NOTES:END -->
