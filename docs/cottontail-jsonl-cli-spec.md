# Specification: Cottontail JSONL Index & Query CLIs

**Audience:** an implementing agent with full access to this Cottontail repository.
**Goal:** two command-line programs — one that indexes a directory tree of `*.jsonl`
(optionally gzip'd) files into a Cottontail burrow, and one that queries that burrow
in a way that is convenient for an LLM agent to drive.

The intended product is a **structured, ranked "grep on steroids"** for an agent:
exact / Boolean / phrase / proximity / structural search plus a lightweight ranked
retrieval mode, over a large static corpus, with millisecond queries.

This document specifies **external behavior** (CLI contract, I/O formats, semantics,
errors). It does not dictate exact internal API calls — bind against the real
`src/cottontail.h` API. Section 8 records the concrete, *already-validated* build and
query path so you don't have to rediscover it.

---

## 0. Scope, non-goals, and why

These decisions were made deliberately after measuring the engine at scale (see §9).

1. **Ranking model = cover-density (proximity) ranking, no precomputed statistics.**
   The default text ranker is **`icover_ranking`** (Clarke & Terra cover-density passage
   ranking). It scores using only the token inverted index plus cheap, on-the-fly
   collection counts (`idx()->count()`, `idx()->vocab()`, `txt()->tokens()`). **The only
   precompute these tools perform is building the index itself.**
2. **Explicit non-goal: BM25, language-model (LMD), and pseudo-relevance-feedback (PRF)
   ranking are NOT provided.** Those require a separate `tf_idf_annotations` /
   `tf_df_annotations` pass that materializes a term-frequency annotation per
   (document, term). On a ~6,500-shard corpus that pass is single-threaded, roughly
   doubles index size, and extrapolates to ~12 days — and an agent driving structured +
   proximity search does not need it. Do **not** add a stats-precompute step. (If BM25 is
   ever wanted, it would be a clearly separate, opt-in offline tool — out of scope here.)
3. **Index type:** a static, disk-based **`SimpleWarren`** burrow. The indexer writes it;
   the query tool opens it **read-only**.
4. **Indexed content:** only the **text** (the `contents` field by default) is
   tokenized; the **docno** (the `docid` field by default) is recorded out-of-index
   in the cp↔docno map (§3.4), never tokenized. Field names are configurable
   (`--docno-field` / `--text-field`); internal terms are `docno`/`text` (doc-7).
   **All other JSON fields are ignored** — including `id` (its
   semantics are unknown and it must not be used), `source_file`, `row_number`, `mode`,
   and any future fields. They are not indexed, stored, or returned.
5. **Retrieval unit:** one **row = one document**. Ranking and dedup happen at row
   granularity (never multiple overlapping passages from the same row competing for
   result slots). Each result surfaces the **best matching passage span within the row**;
   full row body is returned only on request.
6. **Embedded Q&A:** any trailing `Question:/Answer:` text inside `contents` is indexed
   **verbatim** — no detection, no stripping, no special handling. It is just content.

---

## 1. Reference material in the repo (use these — they are correct for this work)

- **`apps/climbmix-poc.cc`** — a **working end-to-end reference** for *this* project: it
  builds a no-precompute `SimpleWarren` over the gzip'd ClimbMix shards and exercises the
  exact build + cover-density-query + GCL path this spec describes (with timings). It is a
  **probe/scaffold, not the deliverable** — it has a hardcoded corpus path, prints demo
  output instead of the JSON contract, and is one program rather than two — but it is the
  best place to see the whole path working. Read it first, then build the real CLIs.
- **`apps/treccast21-build.cc`** — the authoritative template for **building a static
  `SimpleWarren` burrow** with the per-row tag-annotation pattern (`add_text` +
  `add_annotation(":pid"/":paragraph", …)`). Copy this structure.
- **`src/simple_builder.{h,cc}`** — `SimpleBuilder`, the static external-memory index
  builder (sort/spill/merge). This is the build engine.
- **`src/ranking.cc`** — the ranking functions. The ones this project uses:
  `icover_ranking` (`:389`, cover-density, default), `ssr_ranking` (`:305`,
  shortest-substring over a GCL expression), `tiered_ranking` (`:239`). **All three need
  no precompute.** (`bm25_ranking`/`lmd_ranking` are present but out of scope — see §0.2.)
- **`src/gcl.{h,cc}` + `src/parse.cc`** — the GCL query algebra and its S-expression
  parser. `src/parse.cc:19` lists the operator tokens (see §7).
- **`src/builder.cc` `inhale()`** — file reader that **transparently decompresses
  `.gz`/`.Z`/`.z` via `zcat`**. Use it to read shards; gzip is handled for free.
- The **Annotative Indexing** paper (`docs/Annotative-Indexing-IRRJ-Clarke-2025.{md,pdf}`),
  for the GCL operator semantics.

> Do **not** use `apps/trec-example.cc` as the build model — it builds a *Bigwig*
> (dynamic warren), not a static `SimpleWarren`. Do **not** use `apps/walk.h` — it still
> depends on Boost and is a known build blocker; use C++17/20 `std::filesystem` for
> directory traversal instead.

Both programs are added under `apps/` and wired into the Bazel build like the other app
targets (deps `//src:cottontail`).

---

## 2. Shared conventions

- **Stream discipline:** human-readable progress/warnings/errors → **stderr**;
  machine-readable results and the final summary → **stdout** as JSON. This lets an agent
  capture stdout cleanly.
- **Encoding:** input is UTF-8; preserve UTF-8 in returned text.
- **Exit codes:** `0` success (empty results included); `1` usage error; `2` runtime
  error (I/O, corrupt burrow, query parse failure). Empty result sets are **success**.
- **Error shape:** on a runtime error, emit one JSON object to stderr
  `{"error": "<message>", "where": "<phase>"}` and exit non-zero.
- **JSON field naming:** `snake_case`, stable; additive fields are fine, renames are
  breaking.
- **Burrow:** a directory Cottontail creates/manages. The indexer writes it; the query
  tool opens it read-only as a `SimpleWarren`.

---

## 3. Program 1 — `cottontail-jsonl-index`

### 3.1 Synopsis

```
cottontail-jsonl-index --input <dir> --burrow <path> [options]
```

Recursively finds every `*.jsonl` / `*.jsonl.gz` under `<dir>`, parses each line as one
JSON object, and indexes it as one document. The resulting burrow must be openable
read-only by `SimpleWarren`.

### 3.2 Options

| Option | Default | Meaning |
|---|---|---|
| `--input <dir>` | (required) | Root directory; recurse for `*.jsonl`/`*.jsonl.gz`. |
| `--burrow <path>` | (required) | Output burrow path. |
| `--docno-field <name>` | `docid` | JSON field holding the docno (document id). |
| `--text-field <name>` | `contents` | JSON field holding the text (body). |
| `--buffer <records>` | 256Mi | Builder token/annotation buffer size (records). Raise on big-RAM hosts to spill less; see §3.5. |
| `--overwrite` | off | If the burrow exists, replace it; otherwise fail rather than silently append. |
| `--limit <n>` | none | Index at most `n` rows total (smoke tests). |
| `--strict` | off | Turn skips (bad/missing-field lines) into fatal errors. |
| `--tokenizer <ascii\|utf8>` | `utf8` | Token model. `utf8`: Unicode-aware (case folding, accents, CJK). `ascii`: byte-level, ASCII only (non-ASCII bytes are separators). |
| `--stem <name>` | none | Also build a co-located stemmed stream (e.g. `porter`); see `docs/stemming.md`. |
| `--verbose` | off | Per-file progress to stderr. |

Tokenization and stemming are recorded in the burrow's dna, so the query tool
reconstructs the identical tokenizer (and any stemmed stream) automatically — there
is no matching flag on the query side. Default retrieval is exact surface tokens
(Unicode case-folded under `utf8`); `--stem` adds opt-in per-query recall (see
`docs/stemming.md`).

### 3.3 JSONL parsing rules

- One JSON object per line; blank lines skipped silently.
- A line that fails to parse, is missing the docno/text field, or is
  **contentless** (empty docno/text, or text with no indexable tokens) is
  **skipped, counted, and logged** at `--verbose`. It must **not** abort the run
  unless `--strict`.
- A **duplicate docno** is **not** detected at index time (cp-native: the indexer
  stores no docno). Both rows are indexed and both appear in the flat dump; docno
  uniqueness is enforced later, when the index CLI (TASK-6.3) builds the SQLite
  map (its `UNIQUE` index fails the build, naming the offender).
- Only the docno field (default `docid`) and text field (default `contents`) are
  read; every other field (including `id`) is ignored.

### 3.4 Indexing model (one row = one document)

For each row, the **content indexer** (`ContentIndexer`, `src/content_index.h`)
stores **only the text**, bracketed by one structural annotation, and hands back
the document's `cp`:

```
cp = add_document(text):
  add_text(text) -> (p_body, q_body) ; add_annotation(":item", p_body, q_body)
  return cp = p_body
```

- `:item` spans the **body** and is the document/container extent.
- The docno is **not** tokenized and there is **no `:docno`** annotation. Indexing
  the docno would bloat the inverted index with tokens we never search (e.g.
  `shard_*`) — see `docs/indexing.md` §2.
- The unique internal id is the `:item` start address `cp`. `jsonl_index` pairs
  each docno with its `cp` in a flat `<burrow>/docno-cp.tsv` dump (one
  `docno<TAB>cp` line per indexed row), from which the index CLI (TASK-6.3) builds
  the `cp ↔ docno` **SQLite** map (`docno-cp.sqlite`), whose `UNIQUE` index
  enforces docno uniqueness. See `docs/indexing.md` (decision doc-6 cp-native,
  doc-7 naming).
- Body text is indexed **verbatim**.

Use the **`hashing` featurizer** and, by default, the **`utf8` (Unicode) tokenizer**
— correct for the UTF-8 corpus (whole-word accented/non-Latin tokens, Unicode case
folding). `--tokenizer ascii` selects the byte-level `ascii`/`noxml` tokenizer
instead (faster, but non-ASCII bytes are separators, so e.g. `café` → `caf`).
Neither tokenizer needs body sanitization: `<`, `>`, `&` are ordinary characters.
The container is referenced at query time as the bare GCL tag `:item`.

### 3.5 Build path & resource behavior

- Build through **`SimpleBuilder`** and `finalize()` to produce the static burrow; open it
  with `Warren::make("simple", burrow)`. The concrete call sequence is in §8.
- `SimpleBuilder` is **external-memory**: it buffers tokens/annotations in RAM, spills
  *sorted* temp files when a buffer exceeds `--buffer` records, then does a streaming
  k-way merge at `finalize()`. **Peak RAM ≈ buffer size, independent of corpus size.**
  Raw text is written straight to disk as compressed chunks during ingest.
- **Ingest is single-threaded** (the sort/flush and final merge use threads internally);
  do not assume a clone-per-thread ingest model. Throughput at scale comes from large
  `--buffer` values (fewer, bigger spill files → fewer open files at merge), not from
  parallel ingest.
- Reading shards via `inhale()` handles `.gz` transparently.

### 3.6 Output

Progress/warnings → stderr. On completion, one JSON object → stdout:

```json
{
  "burrow": "/path/corpus.burrow",
  "files_seen": 128,
  "rows_indexed": 412903,
  "rows_skipped": 17,
  "elapsed_seconds": 643.2,
  "burrow_bytes": 5821342720
}
```

### 3.7 Self-checks

- A tiny sample directory produces a burrow the query tool opens as a `SimpleWarren`.
- A row with obvious content is retrievable and returns its expected `docid`.
- A deliberately malformed line is skipped and counted, and the run still exits `0`
  (unless `--strict`).
- A `.jsonl.gz` shard indexes identically to its decompressed form.

---

## 4. Program 2 — `cottontail-jsonl-query`

> ⚠️ **cp-native (TASK-5.12 / A3 done; cover_search pending A1/A2).** The
> **non-cover** query path is now **cp-native** (decisions doc-6/doc-7/doc-8):
> `--text`/`--gcl` rank within `:item` and each hit carries its **`cp`** (the
> `:item` start); `--get <cp>` fetches a row's body by `cp`; `get_document` returns
> `{cp, found, text}`. **The engine is cp-only — it never reads a `docno`/map**
> (doc-8): `docno ↔ cp` is Python-only (`isj_agent.docno_map`), and a human
> "fetch by docno" uses the **`cottontail-fetch`** helper (TASK-6.4:
> `docno → cp → --get <cp>`). Some response-shape snippets **below still show the
> old `docid` key** and the `:docno` recovery — those are being updated; the
> authoritative current shapes are `cp` (search/get) per doc-7/doc-8.
> `--cover`/`cover_search` is a **separate tool** still being reworked under
> A1/A2 (TASK-5.1/5.2) and is the only part still mid-cutover.

### 4.1 Synopsis

```
cottontail-jsonl-query --burrow <path> --text "<query words>" [options]
cottontail-jsonl-query --burrow <path> --gcl  "<gcl expression>" [options]
cottontail-jsonl-query --burrow <path> --explain --gcl "<expr>" [options]
echo '{"q":"...","top_k":5}' | cottontail-jsonl-query --burrow <path> --batch
```

Opens the burrow **read-only as a `SimpleWarren`**, sets the default container to `:item`,
and prints ranked results as JSON to stdout. A single opened handle is reused for the life
of the process.

### 4.2 Query modes

- **`--text "<words>"`** — convenience mode. Words are tokenized with the burrow's
  tokenizer and run through **cover-density ranking** (`icover_ranking(warren, words,
  ":item")` by default). This is the "just retrieve, ranked" path; no operator knowledge
  required and **no precomputed stats involved**. (`icover` needs ≥2 terms; a one-word
  query falls back to `ssr` so single-word "grep" still ranks.)
- **`--gcl "<expr>"`** — structured mode. The expression is passed **through to the
  engine's GCL parser unchanged** (`hopper_from_gcl`), exposing the full operator set
  (Boolean, phrase/region, proximity, containment, negation — see §7). The matching
  `:item` documents are ranked by cover density (`ssr_ranking(warren, expr, ":item")`); a
  malformed expression is a reported error (exit 2), not a silent empty result. Do not
  invent or restrict operators — surface what the engine supports.
- **`--ranker <icover|ssr|tiered>`** — optional ranker selection for `--text`
  (default `icover`). All three are cover-density / proximity rankers requiring no
  precompute. (There is intentionally no BM25/LMD/PRF option — see §0.2.)
- **`--cover "<cover query>"`** — the ISJ agent's search tool (`cover_search`,
  distinct from `--gcl`/`search_gcl`). A GCL cover query that may use the **`word*`
  family marker** (a full word + trailing `*` → the word *and* its morphological
  family; bare terms stay exact; honored inside quoted phrases). Ranks `:item` by
  `ssr` cover density and returns `{rank, score, cp, summary}` where `summary`
  is a cover-biased extractive summary (see §4.8). Requires a `--stem porter`
  burrow; a `word*` query against a non-stemmed burrow, or a non-trailing `*`
  (e.g. `at*ack`), exits `2` with an error object. See `docs/stemming.md §6a`.
  `--exclude <docid>` (repeatable) carves judged documents out of the search;
  `--window N` sets the summary window in tokens; `--max-covers N` (default `1`)
  selects how many of the best (tightest) covers the summary is built from (`1` =
  a single focused snippet). The response also carries
  `total_matches`/`unjudged_matches`/`atom_counts` (see §4.8).

