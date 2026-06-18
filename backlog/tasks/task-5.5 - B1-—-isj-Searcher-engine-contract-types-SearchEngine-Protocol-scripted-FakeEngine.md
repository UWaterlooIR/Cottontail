---
id: TASK-5.5
title: >-
  B1 — isj: Searcher engine contract types + SearchEngine Protocol + scripted
  FakeEngine
status: To Do
assignee: []
created_date: '2026-06-18 02:17'
labels:
  - python
  - isj
  - searcher
dependencies: []
references:
  - backlog/docs/doc-3
  - isj/isj_agent/protocol/intents.py
  - isj/isj_agent/engine
  - isj/README.md
  - isj/pyproject.toml
parent_task_id: TASK-5
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives

Python, in the `isj/` uv project (package `isj_agent`, hatchling build; run
`uv sync --project isj` after changes). NO C++, NO network, NO LLM. New files:
`isj_agent/protocol/search.py` (types), `isj_agent/engine/base.py` (the Protocol),
`isj_agent/engine/fake.py` (the scripted FakeEngine); tests in `isj/tests/`. The
`isj_agent/engine/` package already exists (only `__init__.py`). Match the Analyst's
style: pydantic v2 models in `protocol/` (see `protocol/intents.py`), pytest with no
network.

## Context

The Searcher (task B2, later) is an LLM loop that calls a search engine, reads passages,
judges them, reformulates, and stops. To build and TEST B2 with no C++ engine and no live
server, B1 defines the typed CONTRACT between the Searcher and "an engine" — the
`SearchEngine` Protocol, shaped to the `cover_search` tool — plus the data types that
cross that boundary, plus a deterministic scripted `FakeEngine`. This decouples the
Python agent track from the C++ engine track. The real HTTP-backed engine
(`HttpSearchEngine`) arrives in C1; B2's tests run against `FakeEngine`.

The cover_search contract this mirrors (A1 = TASK-5.1, A2 = TASK-5.2):
- request: query (a GCL cover string that MAY use the word* family marker), top_k,
  exclude_docids (the judged set to skip), window (summary window size in tokens,
  default 75).
- response: total_matches and unjudged_matches (DOCUMENT counts; unjudged = matches minus
  exclude_docids), atom_counts (per query leaf {term, count}, count = total OCCURRENCES),
  results (ranked {rank, score, docid, summary}, summary = the cover-biased extractive
  summary).
The agent holds the judged set and passes it as exclude_docids each call (the engine is
stateless). Judgement grade scale is 0-4 (UMBRELA-aligned).

## Required behavior (the contract)

