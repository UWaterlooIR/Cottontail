# Phrase (FollowedBy) performance on large indexes — findings and a proposal

**To:** Charles L. A. Clarke (author of Cottontail and the GCL algebra)
**From:** Mark Smucker's fork, investigation by Claude (Opus 4.8)
**Date:** 2026-07-02
**Status:** proposal / request for comment — no code changed yet
**Scope:** GCL phrase evaluation (`FollowedBy` / `Containing`) under `SimpleWarren`

---

## TL;DR

On a 100M-document `SimpleWarren` burrow, a four-facet cover query
(`tiered_query_search`) took **~712 s**. We traced the cost to a **single quoted
phrase** OR'd into one facet. That phrase adds **zero** results but 34× the run
time.

The mechanism, confirmed by profiling and a controlled experiment:

- A quoted phrase compiles to `(>> (# N) (... t1 … tn))` — `Containing` over
  `FollowedBy` (`src/parse.cc:211`).
- `FollowedBy(A, B)` is **asymmetric**: it produces one candidate interval **per
  occurrence of the first term `A`** (`src/gcl.cc:70`). To answer each boundary
  query, `Containing::rho_` loops once per `A`, grinding through every `A` to
  find the rare true adjacencies (`src/gcl.cc:136`).
- Inside a cover, that phrase hopper is re-driven **hundreds to thousands of
  times**. A phrase that enumerates fully in **~2 s** on its own consumed
  **~650 s** inside the cover — a **328×** blow-up (and **4000×** for a
  pathological reversed phrase).
- `gprof` attributes **~7 billion** `ArrayHopper::L_` probes to the query;
  **99.9%** are called from `FollowedBy::L_`. Posting decompression is **~1%** —
  this is entirely CPU spent walking hoppers in RAM, not I/O.

**The trigger is precise and testable:** a phrase is deadly when

```
        freq(FIRST word)
  ρ = ───────────────────────    is large.
      (times the phrase occurs)
```

`camp placement`: `camp`(635K) / 40 hits = **15,875** → 651 s. `site selection`:
`site`(4.8M) / 28,071 hits = **171** → 13 s, even though `site` is the *most
common* leading word. Reversing `campsite selection` (15 s) to `selection
campsite` (806 s) — same words, opposite order — is a **53× swing from word order
alone**.

**Recommendation.** Two independent, semantics-preserving fixes, in priority
order:

1. **Lazily materialize a phrase sub-hopper into an `ArrayHopper`** (general;
   fixes the worst case, including `camp placement`). The infrastructure already
   exists (`ArrayHopper::make(n, postings, qostings, fostings)`).
2. **Anchor `FollowedBy` on the rarer operand** (cheap; fixes the order-asymmetry
   cases like `selection campsite`, but *not* `camp placement`).

Details, code, and a validation plan follow. We would like your read on whether
(1) fits the architecture before we implement anything.

---

## Part I — Findings

### I.0 Setup and method

- **Index:** `/share/indexes/climbmix-100M-porter.burrow` — a `SimpleWarren`
  burrow, ~100M documents, ~250 GB on disk (pst 155 GB, raw 110 GB, docno-cp
  6 GB, idx 1.2 GB, txt 1.2 GB), Porter-stemmed.
- **Machine:** 503 GB RAM; during these runs 223 GB was in page cache and 229 GB
  free — i.e. the working set fits in RAM.
- **Server:** `//apps:cottontail-jsonl-server --threads 8`. Queries issued in
  parallel (`ThreadPoolExecutor`) at the agent's real `top_k = 200`.
- **Cold vs warm:** "cold" = fresh server process; "warm" = a second identical
  pass immediately after. (Note: restarting the server does *not* drop the OS
  page cache, so both passes are effectively page-cache-warm here — see I.1.)

The four facets (`F1..F4`) and the two tiers used below:

```
F1 = (+ backpack* hiker* trekker*)
F2 = (+ bear* "black bear*" "grizzly*" "bear-resistant")
F3 = (+ food* store* "food storage" "food cache*" "food protection")
F4 = (+ canister* hanging* "campsite selection" "site selection" "camp placement")
tier1 = (^ F1  (+ bear* "black bear*" "grizzly*")
              (+ food* store* "food storage" "food cache*")
              (+ canister* hanging* "campsite selection" "site selection"))
tier2 = (^ F1 F2 F3 F4)
```

