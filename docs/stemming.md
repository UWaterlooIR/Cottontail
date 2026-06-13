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
stats**. (This lands on branch `feature/stemming-tokenizer`; it must be merged /
available before doing the CLI work below.)

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

## 4. How a query reaches the stemmed stream (mechanism — read before coding)

The cover-density rankers already contain the only hook needed. They split the
query with `warren->tokenizer()->split()` (surface terms) and compute each lookup
feature as `featurize(warren->stemmer()->stem(token))`
(`src/ranking.cc`, e.g. `icover_ranking` ≈ `:988`, `ssr_ranking` ≈ `:1142`):

- `warren->stemmer()` is the **`NullStemmer`** → `stem()` returns the surface
  unchanged → `featurize(surface)` → **exact stream**.
- `warren->stemmer()` is **Porter** → `stem()` returns `"porter:…"` →
  `featurize("porter:…")` → **stemmed stream** (the one the tokenizer populated).

A burrow built per §3 opens with **no** warren-level stemmer — the `Warren`
constructor defaults `stemmer_` to `NullStemmer` (`src/warren.h:37`) and dna
carries none — so **queries are exact by default**. Good.

A no-op query term is safe and symmetric: `--stem "ox"` → Porter returns `"ox"`
(`stemmed=false`) → `featurize("ox")` → matches the exact `ox` postings the
tokenizer always wrote. No silent miss. The dangerous inverse can't happen: the
query never looks for a `porter:ox` the index didn't write, because Porter never
produces one.

---

## 5. Query tool changes — `cottontail-jsonl-query`

- Add flag **`--stem`** (boolean, default off).
  - default (off): exact, unchanged.
  - `--stem`: run the **same** ranking / `--gcl` path, but with a Porter stemmer
    active **on the handle**, so the rankers target the stemmed stream. `--gcl`
    operators are unchanged; bare terms get stemmed.

- **Activating the stemmer — avoid the landmine.** `Warren::set_stemmer()`
  (`src/warren.h:79`) **persists** the stemmer to the burrow's dna:
  `set_parameter_` → `set_parameter_in_dna` writes disk immediately
  (`simple_warren.cc:142–146`). Calling it on a query handle would permanently
  make stemming the **global default** — exactly the failure this design avoids.
  **Do not use `set_stemmer()` for the per-query toggle.**
  - Recommended: give the handle an **in-memory-only** Porter for `--stem`
    queries, mutating nothing on disk. The minimal safe enabler is a
    non-persisting, handle-local stemmer setter on `Warren` (set `stemmer_`
    without calling `set_parameter`); add it if it doesn't exist. Equivalent
    alternatives: thread a stemmer argument into the ranking call, or compose the
    hopper at the feature level. Whichever you choose, the invariant is
    absolute: **default open = exact, and the query tool writes nothing to the
    burrow.**

- **Detection / refuse mismatch.** Decide whether the burrow even has a stemmed
  stream by inspecting its dna **tokenizer**: name `stemming` means yes, and the
  tokenizer's nested recipe names the stemmer to use — use the **same** one
  (symmetry: index-time and query-time stemmers must match). If `--stem` is
  requested but the tokenizer is plain `ascii` (no stemmed stream), **exit 2**
  with a clear error. Do **not** silently fall back to exact — silent recall loss
  is the failure `--explain` exists to surface.

- best_passage spans and docid recovery are unchanged (addresses are shared).

- Search output (§4.4): add `"stemmed": true|false`, reflecting which stream the
  query ran against.

- `--explain` (§4.5): for each leaf term, report `"stream": "exact"|"stemmed"`
  and the `df` from **that** stream (for stemmed, `featurize` the stemmer's
  output). A stemmed term with zero stemmed postings is then detectable.

---

## 6. Agent-facing behavior to document (`--help` and docs)

- `--stem` trades precision for recall; **over-stemming is expected** — Porter
  conflates `university`/`universe`, `organization`/`organ`, `business`/`busy`.
  Because the tool's value is inspectable matches, exact stays the default so the
  agent reasons about precise matches and opts into recall deliberately.
- Short (< 3 char) and non-alphabetic terms (e.g. `covid19`) are **never
  stemmed**; under `--stem` they fall back to exact for that term automatically.
  This is correct, not a bug.
- **Non-ASCII caveat (pre-existing, not stemming-specific).** The `ascii`
  tokenizer is ASCII-only and treats non-ASCII bytes as separators, so
  accented/UTF-8 words are split or truncated (e.g. `café` → `caf`) in **both**
  streams. Document it; it affects all retrieval, not just stemming.

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
e. **`--explain` stream labeling** — per-term `stream` = `exact`|`stemmed` and the
   `df` comes from the correct stream.
f. **Position alignment** — a stemmed-term hit returns a correct `best_passage`
   span and correct `docid` (proves shared addresses).
g. **Over-stem pinned** — a fixture with two words sharing a Porter stem
   (`organization`/`organ`): `--stem` conflates them **and** exact keeps them
   separate. Locks the documented behavior so it can't regress silently.
h. **No dna mutation** — running a `--stem` query leaves the burrow's dna
   byte-for-byte unchanged (guards the `set_stemmer` landmine), and a subsequent
   default open is still exact.
i. **gzip parity** — stemming does not change the `.jsonl` vs `.jsonl.gz`
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
