---
id: TASK-12
title: >-
  cover_search summary: best K covers (default K=1), not all covers in the
  document
status: Done
assignee:
  - '@claude'
created_date: '2026-06-26 16:37'
updated_date: '2026-06-26 16:52'
labels:
  - server
  - search
dependencies: []
priority: high
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The cover_search per-hit summary (the snippet shown to the agent/user) is built from ALL covers in the matched document. cover_summary (apps/jsonl_core.cc) emits one window per cover, merges overlapping windows, and joins non-contiguous extents with " . . . ". When a document has many covers spread across it, the summary sprawls across nearly the whole document -- noisy to read and large in the agent context.

PARAMETERIZE the summary to the best K covers, with the DEFAULT K=1 (a single focused snippet of about window tokens). K is a per-request knob like top_k/window. K=1 is the common case; K>1 widens the snippet when wanted.

CURRENT: jsonl_cover_search PHASE 2 (apps/jsonl_core.cc, around lines 817-829) walks the query hopper within the container span [cp,cq], collects EVERY cover (p,q), and passes them all to cover_summary(warren, covers, cp, cq, window).

DESIRED: during that same phase-2 walk, keep only the best K covers (no extra corpus pass), then feed those K to the existing cover_summary windowing/merge/join, presented in document order.

BEST COVER (recommended definition; confirm at implementation): the tightest cover -- smallest (q - p) span -- which is also the highest-density, highest-scoring single cover under the ssr 1/(K + q - p) model the ranker already uses; ties broken by document order (earliest). The best K = the K tightest covers.

SAME WINDOWING: keep cover_summary unchanged -- per-cover window max(window, cover_length) centered on the cover, shifted inward at body edges, clamped to body; overlapping windows merge; non-contiguous extents join with " . . . ". For K=1 this is one contiguous snippet; for K>1 the existing merge/join applies to just those K covers.

PARAMETER: a new optional cover_search request field (proposed name summary_covers, default 1) threaded through CoverSpec, the server request parsing (cover_spec_from), and a query-CLI flag; the isj engine/Searcher default is 1. Missing or invalid value falls back to 1.

Relation to TASK-10: smaller per-result summaries (K=1) also shrink the context the Searcher accumulates each search, helping bound context growth -- but the primary goal here is summary QUALITY.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 cover_search summary is built from the best K covers, where K is a new per-request parameter defaulting to 1 (not from all covers). The best K = the K tightest covers (smallest q-p span; ties broken by earliest document order). K=1 yields a single focused snippet.
- [x] #2 The selected K covers are windowed and assembled by the EXISTING cover_summary mechanism (per-cover window max(window, cover_length) centered + edge-shift + body-clamp; overlapping windows merge; non-contiguous extents join with " . . . "), in document order. For K=1 the result is one contiguous snippet.
- [x] #3 The K parameter is plumbed through the cover_search request: a CoverSpec field (default 1) parsed by the server (cover_spec_from) and exposed as a query-CLI flag; the isj engine/Searcher default is 1; a missing or invalid value falls back to 1.
- [x] #4 The change is localized to the cover_search path in apps/jsonl_core.cc -- select the top-K covers during the existing phase-2 walk (e.g. a bounded heap keyed by span), with no extra corpus pass.
- [x] #5 Tests cover K=1 (single-cover snippet) and a K>1 case; bazel test //test:tests //test:jsonl_test //test:jsonl_server_test stays green.
- [x] #6 The new parameter and best-K-covers semantics (default 1) are documented where cover_search/A2 is described, so the contract is not stale.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DECISIONS (user): param name = max_covers; isj is NOT changed (server CoverSpec defaults max_covers=1, so the Searcher gets K=1 with no B1 contract change). Best cover = tightest span (q-p), ties -> earliest position.