`tier2` is `tier1` plus three phrase terms — one each into the bear, food, and
canister facets: `"bear-resistant"`, `"food protection"`, `"camp placement"`.
Both tiers return the **identical 5,765 matches**.

### I.1 Cold ≈ warm ⇒ CPU-bound, not I/O-bound

All six queries, run cold then warm (parallel, `top_k = 200`):

| query | cold | warm | matches |
|---|---:|---:|---:|
| F1 backpack | 3.5 s | 2.3 s | 391,279 |
| tier1 | 19.7 s | 18.8 s | 5,765 |
| F2 bear | 148 s | 147 s | 2,590,990 |
| tier2 | 713 s | 711 s | 5,765 |
| F4 canister/… | 2,923 s | 2,938 s | 1,874,198 |
| F3 food/… | 4,030 s | 4,023 s | 18,627,239 |

Warm ≈ cold within noise. With 223 GB cached and 229 GB free, the postings were
resident, yet the second pass was no faster. The cost is **CPU walking hoppers**,
not disk. (Confirmed again by the profile in I.4: decompression is ~1%.)

Corollary already visible here: a bare wide facet (`F3` alone, 4,030 s) is far
more expensive than the whole intersection that contains it (`tier2`, 713 s),
because the cover is lazy and pruned by the rarest facet. Facets should never be
evaluated standalone.

### I.2 Localizing the cost: it is one phrase

Starting from `tier1` and adding the three `tier2` phrases one at a time
(parallel, warm, `top_k = 200`):

| query | time | Δ vs tier1 | matches |
|---|---:|---:|---:|
| tier1 (baseline) | 18.9 s | — | 5,765 |
| + `"bear-resistant"` (B) | 35.2 s | +16 s | 5,765 |
| + `"food protection"` (C) | 59.9 s | +41 s | 5,765 |
| + `"camp placement"` (D) | **649.5 s** | **+630 s** | 5,765 |
| tier2 (all three) | 711.8 s | +693 s | 5,765 |

`"camp placement"` alone accounts for **630 s of the 693 s** — and adds **zero**
matches.

### I.3 It is not the phrase in isolation — it is emergent in the cover

| query | time | matches |
|---|---:|---:|
| `"camp placement"` standalone (full enumeration) | **1.98 s** | 40 |
| `(^ F1 F2b F3b "camp placement")` — phrase as the whole 4th facet | **0.14 s** | 1 |
| `(^ F1 F2b F3b (+ canister* hanging* "camp placement"))` | **631 s** | 5,681 |

The phrase enumerated on its own is trivial (2 s, 40 hits). It becomes deadly
only when OR'd into a dense facet inside the cover. Operand order within the
cover is irrelevant (reordering the offending facet first vs last: 648 s vs
658 s).

### I.4 Profile — where the 36 minutes go

`//apps:cottontail-jsonl-query` rebuilt with `-pg` (same `-c dbg -Og` flags as the
server), run on `tier2`, `top_k = 200`. 36 min wall, correct 5,765 result. `gprof`
flat profile (self-time):

| self | calls | function |
|---:|---:|---|
| 13.6% | 2.66 B | `(anon)::hopping` (array gallop) |
| 13.6% | 2.66 B | `(anon)::gnippoh` (array gallop, **reverse**) |
| 13.2% | **6.95 B** | `ArrayHopper::L_` |
| 9.0% | **6.95 B** | `ArrayHopper::R_` |
| 4.1% | 3.47 B | `FollowedBy::L_` |
| 2.7% | 3.47 B | `FollowedBy::R_` |
| ~15% | ~1.7 B ea | `Combinational::tau_/uat_`, `Hopper::tau/rho/uat/ohr` |
| ~11% | 1.7 B | `FixedWidthHopper::rho_/ohr_/tau_/uat_` |
| 1.8% | 4.8 M | `Containing::rho_` |
| **0.78%** | **21** | `decode_all` (**zlib posting decode**) |

Two things stand out:

1. **Decompression ran 21 times (0.78%).** The postings were read essentially for
   free; the entire cost is in-RAM hopper iteration. This is a CPU problem.
