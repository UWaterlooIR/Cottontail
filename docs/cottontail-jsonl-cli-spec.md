# Specification: Cottontail JSONL Index & Query CLIs

**Audience:** an implementing agent with full access to the `claclark/Cottontail` repository.
**Goal:** two command-line programs — one that indexes a directory tree of `*.jsonl` files into a Cottontail burrow, and one that queries that burrow in a way that is convenient for an LLM agent to drive.

This document specifies **external behavior** (CLI contract, input/output formats, semantics, errors). It does **not** dictate exact internal API calls — you have the repo and should bind against the real `src/cottontail.h` API. Where helpful, it points at existing code to copy patterns from.

---

## 0. Reference material in the repo

Use these as implementation templates rather than reinventing:

- `apps/trec-example.cc` — the authoritative example for **building a burrow** and for the **clone-per-thread concurrency pattern**. It shows the construction sequence (`Working::mkdir` -> `Featurizer::make("hashing")` -> `Tokenizer::make("ascii","xml")` -> a warren -> `Stemmer::make("porter")` -> `set_default_container` / `set_parameter` with GCL queries), ingestion via `scribe_files` / a `Scribe`, and annotation via the warren's `annotator()` inside transactions.
- `apps/treccast21.cc` — example for **ranked retrieval with passage output**, the `Ranker::from_pipeline(...)` ranking-pipeline mechanism, and recovering text with `txt()->translate(...)`.
- `apps/walk.h` — filesystem walking helper (`walk_filesystem`) for enumerating input files.
- The **Annotative Indexing** paper (cited in the repo README; arXiv 2411.06256), especially the operator figure, for the GCL operator set.

Both new programs should be added under `apps/` and wired into the existing Bazel build the same way the example apps are.

---

## 1. Resolved decisions & assumptions

These were decided with the requester.

1. **Indexed content:** only the `contents` field (body text) plus **`docid`** (the single document identifier). **All other JSON fields are ignored** — including `id` (its semantics are unknown and it must not be used), `source_file`, `row_number`, `mode`, and any future fields. They are not indexed, not stored, not returned.
2. **Retrieval unit:** one **row = one document**. Ranking and deduplication happen at row granularity (never multiple overlapping passages from the same row competing for result slots). Each result additionally surfaces the **best matching passage span within the row**; full row body text is returned only when explicitly requested.
3. **Embedded Q&A:** the trailing `Question:/Answer:` text inside `contents` is part of the body and is indexed **verbatim, with no special handling** — no detection, no stripping, no separate annotation. It is simply content.
4. **Index type:** the on-disk index is a **static, disk-based `SimpleWarren`**. The query program opens it **read-only**; the index program must produce a burrow that `SimpleWarren` can open.

---

## 2. Shared conventions

- **Stream discipline:** human-readable progress, warnings, and errors go to **stderr**. Machine-readable results and the final summary go to **stdout** as JSON. This lets an agent capture stdout cleanly.
- **Encoding:** input is UTF-8. Preserve UTF-8 in returned text.
- **Exit codes:** `0` success; `1` usage error (bad/missing arguments); `2` runtime error (I/O, corrupt burrow, query parse failure). Empty result sets are **success**, not errors.
- **Error shape:** on a runtime error, emit a single JSON object to stderr: `{"error": "<message>", "where": "<phase>"}` and exit non-zero.
- **JSON field naming:** `snake_case`, stable. Treat the schemas below as a contract; additive fields are fine, renames are breaking.
- **Burrow:** a directory created/managed by Cottontail. The indexer writes it; the query tool opens it read-only as a `SimpleWarren`.

---

## 3. Program 1 — `cottontail-jsonl-index`

### 3.1 Synopsis

```
cottontail-jsonl-index --input <dir> --burrow <path> [options]
```

Recursively finds every `*.jsonl` under `<dir>`, parses each line as one JSON object, and indexes it as one document in the burrow at `<path>`. The resulting burrow must be openable read-only by `SimpleWarren`.

### 3.2 Options

| Option | Default | Meaning |
|---|---|---|
| `--input <dir>` | (required) | Root directory; recurse for `*.jsonl` files. |
| `--burrow <path>` | (required) | Output burrow path. |
| `--docid-field <name>` | `docid` | JSON field used as the document identifier. |
| `--contents-field <name>` | `contents` | JSON field holding the body text. |
| `--threads <n>` | hardware concurrency (min 2) | Ingest parallelism. |
| `--stemmer <name>` | `porter` | Stemmer recipe. |
| `--overwrite` | off | If the burrow exists, replace it; otherwise fail rather than silently append. |
| `--limit <n>` | none | Index at most `n` rows total (for smoke tests). |
| `--verbose` | off | Per-file progress to stderr. |

### 3.3 JSONL parsing rules