Exactly one of `--text` / `--gcl` / `--cover` (or `--batch`) must be supplied.

### 4.3 Options

| Option | Default | Meaning |
|---|---|---|
| `--burrow <path>` | (required) | Burrow to open read-only as a `SimpleWarren`. |
| `--text` / `--gcl` / `--cover` | — | Query (see 4.2). |
| `--ranker <name>` | `icover` | Cover-density ranker for `--text` (`icover`/`ssr`/`tiered`). |
| `--top-k <n>` | 10 | Number of ranked rows to return. |
| `--window <n>` | 75 | `--cover` only: summary window size in tokens, centered on each cover. |
| `--max-covers <n>` | 1 | `--cover` only: build the summary from the best (tightest) `n` covers (`1` = a single focused snippet). |
| `--exclude <docid>` | — | `--cover` only, repeatable: carve a judged document out of the search. |
| `--full-text` | off | Include the entire row body in each result (otherwise best passage + snippet). |
| `--snippet-chars <n>` | 240 | Max chars of the best-passage text when `--full-text` is off. |
| `--explain` | off | Dry run: parse + cheap diagnostics, no ranking (see 4.5). |
| `--batch` | off | Read one query object per stdin line; emit one result object per line (JSONL). |
| `--format <json\|jsonl>` | `json` | Single JSON object, or one object per line. |

