---
id: TASK-5.5
title: >-
  B1 — isj: Searcher engine contract types + SearchEngine Protocol + scripted
  FakeEngine
status: To Do
assignee: []
created_date: '2026-06-18 02:17'
updated_date: '2026-06-18 04:05'
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
`isj_agent/protocol/search.py` (types), `isj_agent/engine/base.py` (the Protocol +
EngineError), `isj_agent/engine/fake.py` (the scripted FakeEngine); tests in `isj/tests/`.
The `isj_agent/engine/` package already exists (only `__init__.py`).

The in-repo exemplar to copy the style from: `isj_agent/protocol/intents.py` (a pydantic
BaseModel) and `isj_agent/agents/analyst.py` (how a model becomes an LLM JSON-schema and
is validated back). Match that style.

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

## Pydantic v2 — how this project uses it (bake-in; read if unfamiliar)

Pydantic v2 is the data-validation / parsing library (Rust core, package `pydantic-core`;
pinned `pydantic>=2.0` in isj/pyproject.toml). We lean on FOUR operations:
- DECLARE: a model is a `class X(BaseModel)` with typed fields; constraints via `Field(...)`.
- VALIDATE/PARSE untrusted data (esp. an LLM's or a server's JSON) into a typed object:
  `X.model_validate_json(s)` or `X.model_validate(dict)`; raises `pydantic.ValidationError`
  on bad/Out-of-constraint data.
