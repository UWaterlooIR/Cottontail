---
id: TASK-28
title: >-
  cover_rewrite: wrap multi-word phrases in (materialize ...) — Charlie's
  operator kills the phrase re-drive blow-up
status: To Do
assignee: []
created_date: '2026-07-03 13:20'
updated_date: '2026-07-03 13:23'
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
