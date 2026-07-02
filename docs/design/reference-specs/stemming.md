# Spec delta — opt-in stemming for the Cottontail JSONL CLIs

Extends `docs/cottontail-jsonl-cli-spec.md` (section numbers below refer to that
spec). The **index-side mechanism already exists** — a `StemmingTokenizer` that
builds an exact stream and a stemmed stream co-located in one index. This
document tells an implementing agent how to **expose that through the two CLIs**
(`cottontail-jsonl-index`, `cottontail-jsonl-query`) without disturbing the
exact-by-default behavior, and how to test it.

Read §1 and §4 before writing any query code — the query mechanism is subtle and
has one genuine landmine.

---

## 1. What already exists — do not rebuild it

`src/stemming_tokenizer.{h,cc}` adds a tokenizer registered under the name
**`stemming`** (wired into `Tokenizer::make`/`check`). It is a general decorator:
it wraps **any** inner tokenizer together with **any** stemmer, both named in its
nested `name`/`recipe` recipe:

```
[ tokenizer:[ name:"ascii",  recipe:"noxml" ],
  stemmer:[   name:"porter", recipe:"" ] ]
```

Behavior:

- For every token the inner tokenizer emits, it adds a **co-located** feature —
  same address, offset, length — for the stemmed surface form, **only when the
  stemmer's `bool stemmed` out-param reports it actually changed the word**
  (short/non-alphabetic terms produce no stem feature). Porter prefixes its
  output with `porter:`, so exact and stemmed features never collide.
- Exact and stemmed features **share token addresses**, so GCL operators,
  `:item` containment, best-passage spans, and `:docno` recovery behave
  identically whether a match lands on an exact or a stemmed feature.
- `recipe()` round-trips, so a warren rebuilt from a burrow's dna reconstructs an
  identical tokenizer.