1. Types (pydantic v2, isj_agent/protocol/search.py), mirroring the cover_search response:
   - AtomCount   { term: str, count: int }
   - Hit         { rank: int, score: float, docid: str, summary: str }
   - SearchResponse { total_matches: int, unjudged_matches: int,
                      atom_counts: list[AtomCount], results: list[Hit] }
   - Judgement   { docid: str, grade: int (constrained 0..4), reason: str }
   The per-intent RankedList output type is NOT defined here — it is deferred to B2
   (coupled to B2's compile step).

2. SearchEngine Protocol (isj_agent/engine/base.py) — a typing.Protocol, runtime_checkable,
   so both FakeEngine (B1) and the future HttpSearchEngine (C1) satisfy it STRUCTURALLY:
   - search(self, query: str, *, top_k: int = 10,
            exclude_docids: Sequence[str] = (), window: int = 75) -> SearchResponse
   - read(self, docid: str) -> str | None    (full document body; None if docid unknown)
   These mirror the isj-profile tools cover_search and get_document. There is NO judge
   method on the engine — judging is controller-side state in B2; B1 only defines the
   Judgement type.

3. FakeEngine (isj_agent/engine/fake.py) implementing SearchEngine deterministically from
   a SCRIPT:
   - Constructed with an ordered list of scripted SearchResponse batches and an optional
     docid->text map for read().
   - Each search() returns the next scripted batch; once the script is exhausted it
     returns a DRY response (total_matches=0, unjudged_matches=0, empty results) so the
     loop terminates.
   - Honors exclude_docids: removes any Hit whose docid is in exclude_docids from the
     returned batch, decrements unjudged_matches by the number removed, leaves
     total_matches unchanged (exclusions do not change corpus-wide breadth, matching the
     engine), and re-ranks the surviving Hits 1..N.
   - Records every call's arguments (query, top_k, exclude_docids, window) on a public
     attribute so tests can assert what the controller sent.
   - read(docid) returns the mapped text or None. No network, no LLM, fully deterministic.

## Non-goals

- No C++; do not touch apps/ or the engine. No HTTP client (C1). No LLM/agent loop (B2).
- Do NOT define the per-intent RankedList type (B2 owns it).
- The scripted FakeEngine does NOT parse GCL or react to the query content — intentional:
  B2's tests drive the agent with a stub LLM, so query-reactivity is not exercised, and
  real query/cover semantics are validated in C1 against the live engine.
- No proximity/cover/word* logic in Python.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 isj_agent/protocol/search.py defines pydantic v2 AtomCount{term,count}, Hit{rank,score,docid,summary}, and SearchResponse{total_matches,unjudged_matches,atom_counts,results}, matching the cover_search response shape (A2).
- [ ] #2 isj_agent/protocol/search.py defines Judgement{docid,grade,reason} with grade constrained to 0..4 (grade 5 or -1 raises a pydantic ValidationError); the per-intent RankedList type is NOT defined in B1 (deferred to B2).
- [ ] #3 isj_agent/engine/base.py defines a runtime_checkable SearchEngine typing.Protocol with search(query, *, top_k=10, exclude_docids=(), window=75) -> SearchResponse and read(docid) -> str | None, mirroring the isj-profile cover_search and get_document tools; the engine has no judge method.
- [ ] #4 isj_agent/engine/fake.py FakeEngine implements SearchEngine from an ordered list of scripted SearchResponse batches: successive search() calls return successive batches, and once exhausted it returns a dry response (total_matches=0, unjudged_matches=0, empty results).
- [ ] #5 FakeEngine honors exclude_docids: Hits whose docid is in exclude_docids are removed from the returned batch, unjudged_matches is decremented by the number removed, total_matches is unchanged, and the surviving Hits are re-ranked 1..N.
- [ ] #6 FakeEngine records each search() call's (query, top_k, exclude_docids, window) on a public attribute for test assertions; read(docid) returns the mapped text or None.
- [ ] #7 A conformance test confirms FakeEngine satisfies the SearchEngine Protocol (runtime_checkable isinstance); the same Protocol is what HttpSearchEngine will satisfy in C1.
- [ ] #8 isj/tests cover type validation (incl. grade 0..4 bounds), FakeEngine ordering and dry-out, exclude handling with unjudged decrement and re-rank, call recording, read, and Protocol conformance; no test contacts a network or an LLM.
- [ ] #9 uv sync --project isj succeeds and uv run --directory isj pytest tests/ exits 0.
- [ ] #10 isj/README.md documents the engine/ module (SearchEngine Protocol + scripted FakeEngine), the 0-4 grade scale on Judgement, and that B2 tests against FakeEngine while C1 supplies the real HTTP-backed engine.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Pure Python in isj/. Adapt as needed.

1. uv sync --project isj. Mirror the pydantic style in isj_agent/protocol/intents.py.
2. isj_agent/protocol/search.py: AtomCount, Hit, SearchResponse, Judgement
   (grade: int = Field(ge=0, le=4)). Export the names the way intents.py is exported.
3. isj_agent/engine/base.py: from typing import Protocol, runtime_checkable, Sequence.
   @runtime_checkable class SearchEngine(Protocol) with search(...) -> SearchResponse and
   read(docid) -> str | None.
4. isj_agent/engine/fake.py: class FakeEngine. __init__(self, script: list[SearchResponse],
   docs: dict[str, str] | None = None). Hold an index and a public `calls` list. search()
   pops the next batch (or a dry response if exhausted), applies exclude_docids
   (drop + decrement unjudged + re-rank), appends the call args to `calls`, returns it.
   read() looks up docs.
5. isj/tests/test_engine.py:
   - type validation: Judgement(grade=4) ok; grade=5 and grade=-1 raise ValidationError;
     SearchResponse builds and round-trips (model_dump/model_validate).
   - FakeEngine: batches returned in order; dry after exhaustion; exclude_docids removes
     matching Hits, decrements unjudged_matches, leaves total_matches, re-ranks 1..N;
     `calls` records (query, top_k, exclude_docids, window); read() returns text/None.
   - conformance: isinstance(FakeEngine([...]), SearchEngine) is True (runtime_checkable).
   - no test contacts a network or an LLM.
6. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: the engine/
   module (SearchEngine Protocol + scripted FakeEngine), the 0-4 grade scale, and that B2
   tests against FakeEngine while C1 supplies the real HTTP-backed engine.
<!-- SECTION:PLAN:END -->