1. apps/jsonl_core.h: add `size_t max_covers = 1;` to CoverSpec (next to window).
2. apps/jsonl_core.cc, jsonl_cover_search PHASE 2 (~817-829): after collecting all covers (p,q) in [r.cp,r.cq] in document order, set K = max(1, spec.max_covers); if covers.size() > K, select the K with smallest (span=q-p, then p) via nth_element on a copy, then re-sort the chosen K by p (document order); pass those to the UNCHANGED cover_summary(warren, chosenK, r.cp, r.cq, window). For K=1 -> one contiguous window; K>1 -> existing merge + " . . . " join over just those K. Add a brief comment recording best-K semantics.
3. apps/cottontail-jsonl-server.cc: cover_spec_from gains `s.max_covers = b.value("max_covers", s.max_covers);`. Update describe_json IFF it advertises cover_search params (window/top_k/exclude) -> add max_covers.
4. apps/cottontail-jsonl-query.cc: add --max-covers N (size_t, default 1) -> spec.max_covers; add to usage string.
5. isj: NO change (relies on the server default of 1).
6. test/jsonl.cc: the two-cover separator test (~651-685) -> set max_covers=2 to keep the " . . . " join/merge assertions, AND add a default-K=1 assertion on the same fixture that the summary is a single extent (no " . . . "). Add a focused test: several well-separated covers + default K=1 -> summary length bounded near one window (does not span the whole body). Re-check the window test (~811-838) still holds for a single-cover summary.
7. Docs: docs/cottontail-search-server-spec.md line ~78 (request shape) add "max_covers"? + line ~101 note max_covers selects best-K covers (default 1); docs/cottontail-jsonl-cli-spec.md document --max-covers.

GATE: bazel build the apps; bazel test //test:tests //test:jsonl_test //test:jsonl_server_test green; before/after eyeball of a broad query over the 1M burrow (a known multi-cover doc) to confirm the snippet shrank.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
cover_summary lives at apps/jsonl_core.cc:348; the phase-2 cover-recovery walk that feeds it is in jsonl_cover_search around lines 817-829 (it already iterates covers within [r.cp, r.cq] -- track the min-span cover instead of collecting all). The CoverHit.summary field is what the server and the isj Searcher surface. The best-cover definition (tightest span) matches the ranker density signal; flag it as a small decision to confirm. Verify behavior with a known multi-cover document (e.g. a broad query over the 1M burrow) before/after.

Parameter name summary_covers is a proposal -- confirm at implementation (alternatives: summary_k, max_covers). Selection is top-K by tightness, then re-sorted into document order before windowing so the snippet reads left to right.

IMPLEMENTED. apps/jsonl_core.h: CoverSpec gains size_t max_covers = 1. apps/jsonl_core.cc jsonl_cover_search phase-2: after collecting the document covers, keep K=max(1,max_covers) tightest by (span q-p, then p) via std::nth_element on the collected vector, resize to K, std::sort back to document order, then the UNCHANGED cover_summary builds the snippet. apps/cottontail-jsonl-server.cc cover_spec_from parses max_covers; apps/jsonl_json.cc describe_json advertises cs["max_covers"]. apps/cottontail-jsonl-query.cc: --max-covers N flag (default 1) -> spec.max_covers, usage updated. isj UNCHANGED (server CoverSpec defaults to 1, so the Searcher gets K=1 with no B1 contract change). Invalid/0 -> 1; K>=covers.size() keeps all. Tests: test/jsonl.cc SummaryWindowingAndGap now exercises K=2 (the " . . . " gap + adjacent-merge assertions) and the K=1 default (single extent, no gap, does not reach the doc tail); the window test is single-cover and unaffected. Docs: server spec (request shape + max_covers note), CLI spec sections 4.2/4.3/4.8. GATE: bazel build apps clean; bazel test //test:tests //test:jsonl_test //test:jsonl_server_test green. Before/after on the 1M burrow (cover query bear*): top hit summary 7705 -> 430 chars at default K=1 (single extent) vs ~5.5-8.9 KB with " . . . " joins at max_covers=50 -- ~13-18x smaller, focused on the tightest cover.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
cover_search now builds each result summary from the best K covers (K = a new max_covers request knob, default 1) instead of every cover in the document, so a hit shows one focused snippet centered on its tightest cover rather than a document-spanning sprawl. The K tightest covers (smallest span q-p; ties earliest) are selected during the existing phase-2 walk (std::nth_element, no extra corpus pass), put back in document order, and fed to the unchanged cover_summary (so K>1 still windows/merges/joins). Plumbed through CoverSpec, the server (cover_spec_from + describe_json), and the query CLI (--max-covers); isj is unchanged and gets K=1 via the server default. Verified on the 1M burrow: the top bear* hit summary dropped from 7705 to 430 chars at the K=1 default. Build + the C++ test gate green; the gap/merge test now covers both K=1 and K=2.
<!-- SECTION:FINAL_SUMMARY:END -->