- One JSON object per line. Blank lines are skipped silently.
- A line that fails to parse, or is missing the `--docid-field` or `--contents-field`, is **skipped**, counted, and logged to stderr at `--verbose`. It must **not** abort the run. (You may add an optional `--strict` flag, defaulting off, that turns skips into fatal errors.)
- Only `docid` and `contents` are read; ignore every other field, including `id`.

### 3.4 Indexing model (one row = one document)

Each row must be indexed so that:

1. Its `contents` text is fully searchable as the document body, **verbatim** (Q&A included).
2. The whole row is addressable as a single **container/document extent** (so retrieval, scoring, and best-passage extraction operate within row boundaries).
3. Every document carries its `docid` so the query program can return the originating identifier for **every** hit.

**Recommended mechanism (path of least resistance, reuses the existing apps' pattern):** wrap each row as a small tagged unit before scribing, e.g.

```
<doc><docid>shard_00057_0</docid><body> ... contents text ... </body></doc>
```

then set, exactly as `trec-example.cc` does:

- default container query: `(... <doc> </doc>)`
- id parameter query: `(... <docid> </docid>)`

and use the `ascii`/`xml` tokenizer so the wrapper tags delimit documents and ids. This makes one row a clean container extent and lets the `docid` be recovered with the same GCL parameter mechanism the codebase already uses.

**Important — sanitize the body:** because the wrapper relies on tag delimiters, escape or neutralize any `<`, `>`, and `&` characters that occur inside the `contents` text before wrapping (or choose an equivalent delimiting scheme robust to in-text angle brackets). The body text recovered at query time should read naturally (unescaped).

You may instead attach the `docid` via the `annotator()` directly (mirroring how `trec-example.cc` annotates onto document extents) if you find that cleaner — the requirement is only that **every hit resolves back to its row's `docid`**.

### 3.5 Build path & concurrency

- **Target:** a static, disk-based burrow that `SimpleWarren` opens read-only. Use whatever construction path the repository provides to produce that static on-disk form; if the build is most naturally done through a dynamic warren and then finalized/persisted, do so. Consult the repo for the exact builder.
- **Concurrency:** follow the `trec-example.cc` model — build one base warren, then `clone()` a handle per worker thread; parallelize ingestion across threads up to `--threads`, using transactions/commit as in the example.

### 3.6 Output

- Progress and warnings -> stderr.
- On completion, one JSON object -> stdout:

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

### 3.7 Suggested behaviors to self-check

- Indexing a tiny sample directory produces a burrow that the query tool can open as a `SimpleWarren`.
- A row with the sample "elephants" content is retrievable by an obvious query and its returned `docid` equals `shard_00057_0`.
- A deliberately malformed line is skipped and counted, and the run still exits `0`.

---

## 4. Program 2 — `cottontail-jsonl-query`

### 4.1 Synopsis

```
cottontail-jsonl-query --burrow <path> --text "<query words>" [options]
cottontail-jsonl-query --burrow <path> --gcl  "<gcl expression>" [options]
cottontail-jsonl-query --burrow <path> --explain --gcl "<expr>" [options]
echo '{"q":"...","top_k":5}' | cottontail-jsonl-query --burrow <path> --batch
```

Opens the burrow **read-only as a `SimpleWarren`** and prints ranked results as JSON to stdout.

### 4.2 Query modes

The agent picks the level of control:

- **`--text "<words>"`** — convenience mode. The words are tokenized/stemmed and run through the default ranking pipeline. This is the "just retrieve" path; no operator knowledge required.
- **`--gcl "<expr>"`** — structured mode. The expression is passed **through to the engine's GCL query parser unchanged** (i.e., to `hopper_from_gcl` / the ranker's query input). This exposes the full structured query language — phrases, proximity/windows, containment within tagged extents, required/excluded terms — using whatever operator set the in-repo GCL implementation and the Annotative Indexing paper define. Do **not** invent or restrict operators here; surface what the engine supports.
- **`--pipeline "<spec>"`** — optional override of the ranking pipeline string (same grammar `Ranker::from_pipeline` accepts). Defaults below.

> Observed-valid GCL examples from the existing apps (for orientation, not a complete grammar): `(... <doc> </doc>)` to delimit a document extent; `(... <docid> </docid>)` to delimit an id. The implementing agent should consult the repo for the authoritative operator list and expose it verbatim through `--gcl`.

Exactly one of `--text` / `--gcl` (or `--batch`) must be supplied.

### 4.3 Options

| Option | Default | Meaning |
|---|---|---|
| `--burrow <path>` | (required) | Burrow to open read-only as a `SimpleWarren`. |
| `--text` / `--gcl` | — | Query (see 4.2). |
| `--pipeline <spec>` | see 4.6 | Ranking pipeline override. |
| `--top-k <n>` | 10 | Number of ranked rows to return. |
| `--full-text` | off | Include the entire row body in each result (otherwise only the best passage + a short snippet). |
| `--snippet-chars <n>` | 240 | Max characters of the best-passage text returned when `--full-text` is off. |
| `--explain` | off | Dry run: parse + estimate, no ranking (see 4.5). |
| `--batch` | off | Read one query object per line from stdin; emit one result object per line (JSONL). |
| `--format <json\|jsonl>` | `json` | Single JSON object, or one JSON object per line. |