### 4.4 Search output schema

Default (`--format json`):

```json
{
  "query": "elephants disappear middle east",
  "query_mode": "text",
  "ranker": "icover",
  "top_k": 10,
  "elapsed_ms": 3.1,
  "results": [
    {
      "rank": 1,
      "score": 17.83,
      "docid": "shard_00057_0",
      "best_passage": {
        "start": 41,
        "end": 78,
        "text": "The elephant ... disappeared from the Middle East 400,000 years ago"
      },
      "text": null
    }
  ]
}
```

- `score` is the cover-density score from the selected ranker (not BM25); it is meaningful
  for ordering within a query, not comparable across queries.
- `best_passage.start`/`.end` are **token addresses** (`addr`); recover the text via
  `txt()->translate(start, end)`. The best passage is the ranker's best-scoring covering
  span within the row (for `icover`) or the matching extent (for `ssr`/`--gcl`).
- `docid` is recovered with a `:docno` hopper: `docno->tau(result.container_p(), …)` then
  `txt()->translate(...)`.
- If character offsets into the original `contents` are cheaply available, add
  `char_start`/`char_end`; otherwise the passage **text** is sufficient (required).
- `text` is `null` unless `--full-text`, in which case it holds the full row body.

### 4.5 Explain output schema

`--explain` must **not** rank. It parses the query and returns cheap diagnostics so an
agent can detect the common silent-failure case (a required term with zero postings)
before spending a real query. Per-term `df` comes from `idx()->count(featurize(term))`,
which is effectively free.

