---
id: doc-5
title: 'Decision — Searcher wire identity: docno on the wire, cp internal'
type: specification
created_date: '2026-06-21 00:52'
updated_date: '2026-06-21 18:24'
---
> **SUPERSEDED by doc-6 (2026-06-21).** This decision — docno on the wire, cp internal — was reversed in favor of **cp-native identity** (cp on the wire, docno only at the persistence boundary). Kept as the record of the prior decision; see doc-6.

**Status:** accepted (2026-06-21).

Related: docs/indexing.md §3-§5 (cp / sidecar / filtering / fetch), decision doc-4
(indexing model), TASK-5 (the Searcher umbrella and its A/B/C tracks).

## Context

The new-style burrow (doc-4, TASK-6) removed the `:docno` annotation: the unique
internal document id is the `:item` start address `cp`, and the docno (our JSON
`docid`) lives only in the `cp <-> docno` sidecar. The Searcher retrieval side
(`cover_search` / `get_document` / `search_text` / `search_gcl`, and the Python
agent that drives them) was built entirely on `:docno` and must be reframed. This
decision fixes the one question that gates that reframe and the B/C re-spec:
**what document identity crosses the agent <-> engine boundary?**

Today every agent touchpoint is already docno-keyed: results carry `docid`
(search / cover_search / get_document responses), and the agent feeds `docid` back
to read (`get_document {docid}`) and to exclude (`cover_search.exclude_docids`),
then cites docids in its answer.

## Decision

**The agent-facing contract stays docno-keyed; `cp` is an engine-internal identity
the sidecar enables. `cp` never crosses the wire and is never persisted.**

- **Wire / agent (docno).** Requests and responses use the docno string, exactly
  as today: hits carry `docid`; `get_document` takes/returns a `docid`;
  `cover_search.exclude_docids` is a list of docno strings. The agent holds its
  judged set as docnos, persists docnos, and cites docnos. Unchanged.
- **Engine internals (cp).** Inside the engine, documents are keyed on `cp` for
  speed. The sidecar is the translator at the boundary: docno -> cp on the way in,
  cp -> docno on the way out.

## Invariant: cp-only internally, docno only at the boundary

**Internal results and work are keyed on `cp` only.** Ranking results, the
over-fetched candidate set, the exclude post-filter, and the match counts carry
**no docno**. The `cp -> docno` mapping happens **only at the engine boundary, at
emit time, for the results actually returned** -- the `top_k` survivors. The
forward `cp -> docno` lookup is therefore called **O(top_k)** times per query (the
emitted page), never O(candidates), O(matches), or O(over-fetch).

docno crosses into the engine in exactly two narrow inbound spots -- resolving
caller-supplied docnos to `cp` (`exclude_docids -> cp`, `get_document` docid ->
cp) -- and nowhere else. Internally it is `cp` throughout.

Implementation consequence: the internal result type stays cp-keyed (e.g. the
`RankingResult` / a cp struct). Do **not** build a list of docno-carrying hits and
then filter -- that would resolve docnos for over-fetched and excluded candidates
that are about to be dropped. **Filter on `cp` first; attach docno only in the
JSON serializer, to survivors.** docno materialization is bounded by what is
emitted, never by what is scanned.

## How exclusion (post-filter by internal id) works

A docno-facing contract still gets the integer-id speed win, because the engine
resolves the small exclude set once and then operates on `cp`:

1. Resolve `exclude_docids` (docnos) -> a set of `cp` integers via the sidecar
   reverse map -- one lookup per judged doc, bounded by the ISJ budget (tens to a
   few hundred).
2. Rank within **plain `:item`** -- no `:docno` container carve at all.
3. Over-fetch `depth = top_k + |exclude|` so a full page of `top_k` survives.
4. Drop any result whose `cp` is in the exclude-cp set -- an integer hash-set
   membership test (no string compare, no `translate`).
5. Map **only the `top_k` survivors** cp -> docno (sidecar forward) at
   serialization time.
6. `total_matches` / `unjudged_matches` are a byproduct of that same single
   ranking pass (count containers as they close; check `cp` against the exclude
   set) -- not separate enumerations, and integer-only (no docno).

**Cache the resolution.** Because the agent re-sends its growing judged set each
turn (the engine is stateless), the engine **should keep a process-lifetime
`docno -> cp` cache keyed on the open burrow**. `docno -> cp` is immutable for a
static burrow, so the cache is always valid for the life of the opened burrow, and
each judged docno is resolved from the sidecar at most **once per session** rather
than once per turn. It is a pure performance memo (no session / correctness
state), so it does not reintroduce statefulness into the contract.

`get_document` is the symmetric boundary op: docno -> cp -> `txt()->translate`.

This yields both speed wins the model was designed for: ranking never touches the
hyper-frequent docno tokens (the ~85M-posting `shard` carve is gone), and
exclusion is an integer post-filter instead of a GCL containment that grows with
the judged set.

## Revises indexing.md §4

`indexing.md` §4 originally sketched `cp` **on the wire** ("the request carries
exclude as a list of cp integers; results carry per-hit cp"). This decision
supersedes that sketch: **docno stays on the wire; `cp` is internal-only.**
`indexing.md` §4-§5 are updated to match (as part of the retrieval design note), so
the indexing design and this decision agree. Rationale: `cp` is
burrow-instance-local (§3) and a footgun if it reaches a stateless agent or
persisted output; keeping it engine-internal leaves the agent contract and run
output portable and unchanged; and the per-call docno -> cp resolution (cached,
above) is negligible at ISJ scale.

## Consequences / scope

- **A (engine) is redone** on this model: `cover_search` carries the sidecar,
  excludes by `cp` post-filter, emits docno via `cp -> docno` for the returned
  page only, and computes counts as a byproduct of the single pass; `get_document`
  does docno -> cp -> translate. The `cottontail-jsonl-query` CLI and the server
  `/tools/*` open the sidecar and use these; the quarantined query-path tests come
  back as new-model tests.
- **B / C stay docno-keyed**: the B1 contract types, B2 judged set, C1 transport,
  and C2 persisted output are unaffected by the id model and need only light
  updates (note that exclusion / emission are sidecar-backed).
- Detailed engine + contract mechanics live in the retrieval design note (the
  expansion of indexing.md §4-§5); this doc records the decision and the invariant
  above.