2. **The call arithmetic pins the cause.** The call graph shows
   `ArrayHopper::L_`'s callers are `FollowedBy::L_` (6,948,127,167 calls, **99.9%**)
   and `Or::L_` (5,392,224, **0.08%**). And 6.95 B = exactly 2 × 3.47 B — each
   `FollowedBy::L_` makes two leaf probes (`left_->L`, `right_->L`;
   `src/gcl.cc:70`). The ~7 billion array probes are, to rounding, **entirely**
   generated by the phrase's `FollowedBy`. The wildcard/OR terms contribute a
   rounding error.

Note the heavy **reverse-direction** traffic (`gnippoh` 2.66 B; `Hopper::uat/ohr`;
`Combinational::uat_`). The cover's `Combinational::rho_`/`ohr_` probe backward
(`L(k-1)`, `R(k+1)`; `src/gcl.cc:38,52`), so the phrase is scanned in **both**
directions with no monotonic amortization — the cursor thrashes.

### I.5 The trigger, isolated by controlled experiment

Same cover skeleton `(^ F1 F2b F3b (+ canister* hanging* PHRASE))`, varying only
`PHRASE` (parallel, warm, `top_k = 200`):

| PHRASE | ρ = freq(1st word) / occurrences | predicted | **measured** |
|---|---:|---|---:|
| *(none — floor)* | — | — | 9.8 s |
| `site selection` | 4.8M / 28,071 = 171 | fast | **13.2 s** |
| `campsite selection` | 49K / 495 = 99 | fast | **15.2 s** |
| `camp placement` | 635K / 40 = 15,875 | deadly | **651 s** |
| `selection campsite` (reversed) | 2.5M / ~0 = huge | deadly | **806 s** |

This falsifies "phrases are slow" and "frequent words are slow":

- `site` is the **most common** leading word of the set (4.8M) yet
  `"site selection"` is ~free (13 s). Raw frequency is exonerated.
- `"campsite selection"` (15 s) vs the **same two words reversed**,
  `"selection campsite"` (806 s): a **53× swing from word order alone**, identical
  vocabulary and identical result count. This is the `FollowedBy` asymmetry made
  visible.

Excess-over-floor tracks ρ: ρ≈100 → +5 s; ρ≈16,000 → +641 s; ρ→∞ → +796 s.

**Statement of the trigger.** A phrase is expensive when its **first** word is
common relative to how often the exact phrase occurs. A phrase led by a rare word
is cheap regardless of the second word; a phrase led by a common word that rarely
forms that pair is a landmine (`"the summit"`, `"of climbing"`, `"is a"`, …). The
cost of one phrase term can dwarf the entire rest of the query while contributing
nothing to the result set.

---

## Part II — Root cause, in code

The chain, top to bottom:

**1. Phrase compile** (`src/parse.cc:211`):

```
"camp placement"  ⟶  (>> (# 2) (... camp placement))
                  =   Containing( FixedWidth(2), FollowedBy(camp, placement) )
```

**2. `FollowedBy` is asymmetric — one interval per first term** (`src/gcl.cc:70`):

```cpp
addr FollowedBy::L_(addr k) {                 // driven by right_, anchored on left_
  switch (addr ll = right_->L(k)) {
  case minfinity: return minfinity;
  case maxfinity: return maxfinity;
  default:        return left_->L(ll - 1);    // ← two leaf probes per call
  }
}
addr FollowedBy::R_(addr k) {
  switch (addr rr = left_->R(k)) {            // ← walks left_ (the FIRST word)
  case minfinity: return minfinity;
  case maxfinity: return maxfinity;
  default:        return right_->R(rr + 1);
  }
}
```

`(... A B)` yields, for each `A`, the interval `[A, next-B-after-A]`. There are
`freq(A)` such intervals, most of them spanning a large gap; the enclosing
`(# 2)` keeps only those where `B` is truly adjacent.

**3. `Containing::rho_` loops once per first-word** (`src/gcl.cc:136`):

```cpp
void Containing::rho_(addr k, addr *p, addr *q, fval *v) {
  for (;;) {
    left_->rho(k, p, q, v);                   // the (# 2) window
    if (*q == maxfinity) return;
    right_->tau(*p, &pp, &qq);                // the FollowedBy candidate
    if (qq <= *q) return;                     // window contains it → done
    k = qq;                                    // else advance past it and retry
  }
}
```

To answer "next phrase occurrence ≥ k", this consumes `FollowedBy` candidates one
`A` at a time until it finds a real adjacency. Between two true hits it spins
`freq(A)/occurrences` times — exactly ρ.