```json
{
  "query": "(>> :item (^ elephant qesem))",
  "query_mode": "gcl",
  "parsed_ok": true,
  "leaves": [
    {"term": "elephant", "df": 5123},
    {"term": "qesem", "df": 4}
  ]
}
```

If the query fails to parse, return `{"parsed_ok": false, "error": "<parser message>"}`
and exit non-zero. (`--explain` is the dry-run an agent should use to validate a
structured query and spot zero-posting terms cheaply.)

### 4.6 Batch mode (for agents / eval loops)

With `--batch`, read stdin line by line; each line is a JSON object:

```json
{"q": "<text or gcl>", "is_gcl": false, "top_k": 5, "ranker": "icover", "full_text": false}
```

Emit exactly one result object per input line to stdout (JSONL), preserving input order,
each shaped like 4.4 with an added `"input_index"` field. A malformed input line yields
`{"input_index": i, "error": "..."}` but does not abort the batch.

### 4.7 Error & edge behavior

- Missing/corrupt burrow → exit `2` with an error object.
- Malformed `--gcl` → exit `2` with the parser message.
- Zero results → exit `0` with an empty `results` array.
- Open the burrow **once** and reuse the handle. (A one-shot CLI needs one handle; if you
  ever thread query handling, clone per thread.)

### 4.8 Cover-search output schema (`--cover`)

