---
id: TASK-28
title: >-
  cover_rewrite: wrap multi-word phrases in (materialize ...) — Charlie's
  operator kills the phrase re-drive blow-up
status: To Do
assignee: []
created_date: '2026-07-03 13:20'
updated_date: '2026-07-03 13:35'
labels: []
dependencies: []
priority: high
ordinal: 42000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Quoted multi-word phrases OR'd into cover facets are the documented FollowedBy pathology (docs/design/phrase-search-performance-and-proposal.md): a phrase compiles to Containing-over-FollowedBy and is re-driven once per cover probe, blowing up 328-4000x when the phrase's first word is frequent but the phrase is rare. This is what timed out the tiered/multitext arms of the TASK-22 A/B (6 tiers x ~6s each vs the 30s engine client timeout; abandoned requests then piled up on the server).

Upstream already ships the counter-move (merged in the TASK-24 sync): the (materialize X) GCL operator (gcl/materialize.{h,cc}; parseable via gcl/parse.cc) — a lazy hopper that enumerates X ONCE on first touch, snapshots to an array, and answers all later probes by binary search, eliminating the re-drive multiplier. Charlie's own ai/improvements.md 'Lazy Materialization' note shows exactly this manual fix on exactly our query shape. His experimental auto-optimizer (gcl/optimizer.*, default-off) targets a different shape and stays untouched.

VALIDATED 2026-07-04 on the captured A/B killer tier (1M burrow, cold CLI): plain 6.0s -> materialized 1.25s end-to-end with byte-identical results (ranking-phase speedup ~5-20x once ~1s process startup is discounted). (First measurement claimed 43x and was bogus — a wrapping-regex bug made the run fail fast; caught by the parity check. Wrap at token boundaries carefully.)

