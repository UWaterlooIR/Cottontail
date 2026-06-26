---
id: TASK-15
title: 'cottontail-fetch --cp: fetch text by cp and report its docno'
status: Done
assignee:
  - '@claude'
created_date: '2026-06-26 19:52'
updated_date: '2026-06-26 19:56'
labels:
  - isj
  - tooling
dependencies: []
priority: medium
ordinal: 29000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
cottontail-fetch currently goes one way only: docno -> cp -> text. Add the reverse, --cp <cp>, which resolves cp -> docno (via the read-only DocnoMap) and reads cp -> text (via cottontail-jsonl-query --get), printing both. Useful when you have a cp from a search result / trace and want the human-facing docno plus the body. The C++ engine stays cp-only (doc-8); the cp<->docno map is Python-only.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 cottontail-fetch takes exactly one of --docno or --cp (mutually exclusive, one required). --docno behaves as today (prints the text). --cp <int> prints the docno then the text.
- [x] #2 A fetch_by_cp(burrow, cp, query_bin) -> (docno|None, text) function resolves docno via DocnoMap.docno(cp) (None if the cp is not in the map) and reads the body via cottontail-jsonl-query --get <cp>; raises RuntimeError if the cp is not found in the burrow.
- [x] #3 The cp->text subprocess+parse is factored into a shared helper used by both fetch_text (docno path) and fetch_by_cp (cp path); no behavior change to the existing docno path.
- [x] #4 Tests (no network): fetch_by_cp returns (docno, text) for a known cp; main(--cp ...) prints the docno and text; a not-found cp exits non-zero. uv run --directory isj pytest exits 0.
- [x] #5 Docs: the --cp usage is documented wherever cottontail-fetch appears (running-the-search-stack.md and/or the CLI spec).
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
isj/isj_agent/fetch.py: (1) _read_text_by_cp(burrow, cp, query_bin) -> str factored out of fetch_text (the --get subprocess + JSON parse + found check). (2) fetch_text refactored to docno->cp (DocnoMap.cp) then _read_text_by_cp. (3) fetch_by_cp(burrow, cp, query_bin) -> (docno|None, text): docno=DocnoMap.docno(cp), text=_read_text_by_cp. (4) argparse mutually-exclusive group --docno|--cp (type=int), required=True. (5) main: --docno -> print(text); --cp -> print "docno: <docno or (unmapped)>" then the text. (6) module docstring + prog description updated for both directions. Tests in tests/test_fetch.py mirroring the existing monkeypatched-subprocess pattern. Docs: grep for cottontail-fetch and add --cp usage. GATE: uv run --directory isj pytest green.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
IMPLEMENTED in isj/isj_agent/fetch.py. Factored _read_text_by_cp(burrow, cp, query_bin) out of fetch_text (the --get subprocess + JSON parse + found check); fetch_text now does docno->cp (DocnoMap.cp) then _read_text_by_cp (unchanged behavior). Added fetch_by_cp(burrow, cp, query_bin) -> (docno|None, text): docno=DocnoMap.docno(cp), text=_read_text_by_cp. argparse: mutually-exclusive group --docno|--cp (type=int), required=True. main: --docno prints text (as before); --cp prints "docno: <docno or (unmapped)>" then the text (dispatch on args.docno is not None, so cp=0 works). Module docstring + prog description cover both directions. tests/test_fetch.py: fetch_by_cp returns (docno,text); unmapped cp -> docno None; main --cp prints docno+text; not-found cp -> exit 1; neither flag -> argparse error. Docs: cli-spec + indexing.md (sec 5 and sec 6) note the --cp reverse. GATE: uv run --directory isj pytest = 68 passed, 1 skipped. LIVE: cottontail-fetch --cp 23924823 over the 1M burrow -> "docno: shard_00000_48352" + the text.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
cottontail-fetch gained a --cp <cp> mode (the reverse of --docno): it resolves cp -> docno via the read-only DocnoMap and reads cp -> text via cottontail-jsonl-query --get, printing both. --docno and --cp are mutually exclusive (one required); the existing --docno path is unchanged (the cp->text subprocess is now a shared helper). A new fetch_by_cp() returns (docno|None, text). Tests cover the cp path (known cp, unmapped cp -> None docno, main output, not-found, arg validation); docs updated in the cli-spec and indexing.md. Verified live on the 1M burrow.
<!-- SECTION:FINAL_SUMMARY:END -->