Request: `{ "query", "top_k"?, "exclude"? : [cp,…], "window"? : tokens }`.

```jsonc
{
  "total_matches": 50,          // DOCUMENTS matching the query in :item (ignores exclude)
  "unjudged_matches": 4,        // matching documents NOT excluded; results are drawn from these
  "atom_counts": [              // per query leaf -> total OCCURRENCES of the feature it resolves to
    { "term": "black",   "count": 1840 },
    { "term": "bear*",   "count": 9004 }
  ],
  "results": [
    { "rank": 1, "score": 12.3, "cp": 12345,
      "summary": "…cover-biased extractive summary…" }
  ]
}
```

These four keys are the whole response — nothing else (the Python client mirror
is strict).

- `total_matches` / `unjudged_matches` — **document** counts (matching `:item`
  rows), exact, computed as a **byproduct of the single ssr ranking pass** (doc-6
  §4). `total_matches` ignores `exclude`; `unjudged_matches` =
  `total_matches − (excluded cps that actually match the query)` (excluding a cp
  that does not match, or is absent, leaves it unchanged). Both are independent of
  `top_k`.
- `atom_counts` — one `{term, count}` per query **leaf** (the content terms: bare
  words and `word*` markers; operators/`:tags` skipped, phrase words counted
  individually, deduped). `term` is **as written** (`bear*`, never `porter:…`);
  `count` is the total **occurrences** (collection frequency) of the feature it
  resolves to, `0` when nothing matches (a dead atom). No `stream` field.
- `exclude` — judged **cps** (the `cp` of each prior result) to skip. Exclusion is
  a direct **cp post-filter** on the ranked results (doc-6 §4): ranking over-fetches
  `depth = top_k + |exclude|`, drops hits whose `cp` is in the set, and returns up
  to `top_k` survivors. Exact (integer set membership), stateless (per-request),
  and never opens a `:docno`/map.
- `window` — summary window size in tokens (default 75); affects only the
  `summary` text, never `rank`/`score`.
- `max_covers` — how many of the best (tightest, smallest-span) covers the
  `summary` is built from (default `1` → a single focused snippet); affects only
  the `summary` text, never `rank`/`score`.
- `rank` — 1-based position within the returned (post-exclusion) results,
  restarting at 1 each call, no gaps; NOT an absolute corpus position or the TREC
  submission rank. `score` — `ssr` cover density (sum over the document's covers
  of `1/(K+q−p)`), per-document and exclusion-invariant.
- `summary` — a cover-biased extractive summary built from the best `max_covers`
  (default 1, the single tightest) of the query's covers *within* that document: a
  `window`-token window centered on each chosen cover, shifted inward at the body
  edges, overlapping/touching windows merged, non-contiguous extents joined by
  ` . . . `. It **replaces** `best_passage`.