### 4.4 Search output schema

Default (`--format json`):

```json
{
  "query": "elephants disappear middle east",
  "query_mode": "text",
  "top_k": 10,
  "total_estimated": 1432,
  "elapsed_ms": 12.4,
  "results": [
    {
      "rank": 1,
      "score": 17.83,
      "docid": "shard_00057_0",
      "best_passage": {
        "start": 41,
        "end": 78,
        "score": 17.83,
        "text": "The elephant ... disappeared from the Middle East 400,000 years ago"
      },
      "text": null
    }
  ]
}
```

- `best_passage.start` / `.end` are **token addresses** within the burrow (the engine's native `addr`). Recover the passage string via `txt()->translate(...)`, as `treccast21.cc` does for its passage output.
- If you can cheaply also provide **character offsets into the original `contents`**, add `char_start` / `char_end` to `best_passage`; treat this as a nice-to-have, not required. At minimum the passage **text** must be present.
- `text` is `null` unless `--full-text`, in which case it holds the full row body.
- The best passage is the highest-scoring minimal span covering the query terms within the row (cover-density / shortest-cover style). For `--gcl` queries it is the best-scoring solution extent of the structured query within the row.

### 4.5 Explain output schema

`--explain` must **not** run full ranking. It parses the query and returns cheap diagnostics so the agent can detect the common silent-failure case (a required term with zero postings) before spending a real query:

```json
{
  "query": "(... <something>)",
  "query_mode": "gcl",
  "parsed_ok": true,
  "leaves": [
    {"term": "elephant", "df": 5123},
    {"term": "qesem", "df": 4}
  ],
  "estimated_hits": 1432
}
```

If the query fails to parse, return `{"parsed_ok": false, "error": "<parser message>"}` and exit non-zero.

### 4.6 Default ranking pipeline

Default to a simple, robust pipeline: `stem bm25`.

Also accept (and document) a higher-recall preset the agent can opt into via `--pipeline`, adapted from the existing apps' tuned BM25 + pseudo-relevance-feedback (RSJ expansion) pipelines. Note in `--help` that these presets come from the example apps and are reasonable starting points, not tuned for this corpus.

### 4.7 Batch mode (for agents / eval loops)

With `--batch`, read stdin line by line; each line is a JSON object:

```json
{"q": "<text or gcl>", "is_gcl": false, "top_k": 5, "full_text": false}
```

Emit exactly one result object per input line to stdout (JSONL), preserving input order, each shaped like 4.4 with an added `"input_index"` field. A malformed input line yields an error object for that line (`{"input_index": i, "error": "..."}`) but does not abort the batch.

### 4.8 Error & edge behavior

- Missing/locked/corrupt burrow -> exit `2` with an error object.
- Malformed `--gcl` -> exit `2` with the parser message.
- Zero results -> exit `0` with an empty `results` array.
- Open the burrow **once** as a `SimpleWarren` and reuse the handle for the life of the process. For a one-shot CLI a single handle is fine; if you ever make query handling threaded, use the clone-per-thread pattern.

---

## 5. Why these choices (agent-usability rationale)

- **Row-level hits with a surfaced best passage** give the agent complete, self-contained context while still telling it *where* the evidence is — without flooding it with overlapping fragments from the same segment.
- **Full text behind a flag** keeps default responses token-cheap; the agent escalates to full bodies only when it needs them.
- **`--explain` as a dry run** turns the structured query language's main failure mode (silent zero results from a missing term) into a cheap, inspectable signal the agent can act on before committing to a ranked query.
- **`--text` and `--gcl` as separate modes** let the agent start with bag-of-words and escalate to precise structured queries (phrase, proximity, containment, required/excluded) only when it needs the control — the structured language is an action space, not a requirement.
- **JSON to stdout + JSONL batch** make both tools trivial to wrap later behind a REST or MCP layer using the identical contract.

---

## 6. Build & integration notes

- Add `apps/cottontail-jsonl-index.cc` and `apps/cottontail-jsonl-query.cc`, wired into the Bazel build alongside the existing example targets.
- Reuse `apps/walk.h` for directory traversal and `nlohmann_json` (already a dependency) for JSON parsing and emission.
- Keep both programs dependency-light: standard library + Cottontail + nlohmann_json. No network or HTTP needed here.
- Provide a `--help` for each that documents the options above.

---

## 7. Open items for the implementer

- Confirm the authoritative GCL operator set from the repo / paper and ensure `--gcl` passes expressions through unmodified.
- Confirm the exact `SimpleWarren` construction/build path: how to produce the static on-disk burrow at index time and how to open it read-only at query time.
- Decide whether character offsets into the original `contents` are cheaply recoverable; if so, populate `char_start` / `char_end`.