**4. The leaf probe is already good** (`src/array_hopper.cc:14`). `hopping`
(and reverse `gnippoh`) is a galloping/exponential search plus binary search from
a cached cursor — `O(log distance)` per probe, not a linear scan. **So the disease
is not slow probes; it is ~7 billion of them.** Each phrase boundary query spins
`Containing` over many `A`'s, and the cover issues millions of phrase boundary
queries and re-drives them bidirectionally.

**5. The cover re-drives the phrase hundreds–thousands of times.** The phrase
enumerated once costs 1.98 s (I.3); inside the cover it costs 651 s. The blow-up
factor is the number of independent re-evaluations:

| phrase | one full pass | in cover | re-drives |
|---|---:|---:|---:|
| `camp placement` | 1.98 s | 651 s | **328×** |
| `selection campsite` | 0.20 s | 806 s | **4000×** |

---

## Part III — Proposal (solution space)

All options below are **semantics-preserving** (identical result intervals);
they differ only in cost and in how invasive they are. We rank them.

### Why per-probe tuning alone cannot fix the worst case

To find "the next `camp placement` at/after k", *any* streaming algorithm — even
an optimal two-sided skip/zig-zag merge — must inspect the rarer constituent's
postings that fall in the gap `[k, next-hit]`. For `camp placement` the rarer
word is `camp` (635K) and hits are 40, so a gap holds ~16K `camp` postings. That
is `Ω(freq(rarer) between hits)` per advance, fundamentally. The **only** way to
make a phrase advance sublinear in that gap is to have the phrase's own postings
precomputed. This is why materialization (below) is the primary recommendation
and skip-tuning is secondary.

### Option A — Anchor `FollowedBy` on the rarer operand *(cheap; partial)*

At plan time, `warren->idx()->count(...)` is available (the server already calls
it for `atom_counts`; `apps/jsonl_core.cc:845`). Build `FollowedBy` so that
iteration is driven by whichever operand is rarer, verifying the other at the
required offset/direction. This makes the cost `O(freq(rarer))` instead of
`O(freq(first))`, so word order stops mattering.

- **Fixes:** the asymmetry cases — `"selection campsite"` becomes as cheap as
  `"campsite selection"`.
- **Does NOT fix:** `"camp placement"`. There the rarer word (`camp`) is already
  first, so ρ is unchanged, and the cover still re-drives it. **This is the
  important caveat:** Option A alone leaves the worst real case slow.
- **Cost:** small, local to `FollowedBy` construction. Lowest risk.

### Option B — Lazily materialize a phrase sub-hopper into an `ArrayHopper` *(general; recommended)*

On first evaluation, run the phrase hopper to exhaustion **once**, collect its
`(p, q, v)` intervals into arrays, and serve all subsequent
`tau/rho/uat/ohr/L_/R_` from an internal `ArrayHopper` built via the existing
factory (`src/array_hopper.h`):

```cpp
static std::unique_ptr<Hopper>
ArrayHopper::make(addr n, std::shared_ptr<addr> postings,
                  std::shared_ptr<addr> qostings,
                  std::shared_ptr<fval> fostings = nullptr);
```

Sketch (a wrapper hopper; ~a single new file, no change to `FollowedBy`/
`Containing` semantics):

```cpp
class Materialized final : public Hopper {
  // On first wait(): drive wrapped_ forward once, pushing (p,q,v) into
  // p_/q_/f_ vectors; if the count exceeds cap_, abandon and fall back to
  // streaming wrapped_ directly. Otherwise build inner_ = ArrayHopper::make(...)
  // and delegate every tau_/rho_/uat_/ohr_/L_/R_ to it.
};
```

Effect on the cover: each of the ~millions of phrase boundary queries becomes an
`O(log · #hits)` gallop over a 40-element array instead of a ~700-deep `A`-scan.
The one-time build is a single forward pass — the standalone enumeration cost we
measured: **~2 s** for `camp placement`. Expected `tier2`: **~713 s → ~20 s**
(tier1 level).

- **Fixes:** *all* cases, including `camp placement` and `selection campsite`.
- **Self-selecting cap.** Materialization cost and benefit are inversely
  correlated. Deadly phrases are **rare** (few hits) → they materialize cheaply
  and gain enormously. Dense phrases (many hits) would be expensive to
  materialize — but a dense phrase has hits every few first-words, so
  `Containing` barely spins and streaming is already cheap. A cardinality cap
  `cap_` (e.g. 10⁵–10⁶ intervals): materialize under the cap, stream over it.
  This bounds extra memory and captures exactly the pathological phrases.