- Errors (exit `2`, `{error, where}`): a `word*` query against a non-stemmed
  burrow; a non-trailing `*`; malformed GCL.

---

## 5. Why these choices (agent-usability rationale)

- **Cover-density ranking with no precompute** gives ranked retrieval that is fast (ms),
  cheap to build, and ~⅓ the disk of a stats-bearing index — and it is exactly the
  proximity-based relevance an agent wants from a structured search tool.
- **Row-level hits + a surfaced best passage** give the agent complete, self-contained
  context while still pointing at *where* the evidence is, without flooding it with
  overlapping fragments from one row.
- **Full text behind a flag** keeps default responses token-cheap; the agent escalates
  only when needed.
- **`--text` and `--gcl` as separate modes** let the agent start with bag-of-words and
  escalate to precise structured queries (phrase, proximity, containment, required/
  excluded) — the structured language is an action space, not a requirement.
- **`--explain` as a dry run** turns the structured language's main failure mode (silent
  zero results from a missing term) into a cheap, inspectable signal.
- **JSON to stdout + JSONL batch** make both tools trivial to wrap later behind a REST or
  MCP layer using the identical contract.

---

## 6. Build & integration notes

- Add `apps/cottontail-jsonl-index.cc` and `apps/cottontail-jsonl-query.cc`, wired into
  the Bazel build alongside the existing app targets (deps `//src:cottontail`).
- Use `std::filesystem` for directory traversal (recurse for `*.jsonl`/`*.jsonl.gz`).
  **Do not** use `apps/walk.h` (Boost-broken).
- Read shards with `cottontail::inhale()` — it decompresses `.gz` transparently.
- Use `nlohmann_json` (already a dependency; `#include "src/nlohmann.h"`, type `json`) for
  JSON parsing and emission.
- Keep both programs dependency-light: standard library + Cottontail + nlohmann_json. No
  network, no HTTP.
- Provide `--help` for each documenting the options above.

---

## 7. GCL operator set (authoritative, from `src/parse.cc:19`)

Pass `--gcl` expressions through unchanged. The operator tokens are:

| Token | Operator | Meaning |
|---|---|---|
| `^` | ALL_OF (And) | smallest extent containing all operands |
| `+` | ONE_OF (Or) | any operand |
| `...` or `<>` | FOLLOWED_BY | region from the first operand to the last (ordered) |
| `<<` | CONTAINED_IN | left operand contained in right |
| `>>` | CONTAINING | left operand containing right |

Useful patterns for this corpus (container tag `:item`; the docid is no longer a
GCL tag — it lives in the sidecar, see §3.4):

- Documents containing both terms: `(>> :item (^ influenza vaccination))`
- Documents with the terms in order/proximity: `(>> :item (... influenza vaccination))`
- Either term: `(+ flu influenza)`
- Quoted phrases in `--text`/`--gcl` are expanded via the tokenizer
  (`SExpression::expand_phrases`).

---

## 8. Validated construction & query sequence (copy this)

This is the exact path proven to build and query a static `SimpleWarren` over the corpus
(see §9 for measured behavior). Bind to the real API; names below are accurate.

**Index build (via the generic indexer; new-style, see §3.4 / `docs/indexing.md`):**

```cpp
auto working    = Working::mkdir(burrow, &error);
auto featurizer = Featurizer::make("hashing", "", &error, working);
auto tokenizer  = Tokenizer::make("ascii", "noxml", &error);
auto builder    = SimpleBuilder::make(working, featurizer, tokenizer, &error,
                                      buffer_records, buffer_records);
auto indexer    = DocnoContentsIndexer::make(builder, working, &error);
// for each row:  indexer->add_document(docid, contents, &error);
//   -> add_text(contents) + one ":item" over the body; records (cp, docid).
//      NO add_text(docid), NO ":docno".
indexer->finalize(&error);  // builder->finalize() + writes the cp<->docno sidecar
```

**Query (read-only)** — *old-model, pending the cp/sidecar redo (see the §4 banner);
the `:docno` recovery below does not work against a new-style burrow:*

```cpp
auto warren = Warren::make("simple", burrow, &error);
warren->start();
warren->set_default_container(":item", &error);
// --text:
auto hits = icover_ranking(warren, words, ":item", top_k);   // cover-density, no stats
// --gcl (ranked):
auto hits = ssr_ranking(warren, expr, ":item", top_k);
// --gcl (boolean / counting):
auto h = warren->hopper_from_gcl(expr, &error);              // iterate tau() over :item solutions
// docid for a hit:
auto docno = warren->hopper_from_gcl(":docno", &error);
docno->tau(hit.container_p(), &dp, &dq);                     // txt()->translate(dp,dq) == docid
// best passage text: txt()->translate(hit.p(), hit.q())
warren->end();
```

