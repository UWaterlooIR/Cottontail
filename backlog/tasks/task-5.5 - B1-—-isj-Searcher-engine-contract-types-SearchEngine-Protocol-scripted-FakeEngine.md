---
id: TASK-5.5
title: >-
  B1 — isj: Searcher engine contract types + SearchEngine Protocol + scripted
  FakeEngine
status: Done
assignee:
  - '@claude'
created_date: '2026-06-18 02:17'
updated_date: '2026-06-26 03:31'
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
  exclude (the judged set to skip), window (summary window size in tokens,
  default 75).
- response: total_matches and unjudged_matches (DOCUMENT counts; unjudged = matches minus
  exclude), atom_counts (per query leaf {term, count}, count = total OCCURRENCES),
  results (ranked {rank, score, cp, summary}, summary = the cover-biased extractive
  summary).
The agent holds the judged set and passes it as exclude each call (the engine is
stateless). Judgement grade scale is 0-4 (UMBRELA-aligned).

NOTE ON DEPENDENCIES (why B1 has none yet mirrors A2's shape): B1 carries NO task
dependency — it is pure Python and can be built/tested standalone, mock-only. But its
SearchResponse intentionally mirrors the A1+A2 COMBINED (enriched) response:
total_matches, unjudged_matches, and atom_counts are A2 (TASK-5.2) additions, not part of
A1's base response. Because SearchResponse is extra="forbid" (see the strictness decision),
it therefore will NOT parse an A1-only (base) response — and that is intended: the only
live consumer, HttpSearchEngine (C1), DEPENDS ON A2, so it always speaks the enriched shape.
B1 encodes the FINAL cover_search contract, not an A1-only interim one; do not "relax" it to
match A1 alone.

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
       cp: str
       summary: str                     # cover-biased extractive summary (A1)

   class SearchResponse(BaseModel):
       model_config = ConfigDict(extra="forbid")   # see strictness decision above
       total_matches: int               # documents matching the query (ignores exclude)
       unjudged_matches: int            # matches minus exclude
       atom_counts: list[AtomCount]
       results: list[Hit]

   class Judgement(BaseModel):
       cp: str
       grade: int = Field(ge=0, le=4)   # 0-4 UMBRELA-aligned; out-of-range -> ValidationError
       reason: str

   The per-intent RankedList output type is NOT defined here — deferred to B2.

2. SearchEngine Protocol (isj_agent/engine/base.py) — a typing.Protocol, runtime_checkable,
   so both FakeEngine (B1) and the future HttpSearchEngine (C1) satisfy it STRUCTURALLY:
   - search(self, query: str, *, top_k: int = 10,
            exclude: Sequence[str] = (), window: int = 75) -> SearchResponse
   - read(self, cp: str) -> str | None    (full document body; None if cp unknown)
   These mirror the server tools cover_search and get_document. There is NO judge
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
     SearchResponse batch OR an EngineError to raise — and an optional cp->text map for
     read().
   - Each search() consumes the next script entry: a SearchResponse is returned (after the
     exclude/re-rank step below); an EngineError entry is RAISED (so B2 can test the
     engine-error bounce). Either way the call is recorded (see below). Once the script is
     exhausted, search() returns a DRY response (total_matches=0, unjudged_matches=0, empty
     results) so the loop terminates.
   - Honors exclude on SearchResponse entries: removes any Hit whose cp is in
     exclude from the returned batch, decrements unjudged_matches by the number
     removed, leaves total_matches unchanged (exclusions do not change corpus-wide breadth),
     and re-ranks the surviving Hits 1..N.
   - Records every call's arguments (query, top_k, exclude, window) on a public
     attribute so tests can assert what the controller sent — including for calls that raise.
   - read(cp) returns the mapped text or None (and may raise EngineError if a test
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
- [x] #1 isj_agent/protocol/search.py defines pydantic v2 AtomCount{term,count}, Hit{rank,score,cp,summary}, and SearchResponse{total_matches,unjudged_matches,atom_counts,results}, matching the cover_search response shape (A2).
- [x] #2 isj_agent/protocol/search.py defines Judgement{cp,grade,reason} with grade constrained to 0..4 (grade 5 or -1 raises a pydantic ValidationError); the per-intent RankedList type is NOT defined in B1 (deferred to B2).
- [x] #3 isj_agent/engine/fake.py FakeEngine implements SearchEngine from an ordered list of scripted SearchResponse batches: successive search() calls return successive batches, and once exhausted it returns a dry response (total_matches=0, unjudged_matches=0, empty results).
- [x] #4 FakeEngine honors exclude: Hits whose cp is in exclude are removed from the returned batch, unjudged_matches is decremented by the number removed, total_matches is unchanged, and the surviving Hits are re-ranked 1..N.
- [x] #5 FakeEngine records each search() call's (query, top_k, exclude, window) on a public attribute for test assertions; read(cp) returns the mapped text or None.
- [x] #6 A conformance test confirms FakeEngine satisfies the SearchEngine Protocol (runtime_checkable isinstance); the same Protocol is what HttpSearchEngine will satisfy in C1.
- [x] #7 isj/tests cover type validation (incl. grade 0..4 bounds), FakeEngine ordering and dry-out, exclude handling with unjudged decrement and re-rank, call recording, read, and Protocol conformance; no test contacts a network or an LLM.
- [x] #8 uv sync --project isj succeeds and uv run --directory isj pytest tests/ exits 0.
- [x] #9 isj/README.md documents the engine/ module (SearchEngine Protocol + scripted FakeEngine), the 0-4 grade scale on Judgement, and that B2 tests against FakeEngine while C1 supplies the real HTTP-backed engine.
- [x] #10 SearchResponse round-trips losslessly (SearchResponse.model_validate(x.model_dump()) equals x); a strictness decision is made and documented (recommended ConfigDict(extra='forbid') on SearchResponse so an unexpected server field raises ValidationError instead of being silently dropped).
- [x] #11 isj_agent/engine/base.py defines class EngineError(Exception) with a human-readable message; the SearchEngine Protocol documents that search() and read() MAY raise EngineError to signal any engine-side failure (an invalid query is one case), and there is no Python-side query validation.
- [x] #12 FakeEngine supports scripted errors: a script entry may be an EngineError, and the corresponding search() call raises it (with the call still recorded), so B2 can test the engine-error bounce.
- [x] #13 read() on the SearchEngine Protocol (and FakeEngine.read) carries a docstring/comment stating it is intentionally part of the engine contract for FUTURE use (a possible agent read-tool, and the downstream RAG grounding/Writer step) even though the B2 MVP does not call it; it must NOT be removed as unused. isj/README notes the same.
- [x] #14 isj_agent/engine/base.py defines a runtime_checkable SearchEngine typing.Protocol with search(query, *, top_k=10, exclude=(), window=75) -> SearchResponse and read(cp) -> str | None, mirroring the server's cover_search and get_document tools; the engine has no judge method.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Adopt the embedded plan, with ONE correction: cp is INT (not str), matching the shipped cover_search wire (r["cp"]=addr, an integer), the server exclude parse (vector<addr>), DocnoMap (cp:int), and doc-6. Pure Python in isj/; no C++/network/LLM. Mirror isj_agent/protocol/intents.py style.

1. isj_agent/protocol/search.py (pydantic v2):
   - AtomCount{term:str, count:int}
   - Hit{rank:int, score:float, cp:int, summary:str}
   - SearchResponse{model_config=ConfigDict(extra=forbid); total_matches:int, unjudged_matches:int, atom_counts:list[AtomCount], results:list[Hit]}
   - Judgement{cp:int, grade:int=Field(ge=0,le=4), reason:str}
   (RankedList deferred to B2.)
2. isj_agent/engine/base.py: class EngineError(Exception). @runtime_checkable class SearchEngine(Protocol): search(query:str, *, top_k:int=10, exclude:Sequence[int]=(), window:int=75)->SearchResponse; read(cp:int)->str|None. Both documented MAY raise EngineError; no judge method; read documented as intentional future-use (RAG grounding), not dead code (AC#13).
3. isj_agent/engine/fake.py: FakeEngine(script:list[SearchResponse|EngineError], docs:dict[int,str]|None=None). Public calls list. search(): record (query,top_k,exclude,window); consume next entry -> raise if EngineError else apply exclude (drop Hits whose cp in exclude; decrement unjudged_matches by removed count; total_matches unchanged; re-rank 1..N) and return; dry SearchResponse(0,0,[],[]) once exhausted. read(cp)->docs.get(cp) or None.
4. isj/tests/test_engine.py: grade bounds (4 ok; 5/-1 ValidationError); SearchResponse round-trip (model_validate(model_dump())==x); extra=forbid rejects unknown key; FakeEngine ordering + dry-out; scripted EngineError raises (call recorded); exclude drop+decrement+re-rank; call recording; read text/None; isinstance(FakeEngine(...), SearchEngine). No network/LLM.
5. isj/README.md: engine/ module (Protocol + EngineError + FakeEngine), 0-4 grade scale, pydantic round-trip pattern, read as future-use, B2-vs-C1 split.
GATE: uv sync --project isj; uv run --project isj pytest green.
FORWARD-COMPAT: cp:int <-> C1 SearchResponse.model_validate(resp.json()) (integer cp) + request model_dump() exclude->int array; C2 DocnoMap.docno(cp:int); B2 judged set keyed on cp:int.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
RE-SPEC cp-native (doc-6, 2026-06-21). The contract is cp-keyed: the request `exclude` is a list of cp integers; each Hit carries `cp`; Judgement and the judged set are keyed on cp. SearchResponse keeps total_matches/unjudged_matches/atom_counts/results. docno never enters the agent; it appears only in C2 persistence. Authoritative: doc-6 + TASK-5 umbrella.

Implemented per the embedded plan with cp:int (matching the shipped cover_search wire + DocnoMap + doc-6). Files: isj_agent/protocol/search.py (AtomCount, Hit{cp:int}, SearchResponse{extra=forbid}, Judgement{cp:int, grade 0-4}); isj_agent/engine/base.py (EngineError + runtime_checkable SearchEngine Protocol: search(query,*,top_k,exclude:Sequence[int],window)->SearchResponse, read(cp:int)->str|None, both MAY-raise EngineError, no judge, read documented future-use); isj_agent/engine/fake.py (FakeEngine(script:list[SearchResponse|EngineError], docs:dict[int,str]); records calls; consumes script -> raise/return; exclude drop+decrement+re-rank; dry when exhausted; read). tests/test_engine.py (10 tests): grade bounds, round-trip, extra=forbid, ordering+dry, scripted error raises+recorded, exclude, call recording, read, Protocol isinstance. README documents the engine contract. VERIFIED: uv sync + uv run pytest -> 30 passed (10 new); no network/LLM in tests.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
B1 ships the cp-native engine contract for the Searcher: typed SearchResponse/Hit/AtomCount/Judgement (pydantic v2, cp:int, grade 0-4, SearchResponse extra=forbid), a runtime_checkable SearchEngine Protocol (search/read mirroring cover_search/get_document) + EngineError, and a deterministic scripted FakeEngine (ordered SearchResponse|EngineError script, exclude drop+decrement+re-rank, call recording, dry-out). Corrected cp str->int vs the embedded sketch to match the shipped wire. Verified by 10 new tests (uv pytest green, no network/LLM). B2 tests against FakeEngine; C1 supplies the real HTTP engine.
<!-- SECTION:FINAL_SUMMARY:END -->