- **Generality.** Nothing here is phrase-specific; it accelerates **any**
  expensive-to-probe, low-cardinality sub-expression that a parent re-drives
  (e.g. a rare `(^ …)` reused across a query). We suggest scoping v1 to phrases.
- **Risk:** low. Pure performance; results provably identical (same interval
  stream, just precomputed). The main design choices are *where* to insert it
  (see Open Questions) and the cap policy.

### Option C — Native positional phrase operator with two-sided skip *(bigger; ≈ A without caching)*

Replace `(>> (# N) (... …))` with a dedicated N-ary adjacency hopper that
galloping-merges the constituents with skip pointers, anchored on the rarest. In
isolation this is clean, but note it is still `Ω(freq(rarest) in gap)` per
advance and is still re-driven by the cover — so **without** the materialization
of Option B it does not fix `camp placement`. Worth doing as the "right" phrase
primitive, but B is what removes the re-driving cost.

### Option D — Memoize boundary results on the phrase hopper *(subsumed by B)*

A small LRU over `(k → interval)` would cut the bidirectional re-probing. Option
B is the limiting case (full memoization via a sorted array) and is simpler and
more predictable; we mention D only for completeness.

### Option E — Index-time phrase features *(heavyweight; zero query cost)*

Featurize selected phrases/bigrams at index time so a hot phrase resolves to a
single term posting list. Zero query-time cost, but index bloat and you must know
the phrases in advance. Out of scope for a query-engine fix; noted for the record.

### Recommendation

- **Ship B** (lazy materialization with a cardinality cap) as the primary fix —
  it is the only option that addresses the measured worst case, it is
  semantics-preserving and low-risk, and it reuses `ArrayHopper`.
- **Add A** (anchor-on-rarer `FollowedBy`) as a cheap, orthogonal win that also
  helps non-materialized paths and any streaming fallback above the cap.
- Consider **C** later as the principled phrase primitive.

---

## Part IV — Validation plan

All experiments above are reproducible against
`/share/indexes/climbmix-100M-porter.burrow` via `//apps:cottontail-jsonl-server`
and `POST /tools/cover_search` (or `/tools/tiered_query_search`). Acceptance for a
fix:

1. **Correctness:** every query in Parts I/III returns the **identical**
   `total_matches` and top-`k` as today (5,765 for the tiers). This is the
   non-negotiable gate.
2. **`tier2` drops** from ~713 s to within ~2× of `tier1` (~20–40 s).
3. **Trigger table flattens:** `camp placement` and `selection campsite` in the
   I.5 skeleton fall from 651 s / 806 s to near the 9.8 s floor.
4. **Profile shifts:** `FollowedBy::L_/R_` call counts drop by orders of
   magnitude; `ArrayHopper` probes fall from ~7 B to the low millions.
5. **No regression** on `bazel test //test:tests //test:hazel_test`, and on the
   fast, dense phrases (`site selection`, `campsite selection`) which must stay
   fast.

`gprof` reproduction: `bazel build -c dbg --cxxopt=-Og --copt=-pg --linkopt=-pg
//apps:cottontail-jsonl-query`, run with `GMON_OUT_PREFIX` set, then `gprof -b`.
(`perf` was unavailable here — `kernel.perf_event_paranoid = 4`.)

---

## Part V — Open questions for you, Charlie

1. **Where should materialization live?** Options: (a) a `Materialized` wrapper
   hopper inserted by the phrase expander in `src/parse.cc` around every
   `(>> (# N) (...))`; (b) a general planner pass that wraps any sub-expression
   whose estimated cardinality × parent re-drive factor crosses a threshold; (c) a
   new explicit GCL operator the query author (or the phrase expander) can emit.
   We lean toward (a) for v1.
2. **Cap policy.** Is a fixed interval cap (say 10⁶) acceptable, or would you
   prefer a memory budget, or a cost model using `idx()->count()` of the
   constituents to decide up front?
3. **Is `FollowedBy`'s left-anchoring load-bearing** anywhere we should preserve
   (Option A changes drive direction, not semantics — but we want to be sure no
   caller depends on the interval *identity* `[A, next-B]` rather than the final
   phrase intervals)?