Read access requires `start()`/`end()`. The query is served from the on-disk index by
reading only the query terms' postings on demand (no collection scan); a working
`apps/climbmix-poc.cc` exercises this whole path.

---

## 9. Measured behavior (sets expectations for full scale)

Measured on the ClimbMix corpus (`/share/corpora/climbmix-400b-corpus-jsonl/`, gzip'd
JSONL shards, ~86k rows / ~96 MB compressed each; full corpus ~6,500 shards), with the
no-precompute build above. The headline numbers are from a **100-shard run (8,460,288
documents)**:

- **Build:** ~27 s/shard (sub-linear with a large `--buffer`; ~32 s/shard at default).
  External-memory: peak RSS tracks the **buffer size, not the corpus** (a 1 Gi-record
  buffer used ~34 GB regardless of doc count). Burrow ~175 MB/shard. 100 shards: ~44 min,
  17.6 GB.
- **Query latency scales with the query terms' document frequency, not corpus size** —
  the cover-density rankers advance the full posting lists of the query terms.
  Measured `icover` for two *common* terms: ~3 ms at 257 K docs (df ~2 K) → **71 ms at
  8.46 M docs** (df ~65 K–87 K). At 8.46 M docs: `ssr` ~9 ms, containment count ~31 ms,
  GCL proximity ~25 ms, `df` lookups instant.
- **Set expectations accordingly:** **precise queries — rare/specific terms, phrases,
  structured proximity/containment — stay fast (ms) at any scale** (few postings). A
  **broad common-term *ranked* query is second-scale at the full ~560 M-doc corpus**
  (extrapolating the df growth). `--top-k` pruning helps but does not change the trend;
  WAND-style top-k skipping would, but it needs the BM25 stats this project excludes.
  This is the right trade for a precise "grep" tool; flag it in `--help`.
- **Extrapolation to ~6,500 shards:** build ~48 h (one-time), disk ~1.1 TB, ~560 M
  documents, RAM bounded by `--buffer`. **Feasible.**
- For contrast, the (out-of-scope) BM25 `tf_idf_annotations` precompute cost ~164 s/shard
  (~12 days extrapolated) and more than doubled index size — which is why §0.2 excludes it.

---

## 10. Open items for the implementer

- Decide whether `char_start`/`char_end` into the original `contents` are cheaply
  recoverable; if so, populate them in `best_passage` (otherwise passage text suffices).
- Confirm large-`--buffer` behavior on the target host (open-file-descriptor count at the
  final merge scales with corpus/buffer; raise the buffer to keep it bounded).

> Status: implemented in `apps/cottontail-jsonl-index.cc`,
> `apps/cottontail-jsonl-query.cc`, and the shared `apps/jsonl_core.{h,cc}` library, with
> regression tests in `test/jsonl.cc` + `test/jsonl_cli.cc` (`//test:jsonl_test`). The POC
> `apps/climbmix-poc.cc` remains as the timing/scaling probe.

---

## 11. Testing (required — keep the suite green)

Both programs must ship with committed regression tests. The project uses **googletest**
(`test/BUILD`, `src/cottontail.h`); follow these conventions exactly.

### 11.1 Make it testable: thin CLIs over a small library

The single most important rule. Put the real work in a small `cc_library` (e.g.
`apps/jsonl_core.{h,cc}`) exposing functions like:

```cpp
bool jsonl_index(const IndexOptions &opts, IndexSummary *summary, std::string *error);
std::vector<Hit> jsonl_query(Warren &warren, const QuerySpec &spec, std::string *error);
```

`main()` in each CLI is then a thin argv/JSON wrapper. Tests link the library and call
these functions directly — fast, deterministic, no subprocess. Do **not** bury the logic
in `main()`.

### 11.2 Where tests live and how they join the build

- The aggregate target `//test:tests` **globs `test/**/*.cc`**, so adding `test/jsonl.cc`
  is automatically included — no BUILD edit needed for the test source itself.
- Prefer a **dedicated `cc_test`** target `//test:jsonl_test` (mirror `//test:hazel_test`
  in `test/BUILD`: its own `srcs`, `data`, `linkopts = ["-lz","-pthread"]`,
  deps `//src:cottontail` + `@googletest//:gtest_main`). Dedicated targets isolate
  failures and declare their own fixtures.
- Commit the new suite into the green gate: `bazel test -c dbg //test:tests
  //test:hazel_test //test:jsonl_test` must pass before any PR (see §Contributing in
  `/CLAUDE.md`).

