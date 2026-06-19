# Indexing a TREC-like document collection

This note describes how the JSONL search stack should index a **TREC-like
document collection** — a set of documents, each with some **text contents** and
a **unique string identifier (the `docno`)** — and, crucially, how we manage the
identity of documents internally so that ranking, filtering, and fetching are
cheap on a **static burrow**.

It is the authoritative design for the JSONL indexing model. Where it disagrees
with the current code (`apps/jsonl_core.{h,cc}`), this note is the target and the
code should move toward it.

## 1. The document model

A document is just:

- **`docno`** — a unique string identifier (TREC's "document number"); for us it
  is the JSON `docid` field.
- **contents** — the document's text.

We index one **JSON object per line** (`*.jsonl` / `*.jsonl.gz`). The two fields
we care about (names configurable via `IndexOptions.docid_field` /
`contents_field`):

```jsonc
{ "docid": "shard_00037_72680", "contents": "Black bear attacks on hikers ..." }
```

Everything else in the row is ignored. One row = one document. (Passage-level
sub-units are out of scope here; the unit of identity is the whole document.)

**Scale.** The target collection (ClimbMix) is **~500 million documents** over
~400 billion tokens, so addresses are 64-bit and any per-document structure (the
sidecar, §6) and any per-query full scan (the match counts, §4) must be sized with
500M in mind. The committed `Scrapheap/climbmix-1000-*.burrow` is a ~1000-shard
subset (~85M docs — which is why `shard` shows ~85M postings there); the full
collection is ~6× larger.

## 2. What we store in the burrow — contents only

For each row we store **only the contents**, bracketed by one structural
annotation that marks the document's extent:

```cpp
addr p_body, q_body;
builder->add_text(contents, &p_body, &q_body);          // body tokens -> token/text store + inverted index
builder->add_annotation(":item", p_body, q_body, 0.0);  // the document's span [p_body, q_body]
// record (p_body, q_body, docno) for the sidecar (see §6)
```

We do **not** `add_text(docid)` and we do **not** create a `:docno` annotation.

**Why not index the docno.** `add_text` both stores tokens (so `translate` works)
*and* featurizes them into the inverted index. We never *search* for a docno, so
indexing it is pure waste — and our docnos are pathological for it. `shard_00037_72680`
tokenizes (the `_` splits) into `shard`, `00037`, `72680`; measured on a ClimbMix
burrow, the token `shard` has **84,594,007** postings (it is in every docno) and
`0` has ~20 million. Indexing docnos bloats the index and pollutes content queries
for those tokens, all to support an id we only ever need to *print* or *look up by
hand*. So the docno lives outside the inverted index, in a sidecar (§6).

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

**Internally, `cp` is the document id.** Agents, the controller, our ranking and
filtering code all key on `cp`. The `docno` string is materialized only for output
and for human inspection (§5).

> **Caveat — `cp` is burrow-instance-local.** Addresses are assigned at build time;
> they are stable for the life of a given static burrow but **change if the burrow
> is rebuilt**. So `cp` is a fine handle *within a run against one burrow* (the ISJ
> loop, exclusion), but anything persisted for later analysis must store the
> **`docno`** (portable), mapped via the sidecar — never the raw `cp`.

## 4. Filtering retrieval results by internal id

The judged/seen set is **client-side** (the burrow is static and stateless — a
read-opened `SimpleWarren` has a null annotator, so we cannot mark documents in
the index, and we keep no server session). Exclusion is therefore a **post-rank
filter on `cp`**, which is the original ISJ behaviour ("walk down the ranked list,
skip what you've already judged"):

1. Rank within the plain `:item` container (no docno carve, no docid tokens
   touched), over-fetching `depth = top_k + |exclude|` so a full page survives.
2. Drop any result whose `cp` is in the caller-supplied exclude set (an integer
   hash-set membership test — no `translate`, no string compare).
3. Build the expensive cover summaries only for the survivors; return `top_k`.

This is exact, cheap, needs no in-burrow state, and avoids the `shard`-token
posting lists entirely. The request carries `exclude` as a list of `cp` integers;
results carry each hit's `cp` (so the caller can add judged ones to its set).

The over-fetch is cheap at any scale: the judged set is bounded by the ISJ budget
(tens to a few hundred per intent), so `depth = top_k + |exclude|` stays small even
against 500M documents.

> **Open question — match counts at 500M.** Exact `total_matches` /
> `unjudged_matches` mean enumerating the whole match set, which for a broad query
> against 500M documents can be hundreds of millions of rows per call — likely
> infeasible as a per-turn signal. Options: cap the count ("≥ N matches"), sample,
> report a cheaper per-page signal ("k of the top results were already judged"), or
> drop `unjudged_matches` entirely. To be decided — but "keep them exact" does not
> obviously survive 500M.
>
> This is specifically about the **document** match counts. The per-atom
> `atom_counts` signal is *not* affected: it reads each query leaf's collection
> frequency straight from the index directory (`idx()->count(feature)` — an
> `O(log F)` lookup, cached, no posting-list load or document scan), so it stays
> cheap at 500M. The expensive thing is enumerating which/how-many *documents*
> match a cover, not counting an atom's occurrences.

## 5. Fetching document contents

Given any document's span `(cp, cq)`, the text is `txt()->translate(cp, cq)`
(`O(L)` in the document length). Two access paths:

- **Internal (by `cp`).** Agents and our code already hold `cp` from a search
  result, so reading a document is `translate(cp, cq)` directly. (For a standalone
  read-by-`cp`, the sidecar supplies `cq`; see §6.) There is no docno round-trip.
- **External (by `docno`).** The *one* place we need `docno → contents` is a human
  at the CLI fetching a document for inspection. That is `docno → cp` via the
  sidecar reverse map, then `translate(cp, cq)`. It is a rare, latency-tolerant
  operation.

## 6. The sidecar — a `cp ↔ docno` map we build ourselves

To serve docno output and the human fetch without indexing docnos, we build a
small **sidecar** at index time, populated directly from the JSON `docid` strings
(never tokenized). Per document it holds `(cp, cq, docno)`.

- **`cp → docno`** (and `cp → cq`): for emitting a docno per ranked result and for
  read-by-`cp`. Because `cp` values are monotonically increasing, store them as a
  sorted array → **binary search, `O(log m)`** (m = number of documents).
- **`docno → cp`**: for the human external fetch. A hash map (or a docno-sorted
  index) over the same `m` entries.

**Footprint at ~500M documents (size this deliberately).** Documents are stored
contiguously with no inter-document gaps, so we **do not store `cq`**: `cq_i =
cp_{i+1} − 1` (the last document's end is recorded once). That leaves, per
document, an 8-byte `cp` plus the docno text and an offset. Rough costs at m=500M:
the `cp[]` array ≈ 4 GB, offsets ≈ 4 GB, and docno text ≈ 9 GB (`shard_…` ids are
~18 bytes) — ~17 GB if fully resident, which is how `FastidTxt` loads. That is
viable on the target 512 GB host but is not free, so the sidecar should:
- keep the **`cp[]` array resident** (the hot path — `cp → index` by binary
  search, on every result), and
- read **docno text lazily from the on-disk blob** at `offset[index]` (a tiny read
  per emitted result; `top_k` reads per query, not 500M), rather than holding all
  9 GB of docno strings in RAM.
The reverse `docno → cp` (rare human fetch) can stay disk-resident too (a
docno-sorted file, binary-searched / mmap'd) — it need not be in RAM at all.

This is deliberately the same idea as Cottontail's core **`FastidTxt`**
(`src/fastid_txt.{h,cc}`, auto-wrapped by `SimpleWarren` when the `fastid`
parameter is set) — a packed `(p, q, text)` table giving `O(log m)` position→id —
**except** `FastidTxt` is built by translating a `:docno` annotation, which
presupposes the docno is in the store. Ours is built straight from the JSON docids
so we can skip indexing them altogether, and it adds the reverse `docno → cp`
direction that `FastidTxt` does not provide.

What we need to build:

1. **Build:** during `jsonl_index`, accumulate `(cp, cq, docno)` per row; after the
   pass, write a sidecar file into the burrow working directory (alongside the
   index). Fold this into `jsonl_index` so every burrow has it (rather than a
   separate `fast-id`-style step).
2. **Validate:** docnos must be unique — detect and reject (or report) duplicate
   docnos while building, since the whole scheme assumes uniqueness.
3. **Load:** open the sidecar when the burrow opens; expose `docno_of(cp)`,
   `span_of(cp) -> (cp,cq)`, and `cp_of(docno)`.
4. **Consume:** `cover_search` returns `cp` per hit and maps `cp → docno` for the
   result; exclusion post-filters on `cp`; `get_document` (CLI/human) does
   `docno → cp → translate`; the run output (C2) writes `docno` (portable), not
   `cp`.

## 7. Deliberate divergences and assumptions

- **We do not use the Cottontail `id`-annotation / `fastid` / `trec_docno`
  convention** that the other apps (`rank`, `mt`, `splade`, …) share (they set an
  `id` warren parameter naming a docno annotation and translate it). Those tools
  will not recognize our burrows' ids. This is an accepted trade for not indexing
  docnos; the JSONL stack carries its own sidecar instead.
- **`docno` is stored verbatim** from the JSON `docid`. We do not apply
  `trec_docno()` SGML stripping (that is for `<DOCNO>…</DOCNO>` text); a JSON docid
  is already the bare identifier.
- **Uniqueness of `docno` is required** and validated at build time (§6.2).
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

The burrow stores **contents + one `:item` annotation per document, and nothing
else**. The unique internal id is the `:item` start address `cp`, handed to us by
ranking. Filtering judged documents is an integer `cp` post-filter on the ranked
list. Document text is `translate(cp, cq)`. The `docno` lives only in a small
`cp ↔ docno` sidecar we build from the JSON docids — used to print docnos for
results and to let a human fetch a document by docno from the CLI. This removes the
docno-token index bloat, eliminates the docno GCL carve, and fits the static,
stateless burrow exactly.
