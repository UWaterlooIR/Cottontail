# Indexing a TREC-like document collection

This note describes how the JSONL search stack should index a **TREC-like
document collection** — a set of documents, each with some **text contents** and
a **unique string identifier (the `docno`)** — and, crucially, how we manage the
identity of documents internally so that ranking, filtering, and fetching are
cheap on a **static burrow**.

It is the authoritative design for the JSONL indexing model. The identity model is
**cp-native** (decision **doc-6**, which supersedes doc-5): `cp` — the address
Cottontail assigns each document at insert — is the working identity on the wire,
in the engine, and in the live agent loop; the `docno` is **optional** and appears
only at a boundary (persistence and human/external lookup), via a `cp ↔ docno`
**SQLite map** (§6). The indexing layout (contents + `:item`, no `:docno`) is built
by `cottontail-jsonl-index` (TASK-6.2); the cp-native retrieval cutover
(`cover_search` / `get_document` / exclusion on `cp`) is TASK-5's engine track.
(`docno` is optional in general — a corpus with no docnos yields a cp-only burrow
and no map; the JSONL / TREC path always has docids.)

## 1. The document model

A document is just:

- **`docno`** — a unique string identifier (TREC's "document number"). The raw
  JSON key holding it is configurable; in our JSONL it is the `docid` field.
- **`text`** — the document body. The raw JSON key holding it is configurable; in
  our JSONL it is the `contents` field.

Internally — in code, artifacts, tests, and the specs downstream of the indexer —
we use the canonical terms **`docno`** and **`text`** (decision **doc-7**). Only
the indexer knows the raw JSON field names, supplied as configuration so it works
with any JSON: `IndexOptions.docno_field` (`--docno-field`, default `"docid"`) and
`text_field` (`--text-field`, default `"contents"`).

We index one **JSON object per line** (`*.jsonl` / `*.jsonl.gz`):

```jsonc
{ "docid": "shard_00037_72680", "contents": "Black bear attacks on hikers ..." }
```

Everything else in the row is ignored. One row = one document. (Passage-level
sub-units are out of scope here; the unit of identity is the whole document.)

**Scale.** The target collection (ClimbMix) is **~500 million documents** over
~400 billion tokens, so addresses are 64-bit and any per-document structure (the
SQLite map, §6) and any per-query full scan (the match counts, §4) must be sized
with 500M in mind. The cp-native dev/POC burrow is
`Scrapheap/climbmix-100k-porter.burrow` (~100k docs); a ~1000-shard ClimbMix subset
is ~85M docs, and the full collection is ~6× that.

## 2. What we store in the burrow — text only

For each row we store **only the text**, bracketed by one structural
annotation that marks the document's extent:

```cpp
addr p_body, q_body;
builder->add_text(text, &p_body, &q_body);              // body tokens -> token/text store + inverted index
builder->add_annotation(":item", p_body, q_body, 0.0);  // the document's span [p_body, q_body]
// add_document returns cp (= p_body); the driver emits (docno, cp) to the flat map dump (see §6)
```

We do **not** `add_text(docno)` and we do **not** create a `:docno` annotation.

**Why not index the docno.** `add_text` both stores tokens (so `translate` works)
*and* featurizes them into the inverted index. We never *search* for a docno, so
indexing it is pure waste — and our docnos are pathological for it. `shard_00037_72680`
tokenizes (the `_` splits) into `shard`, `00037`, `72680`; measured on an
**old-style** ClimbMix burrow (one that *did* index the docno), the token `shard`
had **84,594,007** postings (it is in every docno) and `0` ~20 million — the bloat
cp-native avoids by keeping docnos out of the index entirely. Indexing docnos
bloats the index and pollutes content queries for those tokens, all to support an
id we only ever need to *print* or *look up by hand*. So the docno lives outside
the inverted index, in a SQLite map (§6).

`:item` stays: it is the document boundary **and** the ranking container, and it
costs one annotation per document.

## 3. Internal document identity — the `:item` start address

Cottontail lays documents out contiguously in one monotonically increasing
address space, so **every document occupies a unique, non-overlapping address
range**, and its **start address is a unique integer id**. We call it `cp` (the
`:item` container start).

- `ssr_ranking` hands it to us for free: each `RankingResult` carries
  `container_p()` = the `:item` start = `cp` (and `container_q()` = `cq`, the end).
  See `apps/jsonl_core.cc` (cover_search reads `r.container_p()`).
- `cp` is exact and collision-free **by construction** — no string compare, no
  containment ambiguity.

**`cp` is the working identity** (decision doc-6). Ranking and filtering, the
engine, the wire, and the live agent loop all key on `cp`: results carry `cp`, the
agent's judged / exclude set is a set of `cp`, and a candidate is read by the `cp`
it already holds. The `docno` is **not** on this path at all; it is materialized
only at the boundary — when persisting results to disk, and for a human/external
`docno → cp` lookup (§4, §5, §6).

> **Caveat — `cp` is burrow-instance-local.** Addresses are assigned at build time;
> they are stable for the life of a given static burrow but **change if the burrow
> is rebuilt**. So `cp` is the **working** id (valid within one burrow instance —
> the run, the wire, the agent loop) and `docno` is the **persisted** id: the
> rewrite `cp → docno` at the disk boundary (§6) is the discipline that keeps a raw
> `cp` out of any saved artifact. A corpus with no docno has only `cp`, valid for
> that burrow instance — inherent, not a footgun.

## 4. Filtering retrieval results by internal id

The judged/seen set is **client-side** (the burrow is static and stateless — a
read-opened `SimpleWarren` has a null annotator, so we cannot mark documents in
the index, and we keep no server session). The agent holds that set as **`cp`
integers** (the `cp`s it saw in prior results) and sends them as `exclude`;
exclusion is the original ISJ behaviour ("walk down the ranked list, skip what
you've already judged"), realized as a direct **post-rank filter on `cp`**:

1. Rank within the plain `:item` container (no docno carve, no docno tokens
   touched), over-fetching `depth = top_k + |exclude|` so a full page survives.
2. Drop any result whose `cp` is in the exclude-`cp` set (an integer hash-set
   membership test — no `translate`, no string compare, no `docno → cp` lookup).
3. Build the expensive cover summaries only for the survivors and return `top_k`,
   **each hit carrying its `cp`** (no docno — the `cp → docno` rewrite happens
   later, at persistence; §6).

This is exact, cheap, needs no in-burrow state, opens no `docno ↔ cp` map on the
hot path, and avoids the `shard`-token posting lists entirely.

> **The identity split (decision doc-6).** The hot path is **`cp` end to end** —
> the request's `exclude` is a list of **`cp` integers**, ranking / filter / counts
> are `cp`, and each returned hit carries its **`cp`**. No `docno ↔ cp` map is
> opened on the query path and no docno is materialized in the engine. The
> `cp → docno` rewrite happens exactly once, off the hot path, when results / traces
> are written to disk (§6) — the only place a `cp` becomes a portable docno.

The over-fetch is cheap at any scale: the judged set is bounded by the ISJ budget
(tens to a few hundred per intent), so `depth = top_k + |exclude|` stays small even
against 500M documents.

> **Note — match counts come free with ranking; do not pay for them twice.**
> `ssr_ranking` makes a full pass over every cover of the query (it does *not*
> stop early at `top_k`), so it already **visits every matching document**. Exact
> `total_matches`/`unjudged_matches` are therefore the **same cost class as the
> ranking we already do**, and should be computed as a **byproduct of that single
> pass**: count each matching container as the ssr loop closes it (`q > cq`), and
> for `unjudged_matches` check whether the container's `cp` is in the exclude set.
> A2 (TASK-5.2) computes them this way — a byproduct of the one ranking pass, **not**
> separate `(>> :item Q)` enumerations — so the counts are not a separate scaling
> problem under ssr.
>
> The cost of *any* of this is governed by query **selectivity** (the combined
> posting length of the query's atoms / number of covers), not by `top_k`: a broad
> cover led by a hyper-frequent atom is expensive to rank — and equally to count —
> no matter how few results are requested. Exact counts would only become the
> relatively expensive odd-one-out if ranking later adopts a **skipping ranker
> (WAND/MaxScore)** that finds top-k without visiting every match; with ssr that
> does not arise.
>
> The per-atom `atom_counts` signal is cheaper still and entirely separate: it
> reads each query leaf's collection frequency from the index directory
> (`idx()->count(feature)` — an `O(log F)` lookup, cached, no posting-list load or
> document scan), independent of the document match counts above.

## 5. Fetching document text

Given a document's span `(cp, cq)`, the text is `txt()->translate(cp, cq)` (`O(L)`
in the document length). Two access paths, by identity:

- **By `cp` (the working path).** The engine and the agent both hold `cp` (and `cq`)
  from a ranking result, so reading a document is `translate(cp, cq)` directly — no
  docno, no map. This is the ISJ loop's read-a-candidate path.
- **By `docno` (the boundary path).** A human/external caller that holds only a
  **docno** uses the **Python helper** `cottontail-fetch` (TASK-6.4): it resolves
  `docno → cp` with `isj_agent.docno_map.DocnoMap` (read-only SQLite) and then calls
  the C++ get-by-`cp` (`cottontail-jsonl-query --get <cp>`). **The C++ engine itself
  is cp-only and never opens the map** (decision **doc-8**): `docno ↔ cp` lives only
  in Python. Occasional and latency-tolerant; the multi-threaded `cover_search` /
  exclusion path never touches the map either.

## 6. The `cp ↔ docno` map — a SQLite store, off the hot path

The map is **not** on the query path (§4). It exists only for the two boundary
operations — the `cp → docno` rewrite when results/traces are persisted, and the
`docno → cp` lookup for a human/external fetch (§5). So it is a plain **SQLite**
store, built once at index time and read occasionally (decision doc-6):

- **Schema.** The store is `<burrow>/docno-cp.sqlite`, one table
  `docno_map(cp INTEGER PRIMARY KEY, docno TEXT UNIQUE)`. The primary key gives
  `cp → docno`; the `UNIQUE` index gives `docno → cp` **and** is the
  docno-uniqueness check — a duplicate docno fails the build, naming the offender.
  The reader is **Python-only** — `isj_agent.docno_map` — keyed on this table name
  and schema; the C++ engine never opens it (decision **doc-8**). Sized for ~500M
  rows (tens of GB on disk); **never loaded into the query process**.

- **Build (two steps, one front door).** A Python index CLI orchestrates:
  1. the C++ `cottontail-jsonl-index` indexes the JSONL into a plain cp-native
     burrow — `add_document(text) -> cp` — and **dumps a flat `docno<TAB>cp` file
     at `<burrow>/docno-cp.tsv`** alongside it (no map structure in C++, no in-RAM
     accumulation);
  2. the CLI loads the flat file into the SQLite store and **deletes the flat
     file** (on success; on failure it leaves both in place and exits non-zero).
  For a corpus with no docnos, step 1 writes no flat file and step 2 builds no
  store — a cp-only burrow.

- **Read (boundary only — Python-only; the C++ engine never opens the map, doc-8).**
  Both readers are Python over `isj_agent.docno_map`: **C2** does the run-output
  `cp → docno` rewrite (a bounded batch per intent and trace), and the
  **`cottontail-fetch` helper (TASK-6.4)** does `docno → cp` for a human/external
  fetch, then calls the C++ get-by-`cp`. The C++ side takes **no SQLite dependency**;
  it is cp-only. The document *text* always comes from the warren; the store holds
  only the identity mapping (`cq` is derived from the `:item` container at `cp`, not
  stored).

This replaces the earlier custom binary sidecar (a packed, compressed, lazily-read
`cp ↔ docno` file with a docno-sorted permutation). That design was justified only
while the map sat on the multi-threaded query path; cp-native takes it off that
path (§4), so an off-the-shelf embedded store is simpler and sufficient — and it
streams to disk at build time instead of accumulating every `(cp, docno)` pair in
RAM to sort.

## 7. Deliberate divergences and assumptions

- **We do not use the Cottontail `id`-annotation / `fastid` / `trec_docno`
  convention** that the other apps (`rank`, `mt`, `splade`, …) share (they set an
  `id` warren parameter naming a docno annotation and translate it). Those tools
  will not recognize our burrows' ids. This is an accepted trade for not indexing
  docnos; the JSONL stack carries its own SQLite `cp ↔ docno` map instead.
- **`docno` is stored verbatim** from the JSON `docid`. We do not apply
  `trec_docno()` SGML stripping (that is for `<DOCNO>…</DOCNO>` text); a JSON docid
  is already the bare identifier.
- **Uniqueness of `docno` is required** and validated at build time by the SQLite
  `UNIQUE` index (§6).
- **One document per row; document-level identity.** Passage/sub-document
  annotations are a separate concern not covered here.

## 8. Rejected alternatives (for the record)

- **Exclude via a GCL container carve** `(!> :item (+ (>> :docno P₁) …))`. Correct,
  but it re-evaluates the hyper-frequent docno tokens (e.g. the 85M-posting
  `shard`) every turn, grows with the judged set, and is only a *containment* match
  (not exact). Replaced by the `cp` post-filter (§4).
- **Mark judged documents with an annotation** (e.g. `:judged`) and carve
  `(!> :item :judged)`. Clean and cheap *on a mutable warren*, but **impossible on
  a static burrow** (no annotator at read time) and it would put per-run session
  state in the index. The judged set stays client-side instead.

## 9. Summary

The burrow stores **text + one `:item` annotation per document, and nothing
else**. The working identity is the `:item` start address **`cp`** (decision
doc-6): results, exclusion, ranking, the agent's judged set, and document reads are
all `cp`; filtering judged documents is a direct integer `cp` post-filter, and text
is `translate(cp, cq)`. The **`docno` is optional and lives only at the boundary** —
in a `cp ↔ docno` **SQLite** map (built at index time from a flat `(docno, cp)`
dump) consulted off the hot path: `cp → docno` when results / traces are written to
disk, and `docno → cp` for a human/external fetch. This removes the docno-token
index bloat and the docno GCL carve, keeps the multi-threaded query path map-free,
and fits the static, stateless burrow exactly.
