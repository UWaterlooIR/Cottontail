---
id: TASK-39
title: 'isj: add scripts/traceview.py -- human-readable viewer for *.trace.jsonl'
status: Done
assignee:
  - '@claude'
created_date: '2026-07-11 15:20'
updated_date: '2026-07-11 15:29'
labels: []
dependencies: []
ordinal: 53000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The isj run traces (intent-NN.trace.jsonl) are JSONL with huge embedded strings (full system prompts, judged documents, reasoning). jq pretty-prints structure but leaves long strings as one-line \n-escaped blobs, so they are unreadable. Add a small stdlib-only viewer that renders embedded newlines as real newlines, word-wraps long strings, filters by event type, can drop the bulky request field, and can truncate giant strings. Lives at isj/scripts/traceview.py (dev/ops utility, like the top-level build/launch scripts).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 isj/scripts/traceview.py reads a *.trace.jsonl and prints each record with embedded newlines rendered and long strings word-wrapped to --width.
- [x] #2 Supports --type T[,T...] (filter by event type), --no-request (drop the request field), --max-str N (truncate long strings), --width N; stdlib-only, runs under plain python3.
- [x] #3 Handles SIGPIPE/BrokenPipeError cleanly when piped to head/less (no traceback).
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added isj/scripts/traceview.py (stdlib-only; from __future__ import annotations so it runs on the system python 3.9). Renders embedded newlines + word-wraps long strings; flags --width/--type/--max-str/--no-request; compact one-line header per event (type + purpose/turn/query/grade/docno). SIGPIPE set to SIG_DFL so piping to head/less exits 141 with no traceback. Verified on Python 3.9.13 over a real trace.

Discoverability follow-up (owner: hard to know what to filter on): added --list-types (scans the file, prints each event type with counts, a purpose breakdown for llm_call, and a ready-to-copy '--type a,b,c' line), a --help epilog documenting all 11 event types + their meaning, and a warning when --type names a type absent from the file (lists what IS present). Verified on a real trace.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
New human-readable viewer for isj *.trace.jsonl at isj/scripts/traceview.py: renders escaped newlines as real newlines and word-wraps the big embedded strings that make jq output unreadable, with type filtering and a --no-request bulk-dropper. Stdlib-only, runs on plain python3, clean under head/less.
<!-- SECTION:FINAL_SUMMARY:END -->