> **Keep the regression net in C++.** Python and shell are committable in this
> repo (for tooling and examples), but the green-gate regression tests stay
> **C++/googletest** — fast, deterministic, no subprocess — which is why §11.1
> (library factoring) matters: test `jsonl_core` directly rather than scripting the
> binary.

### 11.3 Fixtures (tiny, committed under `test/jsonl/`, listed in the target's `data`)

- `sample.jsonl` — a few rows with known `docid`/`contents` **and** extra fields
  (`id`, `mode`, …) present, so the suite can prove they are ignored.
- `sample.jsonl.gz` — the same rows gzip'd, to verify the decompression path is identical.
- `malformed.jsonl` — a blank line, a non-JSON line, and a line missing `contents`.

Build into a temporary `Working::mkdir` directory; reference fixtures by relative path
(`"test/jsonl/sample.jsonl"`), which Bazel resolves via runfiles.

### 11.4 Assertion matrix (the regressions to lock down)

1. **Build accounting** — exact `rows_indexed` / `rows_skipped`; burrow opens as
   `SimpleWarren`.
2. **Retrieval + docid** — an obvious query returns the expected row; its `docid`
   (recovered via the `:docno` hopper) is correct.
3. **Field projection (negative test)** — a token appearing **only** in an ignored field
   (e.g. a unique `id`/`mode` value) returns **zero** hits. This proves only
   `contents`+`docid` are indexed.
4. **gzip == plaintext** — `sample.jsonl` and `sample.jsonl.gz` give identical results.
5. **Skip / strict** — malformed/missing-field lines are skipped and counted (exit 0);
   `--strict` makes them fatal.
6. **GCL semantics** — `(>> :item (^ a b))` and `(... a b)` match exactly the expected
   docs on the fixture; assert counts.
7. **`--explain`** — per-term `df` matches the fixture; `parsed_ok:false` + error message
   on a malformed expression.
8. **JSON output contract** — parse stdout and assert the §4.4 field names/shape (a
   renamed field is a breaking change worth catching).
9. **Empty results** — a no-match query yields an empty array and exit `0`, not an error.
10. **Exit codes & error shape** — usage error → exit `1`; runtime error (missing/corrupt
    burrow, malformed `--gcl`) → exit `2` with a single stderr `{"error","where"}` object;
    success (including empty results) → exit `0`. (Contract from §2.)
11. **Batch mode** — `--batch` preserves input order, emits one object per input line with
    an `input_index`, and a malformed input line yields a per-line `{"input_index","error"}`
    object **without aborting** the batch. (Contract from §4.6.)
12. **`--full-text` vs snippet** — default returns the best-passage snippet (≤
    `--snippet-chars`) with `text: null`; `--full-text` returns the full row body. (§4.3.)

Items 1–9 are library-level (call the §11.1 functions directly). Items 10–12 are
process-boundary behaviors — see §11.6.

### 11.5 Determinism caveats (so tests don't flake)

- `SimpleBuilder` uses worker threads for sort/flush, but the final merged index is
  deterministic — the index itself is safe to assert on.
- The flaky spot is **ranking ties**: rows with equal cover-density scores may swap order.
  Assert on **set membership / presence of expected docids**, or use a fixture where the
  top results have **distinct** scores — do not assert an exact order across tied results.
- The gzip-equivalence test depends on `zcat` being available to `inhale()`. Keep it in
  its **own** test case so a sandbox lacking `zcat` can't sink the rest of the suite.

### 11.6 One CLI end-to-end test (the process boundary)

The §11.1 library tests cover logic, but a few behaviors exist only at the process
boundary — exit codes, the stderr `{"error","where"}` object, stdout JSON framing, and
`--batch` JSONL (assertion-matrix items 10–12). Cover them with **one** small C++
`cc_test` that runs the **built binary**:

- Declare the binary as a Bazel **`data`** dependency of the test target (e.g.
  `data = ["//apps:cottontail-jsonl-query"]`) and locate it via runfiles.
- Invoke it with `popen`/`fork+exec`, capturing stdout, stderr, and the exit status;
  parse the captured streams as JSON and assert their shape.
- Keep it minimal: one happy path, one usage error (exit `1`), one runtime error
  (exit `2`, with the stderr error object), and one `--batch` case (order preserved,
  one malformed line isolated).

This C++ harness is the **committed** regression net for the CLI surface (fast and
self-contained); everything else stays at the library level. Ad-hoc `.sh`/`.py`
scripts are fine for exploration but are not the green-gate tests.