Net effect: a burrow built with the `stemming` tokenizer carries **both** the
exact surface stream and the stemmed stream in **one index, one text store, no
stats**. (Merged to `main` via PR #2.)

> **Status: the CLI surface described below is implemented** in
> `apps/jsonl_core.{h,cc}` and the two CLIs, with tests in `test/jsonl.cc`
> (`JsonlStem.*`) and `test/jsonl_cli.cc`. This section now documents the
> as-built design; §4–§5 describe the mechanism actually used (which differs
> from an earlier draft — see the note in §4).

---

## 2. Core principle (unchanged, now enforced by construction)

Exact (surface) tokens remain the **canonical, default** stream and the default
query behavior. Stemming is **additive and opt-in per query** for recall. It adds
token postings only — no stats precompute, no second text store — so the §0.2
exclusion of BM25/LMD/PRF does **not** apply to it. The agent chooses precision
(exact) vs. recall (stemmed) per query; stemming is an action-space option, not a
mode the index is locked into.

---

## 3. Indexer changes — `cottontail-jsonl-index`

- Add option **`--stem <name>`** (default: `none`; supported: `porter`; `none`
  == current exact-only behavior).
- When `--stem` is set, build the burrow with the **`stemming`** tokenizer
  wrapping the existing `ascii`/`noxml` tokenizer and the named stemmer, instead
  of plain `ascii`. Everything else — `docid`/`:docno`/`:item` structure, the
  `hashing` featurizer, the `SimpleBuilder` path in §8 — is unchanged. The
  tokenizer's recipe carries the stemmer and is written to dna by `finalize()`,
  which is how the query tool detects a stemmed stream (§5).
- **CRITICAL — do not write a warren-level stemmer into dna.** The burrow's dna
  has a separate `parameters → stemmer` slot (read at `simple_warren.cc:60–70`).
  Setting it makes the rankers stem **every** query (§4) and destroys
  exact-by-default. The stemmer must live **only inside the tokenizer recipe**,
  never in the warren `parameters` block.
- Build summary: add `"stemmer": "<name>"` (or `null`). **Measure** the
  burrow-size delta from the stemmed stream on the same 100-shard probe used in
  §9 of the main spec, report it, and extrapolate to ~6,500 shards. Get sign-off
  before any full stemmed build. (Porter skips short/non-alpha tokens, so growth
  is less than one extra posting per body token — but measure, don't assume.)

---

## 4. How a query reaches the stemmed stream (as built)

A stem feature is just `featurize("porter:<root>")` co-located with the exact
token. `--stem` retrieval therefore means: **stem each query term into its
`porter:` atom and look that feature up.** `jsonl_query` does this itself, in
`apps/jsonl_core.cc`:

1. Reconstruct the index's stemmer from the burrow's dna tokenizer recipe
   (`burrow_stemmer`): if the tokenizer name is `stemming`, pull the stemmer
   name/recipe out of its recipe and `Stemmer::make` it. A plain `ascii` burrow
   yields no stemmer (→ §5 missing-stream error).
2. Rewrite the query into stemmed atoms:
   - `--text`: split into surface terms, map each `t → stemmer->stem(t)`, and
     join as `(^ …)` (all-of).
   - `--gcl`: walk the expression and replace each **bare term** with its stem,
     leaving operators, parens, `:tags`, and quoted phrases untouched
     (`stem_gcl`).
3. Rank the rewritten expression with **`ssr_ranking`** (cover density) over
   `:item`. A GCL leaf is featurized verbatim (`parse.cc:258`,
   `featurizer->featurize(term_)`), so a `porter:<root>` atom resolves straight to
   the stemmed feature.

A no-op term is safe and symmetric: `Porter::stem("ox")` returns `"ox"`
(`stemmed=false`, no prefix), which featurizes to the **exact** `ox` feature — so
`--stem "ox"` still matches `ox`. No silent miss, and the query never looks for a
`porter:ox` the index didn't write.

> **Why not use the warren's stemmer hook?** Only `icover_ranking` stems its
> query terms via `warren->stemmer()` (`src/ranking.cc`); `ssr_ranking` and the
> `--gcl` path featurize atoms directly and do **not**. Driving stemming through
> `warren->stemmer()` would also mean mutating the handle's stemmer, and the only
> public setter — `Warren::set_stemmer()` — **persists** to the burrow's dna
> (`set_parameter_` → `set_parameter_in_dna`, `simple_warren.cc:142`), which would
> permanently make stemming the global default and destroy exact-by-default.
> Stemming in `jsonl_core` and targeting the features directly is uniform across
> `--text`/`--gcl`, needs no core change, and never writes to the burrow.

---

## 5. Query tool changes — `cottontail-jsonl-query`

- Flag **`--stem`** (boolean, default off; also accepted per-line in `--batch` as
  `"stem": true`).
  - default (off): exact, unchanged.
  - `--stem`: stem the query into `porter:` atoms and rank via cover density
    (`ssr`) per §4. Works for both `--text` and `--gcl`; `--gcl` operators are
    unchanged and only bare terms are stemmed. (`--stem` ranks via `ssr`
    regardless of `--ranker`, since stemmed atoms can't go through `icover`'s
    internal tokenization.)

- The query tool **never mutates the burrow** — it does not call
  `Warren::set_stemmer()` (see the §4 note on why). Default opens stay exact.

- **Detection / refuse mismatch.** Decide whether the burrow even has a stemmed
  stream by inspecting its dna **tokenizer**: name `stemming` means yes, and the
  tokenizer's nested recipe names the stemmer to use — use the **same** one
  (symmetry: index-time and query-time stemmers must match). If `--stem` is
  requested but the tokenizer is plain `ascii` (no stemmed stream), **exit 2**
  with a clear error. Do **not** silently fall back to exact — silent recall loss
  is exactly the failure this refuse-on-mismatch rule exists to prevent.

- best_passage spans and docid recovery are unchanged (addresses are shared).

- Search output (§4.4): add `"stemmed": true|false`, reflecting which stream the
  query ran against.

---

## 6. Agent-facing behavior to document (`--help` and docs)

- `--stem` trades precision for recall; **over-stemming is expected** — Porter
  conflates `university`/`universe`, `organization`/`organ`, `business`/`busy`.
  Because the tool's value is inspectable matches, exact stays the default so the
  agent reasons about precise matches and opts into recall deliberately.
- Short (< 3 char) and non-alphabetic terms (e.g. `covid19`) are **never
  stemmed**; under `--stem` they fall back to exact for that term automatically.
  This is correct, not a bug.
- **Tokenizer / non-ASCII.** The index defaults to the `utf8` tokenizer
  (Unicode-aware: whole-word accented/non-Latin tokens, Unicode case folding), so
  non-ASCII content is handled correctly. If the index was built with
  `--tokenizer ascii`, non-ASCII bytes are separators (e.g. `café` → `caf`) in
  **both** streams — an ASCII-only limitation, not stemming-specific. Note Porter
  is ASCII-only regardless: it does not stem non-ASCII words (they fall back to
  their exact `utf8` token), so `--stem` adds recall for English, not for accented
  or non-Latin terms.

---

## 6a. The `word*` family marker (`cover_search`) — per-atom, opt-in per term

The whole-query `--stem` flag above stems **every** term. The ISJ search agent
needs finer control: stem *this* word but keep *that* proper noun exact, without
knowing the engine's stem encoding. That is the **`word*` family marker**, served
by a **separate tool, `cover_search`** (not `search_gcl`, which stays a pure GCL
primitive with no `word*` handling).

- A bare term is **exact**: `bear` matches only `bear`.
- A term with a **single trailing `*`** matches the word **and its morphological
  family**: `bear*` matches `bear`, `bears`, …; `attack*` matches
  `attack`/`attacked`/`attacking`. Write the **full ordinary word** then `*` —
  never a shortened stem (`statistic*`, not `stat*`).
- Internally `word*` resolves through the burrow's **own Porter** (the single
  helper `resolve_family_atom` = `stem_atom`), so it targets the same
  `porter:<stem>` feature the index built — the agent never types `porter:`. An
  unstemmable word (`ox*`, short/non-alpha) falls back to the exact surface form
  (symmetric, no silent miss), exactly like `--stem`.
- `word*` is honored **inside a quoted phrase**: `"black bear*"` is desugared
  *before* the normal `expand_phrases` pass into `(>> (# 2) (... black porter:bear))`,
  so it matches the adjacent `black bears`. (The phrase is split on whitespace to
  preserve the trailing `*`, which the tokenizer would otherwise drop.)
- A **non-trailing / mid-token `*`** (e.g. `at*ack`) is a hard error (CLI exit 2 /
  server `400`), never a crash.
- `cover_search` requires a **stemmed stream**: a `word*` query against a burrow
  built without `--stem porter` is a hard error — **no** silent fallback to exact.
- `cover_search` ranks `:item` documents by `ssr` cover density and returns, per
  document, `{rank, score, cp, summary}`, where `summary` is a **cover-biased
  extractive summary** (windows centered on the query's covers, merged, with gaps
  shown as ` . . . `). It replaces the old `best_passage` (which was just the
  document head). It also returns `total_matches`/`unjudged_matches`/`atom_counts`
  and accepts `exclude` (judged cps; a cp post-filter) and a request-side `window`.

So: `--stem` = whole-query recall on `search_text`/`search_gcl`; `word*` =
per-term, opt-in recall on the dedicated `cover_search` tool. They are distinct
mechanisms and do not interact.

---

## 7. Tests to add (extend `test/jsonl.cc` + `test/jsonl_cli.cc`; library-level unless noted)

a. **Stemmed recall** — with a `--stem porter` index, `--stem "elephant"` matches
   a row whose body contains only `elephants`.
b. **Exact preserved** — without `--stem`, `elephant` does **not** match
   `elephants`; an index built **without** `--stem` behaves exactly as today (all
   existing §11 tests still pass).
c. **No-op fallback** — `--stem "ox"` still finds a row containing `ox` (proves
   the symmetric exact fallback for unstemmable terms).
d. **Missing-stream error** — `--stem` against a burrow built **without** `--stem`
   exits `2` with a clear error (no silent fallback).
e. **Position alignment** — a stemmed-term hit returns a correct `best_passage`
   span and correct `docid` (proves shared addresses).
f. **Over-stem pinned** — a fixture with two words sharing a Porter stem
   (`organization`/`organ`): `--stem` conflates them **and** exact keeps them
   separate. Locks the documented behavior so it can't regress silently.
g. **No dna mutation** — running a `--stem` query leaves the burrow's dna
   byte-for-byte unchanged (guards the `set_stemmer` landmine), and a subsequent
   default open is still exact.
h. **gzip parity** — stemming does not change the `.jsonl` vs `.jsonl.gz`
   equivalence.

Determinism: stemmed and exact share addresses, so the §11.5 tie caveats apply —
assert on **docid set membership**, not tied order.

---

## 8. Non-goals (unchanged)

- No BM25/LMD/PRF and no stats precompute (still excluded per §0.2).
- Stemming does **not** change the ranking model: cover-density (`icover`/`ssr`)
  still ranks; it simply operates over whichever stream the query targeted.
- Stemming and case handling add token postings only — no second text store, no
  per-(doc,term) annotation pass.
