---
id: TASK-14
title: >-
  cover_search: cap the summary to max_words tokens (default 150),
  start-anchored with a truncation marker
status: Done
assignee:
  - '@claude'
created_date: '2026-06-26 18:20'
updated_date: '2026-06-26 18:28'
labels:
  - server
  - search
dependencies: []
priority: high
ordinal: 28000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The cover_search summary can still be enormous even after TASK-12 (best K covers): cover_summary sizes each window as T = max(window, cover_length), so a single wide multi-facet cover expands the window to the whole cover. The TASK-11 E2E produced per-result summaries up to 182,799 chars (a 341 KB response, ~79K tokens in one step) -- window=75 is a FLOOR, not a ceiling.

Add a max_words cap (in TOKENS) that bounds the whole summary. Per the user: when capping, anchor the window at the COVER START (not centered) and append a "..." marker so it is clear the snippet was truncated. Tokens (not literal words) -- the unit the engine and window already use; a token is ~a word for prose. Applying the cap to token extents BEFORE translate() also avoids materializing a 180 KB string.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A new CoverSpec parameter max_words (default 150; 0 = uncapped) caps the WHOLE summary (across the best max_covers windows) to at most max_words tokens.
- [x] #2 When a covers natural window max(window, cover_length) exceeds max_words, the window is anchored at the COVER START (not centered) and shows max_words tokens; an extent whose tail was cut (or whose successor extents were dropped by the total budget) ends with a " ..." truncation marker.
- [x] #3 A tight cover that fits within the cap keeps the existing centered window and has NO marker. max_words=0 disables the cap (pre-task behavior).
- [x] #4 The cap is applied to the token EXTENTS before warren->txt()->translate(), so a huge cover span is never materialized into a string.
- [x] #5 max_words is plumbed through CoverSpec, the server (cover_spec_from + describe_json advertises it), and the query CLI (--max-words, default 150); isj is unchanged and inherits the server default of 150 (same precedent as max_covers).
- [x] #6 Tests in test/jsonl.cc: a wide cover under the default cap -> summary is <= ~max_words tokens, starts at the cover (its first tokens), and ends with " ..."; max_words=0 -> uncapped; a tight cover is unaffected (no marker). bazel test //test:tests //test:jsonl_test //test:jsonl_server_test stays green.
- [x] #7 Docs note max_words: docs/cottontail-jsonl-cli-spec.md (sec 4.3/4.8) and docs/cottontail-search-server-spec.md.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DECISIONS (user): tokens (not literal words); when capping, anchor at the COVER START (not centered) and append a "..." marker; default 150; param name max_words.

1. apps/jsonl_core.h: CoverSpec gains size_t max_words = 150.
2. apps/jsonl_core.cc cover_summary(... , addr W, addr max_words): per cover, T = max(W, cover_len); if (max_words>0 && T>max_words) -> anchor window at the cover start p, extent [p, min(p+max_words-1, body_end)], mark truncated; else keep the existing centered window (truncated=false). Merge windows carrying the truncated flag (OR on merge). Then apply a TOTAL token budget = max_words across merged extents (cut the overflow extent from its start-side end; dropping later extents marks truncated). Build out: join with " . . . ", and append " ..." after any truncated extent. jsonl_cover_search passes spec.max_words.
3. apps/cottontail-jsonl-server.cc cover_spec_from: s.max_words = b.value("max_words", s.max_words). apps/jsonl_json.cc describe_json: cs["max_words"] hint.
4. apps/cottontail-jsonl-query.cc: --max-words N (default 1? NO -- default 150) -> spec.max_words; usage string.
5. test/jsonl.cc: wide-cover cap test (<= ~150 tokens, starts at cover, ends with " ..."); max_words=0 uncapped; tight cover unaffected.
6. Docs: cli-spec + server-spec.
GATE: bazel build apps; bazel test //test:tests //test:jsonl_test //test:jsonl_server_test green; before/after eyeball on the 1M burrow (the wide black-bear cover -> bounded summary ending in ...).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
IMPLEMENTED. apps/jsonl_core.h: CoverSpec gains size_t max_words = 150. apps/jsonl_core.cc cover_summary(..., addr W, addr max_words): per cover, if max(W, cover_len) > max_words -> anchor the window at the cover START [p, min(p+max_words-1, body_end)] and mark it truncated; else the existing centered window. Merge windows (OR the truncated flag); then a TOTAL token budget of max_words across the merged extents (cut the overflow extent, drop the rest, mark truncated). Build out: join with " . . . ", append " ..." after any truncated extent. The cap acts on token EXTENTS before translate(), so a huge cover span is never materialized. jsonl_cover_search passes spec.max_words. apps/cottontail-jsonl-server.cc cover_spec_from parses max_words; apps/jsonl_json.cc describe_json advertises cs["max_words"]; apps/cottontail-jsonl-query.cc adds --max-words N (default 150) + usage. isj unchanged (inherits the server default 150). Tests: test/jsonl.cc MaxWordsCap (a >150-token cover -> summary starts at the cover, omits the far term, ends with " ..."; max_words=0 uncapped & longer). Docs: cli-spec (--cover desc, options table, 4.8) + server-spec (request shape + cover note). GATE: bazel test //test:tests //test:jsonl_test //test:jsonl_server_test green. LIVE (1M burrow, the wide 9-facet black-bear cover): default 150 -> the two wide hits shrank 7256->1017 and 5491->846 chars, each ending " ..."; a hit that already fit (754 chars) is unchanged with no marker; max_words=0 reproduces the old 7256/5491-char sprawl.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
cover_search now caps the whole summary to max_words tokens (new CoverSpec parameter, default 150; 0 = uncapped), fixing the remaining context bloat after TASK-12 (a single wide multi-facet cover could still expand window to the whole document -- up to 182K chars in the TASK-11 E2E, because window is a floor via max(window, cover_length)). When a cover is wider than the cap, the window is anchored at the cover START (not centered) and the cut extent ends with " ..."; tight covers keep the centered window and get no marker. The cap is applied to the token extents before translate(), so a huge span is never materialized. Plumbed through CoverSpec, the server (cover_spec_from + describe), and the query CLI (--max-words); isj inherits the server default of 150. Verified on the 1M burrow: the wide black-bear cover summaries dropped from ~7.3K/5.5K chars to ~1K/850 chars with " ..." markers, while an already-small summary was untouched. Build + the full C++ test gate green.
<!-- SECTION:FINAL_SUMMARY:END -->