4. **Appetite for the native phrase operator (Option C)** as the long-term
   primitive, or is materialization-over-the-existing-compile sufficient?

We will not implement until you have weighed in on (1) and the overall approach.

---

## Appendix — environment and exact queries

- Index: `/share/indexes/climbmix-100M-porter.burrow` (SimpleWarren, ~100M docs,
  ~250 GB, Porter). Machine: 503 GB RAM. Server: `--threads 8`, `top_k = 200`.
- Constituent counts (occurrences): `food` 12,174,656 · `site` 4,812,352 ·
  `protection` 4,056,498 · `selection` 2,507,550 · `resistant` 1,895,447 ·
  `bear` 1,226,053 · `hanging` 849,262 · `placement` 836,391 · `camp` 635,410 ·
  `canister` 61,708 · `campsite` 49,645.
- Phrase occurrences: `camp placement` 40 · `campsite selection` 495 ·
  `food protection` 5,758 · `bear-resistant` 2,936 · `site selection` 28,071 ·
  `selection campsite` 4.
- Key code: `src/parse.cc:211` (phrase compile) · `src/gcl.cc:70` (`FollowedBy`
  L_/R_) · `src/gcl.cc:136` (`Containing::rho_`) · `src/gcl.cc:34,38,52`
  (`Combinational` tau_/rho_/ohr_) · `src/array_hopper.cc:14` (`hopping`) ·
  `src/array_hopper.h` (`ArrayHopper::make`).

---

## Addendum (2026-07-04) — `(materialize …)` wrapping tested at 100M scale: rejected

After the upstream sync brought in Clarke's `(materialize X)` operator
(`gcl/materialize.{h,cc}`: lazily enumerate `X` once, snapshot to an array,
answer later probes by binary search — his `ai/improvements.md` suggests exactly
this manual fix for our query shape), we scouted **blanket phrase-wrapping** —
every multi-atom quoted phrase wrapped in `(materialize …)` — as a candidate
app-layer fix (backlog TASK-28). A 1M-burrow validation looked promising
(killer tier 6.0 s → 1.25 s, identical results). **At 100M scale it fails:**

| case (100M, `top_k=200`, `rank_threads=8`) | plain | wrapped |
|---|---|---|
| tier1 baseline (no deadly phrase) | 15.1 s | — |
| `+ "camp placement"` killer | 728.4 s | 353.8 s (2.1×; still 24× over baseline) |
| tier2 (all three added phrases) | ~712 s (doc.) | 519.5 s |
| facet with reversed `"selection campsite"` | ~806 s (doc.) | 256.4 s |
| broad many-results query | **4.0 s** | **127.5 s (32× worse)** |
| `"camp placement"` standalone | 0.5 s | 3.8 s (7.6× worse) |

(Data: `isj/scouting/multitext-dsl-2/captured/2026-07-04-materialize-100m.jsonl`;
harness `…/run_materialize_100m.py`. Server freshly restarted per run set;
client timeouts disabled.)

**Why it fails.** `Materialize` enumerates the wrapped expression over the
*full shard*, unconditionally — and in our parallel ranking
(`parallel_cover_ranking`, TASK-25), *once per rank-worker*, since workers build
their own hoppers. Plain evaluation never pays that: the cover recurrence only
**probes** the phrase at candidate positions, and the range split already
confines each worker's re-driving to its slice. So wrapping converts cheap lazy
probing into mandatory global enumeration — a `"food storage"`-class phrase
(frequent first word) costs ~2 minutes to enumerate at 100M. Wrapping wins only
when *this query's* accumulated re-drive cost exceeds the phrase's full
enumeration cost, which cannot be known in advance: the ρ trigger's denominator
(phrase occurrence count) is only learned *by* enumerating.

**Consequence for the proposal above.** This strengthens Option A
(**rarest-term driving** inside `FollowedBy`): it fixes the per-probe cost at
the source, needs no cost model, adds no global enumeration, and composes with
parallel ranking. Materialization remains attractive only as a *planner*
decision for provably-cheap-to-enumerate subexpressions (Clarke's optimizer
checkpoint reaches the same "not ready to be default-on" conclusion from the
other direction), or with a range-aware / shared-across-workers `Materialize`,
which would require engine changes anyway.
