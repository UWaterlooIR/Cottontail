---
id: TASK-6.4
title: >-
  Human docno fetch helper (Python): docno -> cp -> text via DocnoMap +
  cottontail-jsonl-query
status: To Do
assignee: []
created_date: '2026-06-25 22:14'
updated_date: '2026-06-25 22:14'
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
- [ ] #1 isj_agent/fetch.py resolves docno->cp via isj_agent.docno_map.DocnoMap (TASK-6.3), then reads the document text by subprocessing cottontail-jsonl-query --burrow <b> --get <cp>, and prints it. An unknown docno (or cp) is a clear not-found message with non-zero exit.
- [ ] #2 Installed as the cottontail-fetch console script ([project.scripts]); the cottontail-jsonl-query binary path comes from config.toml [query].binary (repo-root-relative) with a --query-bin override. No C++ change -- the engine stays cp-only (TASK-5.12 / doc-8).
- [ ] #3 Tests: a unit path stubbing the subprocess over a DocnoMap fixture (round-trip docno->text), plus an auto-skipped e2e against the real cottontail-jsonl-query binary; uv run pytest green.
<!-- AC:END -->
