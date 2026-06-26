---
id: TASK-6.4
title: >-
  Human docno fetch helper (Python): docno -> cp -> text via DocnoMap +
  cottontail-jsonl-query
status: Done
assignee:
  - '@claude'
created_date: '2026-06-25 22:14'
updated_date: '2026-06-26 02:10'
labels:
  - python
  - indexing
dependencies: []
parent_task_id: TASK-6
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A small Python helper that lets a human/external caller fetch a document by **docno** now that the C++ engine is cp-only (TASK-5.12 / doc-8: C++ never reads the cp<->docno map). isj_agent/fetch.py: resolve docno->cp with isj_agent.docno_map.DocnoMap (TASK-6.3), then subprocess cottontail-jsonl-query --burrow <b> --get <cp> to read the text, and print it. Console script cottontail-fetch (mirrors cottontail-index). Binary path from config.toml [query].binary (+ --query-bin override). NO C++ change (the engine stays cp-only). Tests: a unit path stubbing the subprocess + an auto-skipped e2e against the real binary.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 isj_agent/fetch.py resolves docno->cp via isj_agent.docno_map.DocnoMap (TASK-6.3), then reads the document text by subprocessing cottontail-jsonl-query --burrow <b> --get <cp>, and prints it. An unknown docno (or cp) is a clear not-found message with non-zero exit.
- [x] #2 Installed as the cottontail-fetch console script ([project.scripts]); the cottontail-jsonl-query binary path comes from config.toml [query].binary (repo-root-relative) with a --query-bin override. No C++ change -- the engine stays cp-only (TASK-5.12 / doc-8).
- [x] #3 Tests: a unit path stubbing the subprocess over a DocnoMap fixture (round-trip docno->text), plus an auto-skipped e2e against the real cottontail-jsonl-query binary; uv run pytest green.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented isj_agent/fetch.py: fetch_text(burrow, docno, query_bin) resolves docno->cp via DocnoMap (TASK-6.3) then subprocesses cottontail-jsonl-query --burrow <b> --get <cp> --format jsonl and returns out['text']; unknown docno -> KeyError; query failure/not-found -> RuntimeError. main(): cottontail-fetch --burrow --docno [--config --query-bin]; unknown docno -> 'error: unknown docno' + exit 1. Query binary from config.toml [query].binary (repo-root-relative) + --query-bin override; [query] added to config.example.toml/config.toml. [project.scripts] cottontail-fetch = isj_agent.fetch:main. NO C++ change (engine stays cp-only, doc-8). Tests (tests/test_fetch.py): unit (stub subprocess over a DocnoMap fixture; unknown-docno KeyError; main exit 1) + auto-skipped e2e against the real binaries. VERIFIED: uv run pytest -> 20 passed (fetch e2e ran); manual cottontail-fetch round-tripped docno->text and errored+exit1 on an unknown docno.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added the cottontail-fetch console script (isj_agent/fetch.py): resolves docno->cp with DocnoMap and reads the body via the C++ cottontail-jsonl-query --get <cp>, so a human/external caller can fetch by docno even though the C++ engine is cp-only (doc-8). Query-binary path via config.toml [query].binary (+ --query-bin). Verified by isj pytest (20 passed incl. a real-binary e2e) and a manual round-trip.
<!-- SECTION:FINAL_SUMMARY:END -->