- SERIALIZE to JSON/dict: `obj.model_dump()` / `obj.model_dump_json()`.
- EMIT JSON SCHEMA: `X.model_json_schema()` — handed to the LLM (guided decoding /
  response_format / a tool's argument schema) so output is constrained to the shape, then
  parsed back with the SAME model. One model = single source of truth.

v2 API names (use these, NOT the v1 ones): `model_validate` / `model_validate_json` /
`model_dump` / `model_dump_json` / `model_json_schema`. (v1's `parse_obj` / `.dict()` /
`.json()` / `.schema()` are deprecated — do not use.) Field constraints ride on
`Field(...)`: `ge`/`le` (numeric bounds), `min_length`/`max_length`, `pattern`, defaults.
Optional fields use `T | None` (Python 3.12) with a default, e.g. `x: str | None = None`.

The exemplar (Analyst) shows the round-trip: intents.py declares `Intents`; analyst.py
builds `response_format` from `Intents.model_json_schema()` and parses the reply with
`Intents.model_validate_json(content)`.

Where B1's models get used (two boundaries; B1 only DEFINES them, later tasks consume):
- HTTP boundary (C1): `HttpSearchEngine` will do `SearchResponse.model_validate(resp.json())`
  to turn the C++ server's JSON into a typed object, and `model_dump()` to build the
  request body. The server's JSON contract (A) and these types are the SAME shape, checked
  at runtime.
- LLM boundary (B2): the `judge` tool's argument schema can be derived from
  `Judgement.model_json_schema()` (or a list wrapper for the batch judge) so the model's
  tool-call arguments are constrained to valid judgements.
- Tests (B1): assert `Judgement(grade=5)` raises `ValidationError`; assert `SearchResponse`
  round-trips (`model_dump()` -> `model_validate()` yields an equal object).

Strictness decision (make it and document it): add
`model_config = ConfigDict(extra="forbid")` on `SearchResponse` so a server that adds an
unexpected field fails LOUDLY (catch contract drift) instead of silently dropping it
(`extra="ignore"` is the default). Recommended for the engine response; note the tradeoff
(strictness vs forward-compat).

## Required behavior (the contract)

1. Types (pydantic v2, isj_agent/protocol/search.py), mirroring the cover_search response:

   from pydantic import BaseModel, ConfigDict, Field

   class AtomCount(BaseModel):
       term: str
       count: int                       # total OCCURRENCES of the atom in the corpus

   class Hit(BaseModel):
       rank: int                        # 1-based within this response
       score: float                     # ssr cover-density score
       docid: str
       summary: str                     # cover-biased extractive summary (A1)

   class SearchResponse(BaseModel):
       model_config = ConfigDict(extra="forbid")   # see strictness decision above
       total_matches: int               # documents matching the query (ignores exclude_docids)
       unjudged_matches: int            # matches minus exclude_docids
       atom_counts: list[AtomCount]
       results: list[Hit]

   class Judgement(BaseModel):
       docid: str
       grade: int = Field(ge=0, le=4)   # 0-4 UMBRELA-aligned; out-of-range -> ValidationError
       reason: str

   The per-intent RankedList output type is NOT defined here — deferred to B2.

2. SearchEngine Protocol (isj_agent/engine/base.py) — a typing.Protocol, runtime_checkable,
   so both FakeEngine (B1) and the future HttpSearchEngine (C1) satisfy it STRUCTURALLY:
   - search(self, query: str, *, top_k: int = 10,
            exclude_docids: Sequence[str] = (), window: int = 75) -> SearchResponse
   - read(self, docid: str) -> str | None    (full document body; None if docid unknown)
   These mirror the isj-profile tools cover_search and get_document. There is NO judge
   method on the engine — judging is controller-side state in B2; B1 only defines the
   Judgement type.

   ERROR CHANNEL (engine-delegated errors): also define, in engine/base.py,
   `class EngineError(Exception)` carrying a human-readable message. `search()` (and
   `read()`) MAY raise EngineError to signal ANY engine-side failure — an invalid query the
   C++ engine rejects is just one cause. The contract is: the engine is the source of truth,
   and a caller (B2's controller) handles EngineError generally by feeding str(error) back
   to the model. There is NO Python-side query validation; the engine validates.

3. FakeEngine (isj_agent/engine/fake.py) implementing SearchEngine deterministically from
   a SCRIPT:
   - Constructed with an ordered list of script ENTRIES — each entry is either a scripted
     SearchResponse batch OR an EngineError to raise — and an optional docid->text map for
     read().
   - Each search() consumes the next script entry: a SearchResponse is returned (after the
     exclude/re-rank step below); an EngineError entry is RAISED (so B2 can test the
     engine-error bounce). Either way the call is recorded (see below). Once the script is
     exhausted, search() returns a DRY response (total_matches=0, unjudged_matches=0, empty
     results) so the loop terminates.
   - Honors exclude_docids on SearchResponse entries: removes any Hit whose docid is in
     exclude_docids from the returned batch, decrements unjudged_matches by the number
     removed, leaves total_matches unchanged (exclusions do not change corpus-wide breadth),
     and re-ranks the surviving Hits 1..N.
   - Records every call's arguments (query, top_k, exclude_docids, window) on a public
     attribute so tests can assert what the controller sent — including for calls that raise.
   - read(docid) returns the mapped text or None (and may raise EngineError if a test
     scripts it to). No network, no LLM, fully deterministic.

## Non-goals

- No C++; do not touch apps/ or the engine. No HTTP client (C1). No LLM/agent loop (B2).
- Do NOT define the per-intent RankedList type (B2 owns it).
- The scripted FakeEngine does NOT parse GCL or react to the query content — intentional:
  B2's tests drive the agent with a stub LLM, so query-reactivity is not exercised, and
  real query/cover semantics are validated in C1 against the live engine. (EngineError
  entries are scripted explicitly, not derived from the query.)
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
- [ ] #11 SearchResponse round-trips losslessly (SearchResponse.model_validate(x.model_dump()) equals x); a strictness decision is made and documented (recommended ConfigDict(extra='forbid') on SearchResponse so an unexpected server field raises ValidationError instead of being silently dropped).
- [ ] #12 isj_agent/engine/base.py defines class EngineError(Exception) with a human-readable message; the SearchEngine Protocol documents that search() and read() MAY raise EngineError to signal any engine-side failure (an invalid query is one case), and there is no Python-side query validation.
- [ ] #13 FakeEngine supports scripted errors: a script entry may be an EngineError, and the corresponding search() call raises it (with the call still recorded), so B2 can test the engine-error bounce.
- [ ] #14 read() on the SearchEngine Protocol (and FakeEngine.read) carries a docstring/comment stating it is intentionally part of the engine contract for FUTURE use (a possible agent read-tool, and the downstream RAG grounding/Writer step) even though the B2 MVP does not call it; it must NOT be removed as unused. isj/README notes the same.
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Pure Python in isj/. Adapt as needed. Pydantic patterns: see the section in the
description and the exemplar isj_agent/protocol/intents.py + isj_agent/agents/analyst.py.

1. uv sync --project isj. Mirror the pydantic style in isj_agent/protocol/intents.py.
2. isj_agent/protocol/search.py: AtomCount, Hit, SearchResponse, Judgement exactly as in
   the description (grade: int = Field(ge=0, le=4); SearchResponse with
   ConfigDict(extra="forbid")). Export the names the way intents.py is exported.
3. isj_agent/engine/base.py: from typing import Protocol, runtime_checkable, Sequence.
   Define class EngineError(Exception). @runtime_checkable class SearchEngine(Protocol)
   with search(...) -> SearchResponse and read(docid) -> str | None; document that both
   MAY raise EngineError.
4. isj_agent/engine/fake.py: class FakeEngine. __init__(self,
   script: list[SearchResponse | EngineError], docs: dict[str, str] | None = None). Hold an
   index and a public `calls` list. search() records the call, then consumes the next entry:
   raise it if it is an EngineError, else apply exclude_docids (drop + decrement unjudged +
   re-rank) and return it; a dry response once exhausted. read() looks up docs.
5. isj/tests/test_engine.py:
   - type validation: Judgement(grade=4) ok; grade=5 and grade=-1 raise ValidationError;
     SearchResponse round-trips (assert SearchResponse.model_validate(x.model_dump()) == x);
     with extra="forbid", model_validate of a dict with an unexpected key raises.
   - FakeEngine: batches in order; dry after exhaustion; an EngineError script entry causes
     search() to raise EngineError (and the call is still recorded); exclude_docids removes
     matching Hits, decrements unjudged_matches, leaves total_matches, re-ranks 1..N;
     `calls` records (query, top_k, exclude_docids, window); read() returns text/None.
   - conformance: isinstance(FakeEngine([...]), SearchEngine) is True (runtime_checkable).
   - no test contacts a network or an LLM.
6. uv run --directory isj pytest tests/ -v (green). Update isj/README.md: the engine/
   module (SearchEngine Protocol + EngineError + scripted FakeEngine), the 0-4 grade scale,
   the pydantic round-trip/validation pattern, and that B2 tests against FakeEngine while C1
   supplies the real HTTP-backed engine.
<!-- SECTION:PLAN:END -->