Scope: app-layer only, in apps/jsonl_core.cc cover_rewrite — no src/ or gcl/ changes, nothing diverges from upstream:
1. Wrap detection is TOKENIZER-based, not whitespace-based: a quoted phrase counts as multi-atom iff the warren tokenizer splits its content into >=2 index atoms. Punctuation-split "words" like "hi-tech" (-> hi, tech) and "u.s.a." (-> u, s, a) compile to FollowedBy chains and are HIGH-RHO phrases in disguise — they MUST be wrapped (Mark's review question, 2026-07-04).
2. A quoted STAR-FREE phrase with >=2 atoms is emitted as (materialize "the phrase") — the parser lowers the quoted phrase inside the operator. A star-carrying phrase's desugared multi-atom form is emitted wrapped: (materialize (>> (# n) (... atoms))) — the existing atoms.size() branch already distinguishes these.
3. A phrase that tokenizes to ONE atom, and bare unquoted tokens (starred or not), are NOT wrapped (nothing to re-drive; and materializing a frequent bare term would snapshot a huge posting for no benefit).
4. cover_leaves/atom_counts run on the ORIGINAL query text and are unaffected; 'materialize' is already in is_gcl_operator? — VERIFY: it is NOT in the is_gcl_operator list (jsonl_core.cc:103) since it's word-shaped; leaf enumeration never sees it (wrapping happens in cover_rewrite output, leaves come from the input) — pin with a test anyway.

Known trade-off (document in code): parallel_cover_ranking workers each build their own hoppers, so each worker materializes its own full-span copy of each phrase — extra CPU, unchanged wall-clock; a shared materialization is a possible later refinement (Charlie's 'substitute bindings' sketch is the upstream direction).

Benefits all three searchers (cover_search, tiered_query_search, multitext_tiered_search). Together with TASK-27 this unblocks the TASK-22 A/B rerun. Branch: claude/ssr-parallel-etc (standing decision).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Wrap detection is TOKENIZER-based: a quoted phrase is wrapped in (materialize ...) iff its content tokenizes to >=2 index atoms — so "hi-tech" and "u.s.a." ARE wrapped (punctuation-split multi-atom) while a true single token is not; desugared star-phrases wrap only their multi-atom (>> (# n) (...)) form; bare unquoted tokens never wrap; the wrap is token-boundary safe (regression: adjacent starred tokens like lipid* "a b" must not glue)
- [ ] #2 Result parity: on a real burrow, wrapped vs unwrapped queries return identical results, totals, and atom_counts for a query set including the captured A/B killer tier and the punctuation cases ("hi-tech", "u.s.a.")
- [ ] #3 Timing: the captured killer tier improves by at least 3x end-to-end on the 1M burrow, recorded in task notes
- [ ] #4 atom_counts/cover_leaves are unaffected (materialize never appears as a term); unit tests cover the wrap shapes, the no-wrap cases, punctuation-split phrases, boundary safety, and parity; bazel //test:all + isj suite green
- [ ] #5 The tiered/multitext request that timed out the A/B completes well under the 30s engine timeout against a live server, recorded in task notes
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Setup
   1.1 Mark TASK-28 In Progress. Current branch claude/ssr-parallel-etc.

2. cover_rewrite: tokenizer-based wrapping of QUOTED phrases (apps/jsonl_core.cc)
   2.1 Space guard first (fixes the glue class once): a tiny emit helper — before appending any '(materialize ...' form, if *out is nonempty and its last char is not whitespace or '(', append ' '. (Regression: input like lipid*\"a b\" without a separator must not emit lipid*(materialize.)
   2.2 Star-free branch of emit_phrase: atoms = tokenizer->split(phrase); if atoms.size() >= 2 emit (materialize \"<phrase>\") via the guard (the parser lowers the quoted phrase inside the operator); else keep today's quoted pass-through. This catches \"hi-tech\" (hi, tech) and \"u.s.a.\" (u, s, a) — punctuation-split multi-atom phrases.
   2.3 Star branch: the existing atoms.size() >= 2 arm's emitted (>> (# n) (... atoms)) gets wrapped as (materialize (>> (# n) (... atoms))); the atoms.size() == 1 arm (bare family atom) stays unwrapped.
   2.4 Export cover_rewrite in jsonl_core.h (it is currently file-internal) so unit tests can assert the REWRITTEN STRING shapes directly, not just end behavior.

3. MultiText tier post-pass: wrap the DSL's <> output (Mark, 2026-07-04: 'Both')
   3.1 New exported helper materialize_followed_by(s_expression) -> string: a small recursive-descent walk over Mt's well-formed prefix output (balanced parens, quoted strings opaque). Rule: wrap the OUTERMOST pathological unit — a (<< X (# n)) whose X contains a (... ...) wraps WHOLE as (materialize (<< X (# n))); a bare (... ...) group wraps itself. Idempotent: never wrap a node whose parent is already materialize.
   3.2 compile_multitext applies it to each compiled tier before handing tiers to the cascade. The JSON-tiers path is untouched (its quoted phrases are covered by 2.x; its prompt does not teach raw (... ) forms).
   3.3 WRAPPED FOR RANKING ONLY (Mark's review question, 2026-07-04): materialization pays off where a hopper is probed thousands of times across the corpus (the ranking scan); it is a LOSS where hoppers are rebuilt per document. So cover_search/tiered/multitext keep TWO forms per query/tier: the WRAPPED form feeds parallel_cover_ranking, and the UNWRAPPED form feeds the per-document summary re-walk (which rebuilds the hopper up to top_k times — each rebuild of a wrapped form would re-enumerate the FULL shard). Concretely: cover_rewrite returns the unwrapped rewrite as today plus a wrapped variant (or a second wrap pass over it); jsonl_cover_search and jsonl_tiered_query_search rank with wrapped, summarize with unwrapped; compile_multitext produces both.
   3.4 Known cost, documented in code: each parallel_cover_ranking WORKER still materializes its own full-shard copy of each phrase (Materialize is not range-aware) — N threads = N full enumerations, ~1x wall-clock but Nx CPU, and the validated end-to-end numbers already include this. Range-aware or shared materialization needs gcl/ changes (upstream's 'substitute bindings' direction) — out of scope; candidate for the Charlie conversation.

4. Unit tests (test/jsonl.cc)
   4.1 Rewrite shapes via exported cover_rewrite: multi-word phrase -> materialized; \"hi-tech\" and \"u.s.a.\" -> materialized; single-token quoted phrase -> NOT wrapped; starred phrase -> materialized (>> ...); single starred word -> bare atom unwrapped; the lipid*-adjacent glue regression parses (hopper_from_gcl non-null on the rewritten string).
   4.2 Ranking-vs-summary split: a phrase query's SUMMARY output (cover positions/text) is identical to today's, and the summary path demonstrably uses the unwrapped form (assert via the exported rewrite pair). materialize_followed_by shapes: (... a b) wrapped; (<< (... a b) (# 3)) wrapped as a whole; already-materialized input unchanged; non-phrase trees untouched.
   4.3 Behavior parity on the small fixture: cover_search and multitext_tiered_search results identical before/after the change for phrase queries (build both ways? — the 'before' is the old behavior: assert instead that wrapped queries return the SAME results as the semantically-equal unwrapped GCL run through search_gcl/jsonl_query, plus the existing phrase tests all stay green unchanged — they pin current matching behavior).
   4.4 atom_counts unaffected: leaves come from the ORIGINAL text; a wrapped query's atom_counts contain no 'materialize' term.
   4.5 bazel test //test:all + full isj suite.

5. Real-burrow validation (ACs 2/3/5; read-only; throwaway server on a free port — the dev servers stay as Mark left them)
   5.1 Killer-tier parity + timing via CLI on climbmix-1M (already measured by hand: 6.0s -> 1.25s; re-verify through the real cover_rewrite path with the ORIGINAL quoted-phrase tier text, not my hand-wrapped s-expression).
   5.2 Punctuation cases on the burrow: \"hi-tech\" / \"u.s.a.\" parity wrapped vs unwrapped.
   5.3 The captured 6-tier A/B request against a throwaway server: completes well under 30s; record timing in task notes.
6. Finalize: notes, ACs, commit, push (rides PR #9).
<!-- SECTION:PLAN:END -->
