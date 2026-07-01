---
id: TASK-19
title: TieredQuery queryable + cascade execute() (no controller change)
status: To Do
assignee: []
created_date: '2026-06-30 21:48'
updated_date: '2026-06-30 23:34'
labels: []
dependencies:
  - TASK-18
references:
  - docs/design/agent-architecture.txt
priority: medium
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add the second concrete `Queryable` so the architecture's two query types both exist. Depends on the Queryable seam (TASK-18). Because the Controller already calls `queryable.execute(...)` and reads the trace via the descriptor after TASK-18, this task adds a self-contained new class and touches NO controller code.

## Design (agreed in conversation)

**`TieredQuery{tiers: list[str]}`** implements `Queryable`:
- `tool_name = "tiered_query_search"`; schema `{properties: {tiers: {type: array, items: string}}, required: [tiers]}`.
- `from_tool_arguments({"tiers": [...]}) -> TieredQuery(tiers)`.
- `trace_arguments() == {"tiers": self.tiers}` (the descriptor TASK-18 reads).
- `query_string() -> str`: a plain readable string joining the tiers (e.g. the tiers separated by " ; "), for the persisted `RankedEntry.surfacing_query` -- a `str`, never a dict/JSON. (Per-tier surfacing -- recording WHICH tier surfaced each doc -- would require sourcing `surfacing_query` per-Hit, a controller change, so it is DEFERRED; v1 records the whole tiered query uniformly per doc, matching the controller's existing per-query surfacing model.)
- `execute(engine, *, top_k, exclude, window) -> SearchResponse`: run the tiers as a CASCADE.

### execute() semantics -- ALWAYS run every tier; cap only the RESULTS
- `running_exclude = set(exclude)`; `merged = []`; `atoms = {}` (union accumulator).
- For EACH tier GCL, in order (do NOT stop early): `resp = engine.search(tier, top_k=<fetch>, exclude=sorted(running_exclude), window=window)`. Append `resp`'s new docs to `merged` (skip any cp already in `merged`); add those cps to `running_exclude` (cross-tier de-duplication); merge `resp.atom_counts` into `atoms` (UNION).
- Build the merged ranked list in tier order (tighter tiers rank above looser ones), renumber `rank` 1..n, then CAP THE RESULTS to `top_k`. Each result keeps the summary/score from the tier that surfaced it.
- Return one `SearchResponse`:
  - `results` = merged, capped at `top_k`;
  - `atom_counts` = the UNION across all tiers -- present and deterministic on EVERY call, so a `count: 0` unambiguously means a dead atom (typo / shortened stem / stray infix `+`), never an un-run tier. (TASK-20's prompt PART 3 depends on this.)
  - `total_matches` = the SUM of the tiers' `total_matches`. Document it as an UPPER BOUND, NOT a distinct count: the tiers are precise->broad relaxations that overlap heavily, so overlapping docs are double-counted and breadth is overstated. It IS, however, 0 if and ONLY IF every tier is dry -- preserving the "0 = dry" signal the searcher prompt relies on. (Do NOT use max: it undercounts the union, since non-nested tiers each reach docs the others do not. Do NOT use the broadest tier alone: its count can read 0 while a narrower, differently-shaped tier still matched -- a FALSE "dry". The exact union is the distinct-reachable count and is not computed.)
  - `unjudged_matches` aggregated the same way (sum, same upper-bound caveat).

### Why ALL tiers must run every call
The Controller pages by re-calling `execute()` with a grown `exclude` (its `seen` set, controller.py:158-165). If `execute()` stopped once `top_k` results were reached, a refill where an early tier alone fills `top_k` would never run the later tiers -- so their atoms would vanish from `atom_counts`, and the model could not tell a dead atom from an un-run tier. Running all tiers every call (capping only the results) keeps `atom_counts` complete and deterministic; the Controller already captures atom_counts from the first fetch and reuses it (controller.py:171-173), which is correct because every call returns the same complete union.

**Stateless** by design: each `execute()` re-runs the cascade; the Controller's paging (re-calling with a grown `exclude`) deterministically yields the next merged batch. No controller change, no shared state in the queryable.

**v1 is Python-only** over the existing `cover_search` engine call. NO new C++/server endpoint. (A native engine `tiered_ranking` server endpoint is a separate future task.)

**Perf follow-up (not in scope, same fix as above):** re-running all tiers per refill is wasteful. A later optimization materializes/caches the deep merged list once and pages it in memory -- which ALSO runs all tiers once and keeps `atom_counts` complete. Document, do not implement.

## Testing note -- attribute dedup to TieredQuery, not the fake
The existing `FakeEngine` (engine/fake.py) is a FLAT, one-response-per-`search()`-call script: it ignores the query content (returns the next scripted response in order) and applies `_apply_exclude()` to the batch ITSELF. One `execute()` fires N `search()` calls, so a flat fake both (a) forces the script order to track the tier order and (b) does the exclude-filtering itself -- masking whether cross-tier de-dup came from TieredQuery or from the fake's post-filter (AC asserts it is TieredQuery's doing). For the cascade tests, add a small TIER-KEYED fake: it returns a scripted response keyed by the TIER GCL STRING (order-independent) and does NOT auto-apply exclude. Then any de-duplication in the merged output must come from `TieredQuery.execute()`'s own MERGE-SKIP (append a cp only if not already merged) -- which TieredQuery must therefore implement, not rely solely on the engine's exclude.

## Degenerate / base case
A single-tier TieredQuery must behave identically to the equivalent CoverQuery (same results, same merged ranking, same `trace_arguments` shape aside from the tool name). Lock this with a test -- it pins the cascade's base case.

## Out of scope
The TieredSearcher agent and its prompt (TASK-20); any controller/base change; native server-side tiered ranking.

Key files: `isj/isj_agent/protocol/queryable.py` (new TieredQuery), tests under `isj/tests/`, `isj/isj_agent/engine/fake.py` (scripting support if needed).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 TieredQuery implements Queryable with tool name tiered_query_search and a tiers string-array argument
- [ ] #2 execute() runs the tiers as a cascade with cross-tier de-duplication (a cp returned by an earlier tier never reappears) and returns one merged SearchResponse in tier order, capped at top_k
- [ ] #3 cps in the incoming exclude never appear in the results
- [ ] #4 A scripted FakeEngine test drives a TieredQuery end-to-end and asserts dedup, merged ranking, and the controller judged-results payload, with no controller code changed
- [ ] #5 A live end-to-end run of the hand-authored 5-tier Yellowstone cascade returns a merged, de-duplicated ranked list
- [ ] #6 The Controller and BaseSearcher are unchanged (the diff touches only TieredQuery plus tests)
- [ ] #7 TieredQuery exposes the trace descriptor (tool_name tiered_query_search and trace_arguments() returning {"tiers": [...]}) so the generic controller trace and judged-results payload reflect the tiers with no controller change
- [ ] #8 execute() ALWAYS runs every tier (it does not stop early when top_k results are reached); only the returned results list is capped at top_k, while the full tier set determines the merged ranking and the atom_counts
- [ ] #9 atom_counts is the UNION of every tiers atom_counts and is present and deterministic on every execute() call regardless of how many results each tier contributed, so a count of 0 unambiguously means a dead atom and never an un-run tier
- [ ] #10 total_matches and unjudged_matches are aggregated across tiers by sum (a documented upper bound that double-counts overlapping tiers, not a distinct count) and are 0 if and only if every tier is dry
- [ ] #11 The cascade tests use a tier-keyed FakeEngine that returns a scripted response per tier GCL string and does NOT auto-apply exclude, so any cross-tier de-duplication in the merged result is attributable to TieredQuery.execute() (its merge-skip) and not the fake
- [ ] #12 A single-tier TieredQuery returns results identical to the equivalent CoverQuery (the cascade base case is locked by a test)
- [ ] #13 TieredQuery.query_string() returns a plain readable string joining the tiers (never a dict/JSON); RankedEntry.surfacing_query for tiered-surfaced docs records it
<!-- AC:END -->
