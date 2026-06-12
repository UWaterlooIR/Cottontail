---
name: climbmix-poc-plan
description: ClimbMix POC direction — pivot to SimpleWarren, scaling target ~6500 shards, status
metadata:
  type: project
---

Goal: rework `apps/climbmix-poc.cc` (uncommitted scratch) to build a **static
SimpleWarren** over the gzip'd ClimbMix shards ([[climbmix-corpus-location]]) and
judge whether it scales to ~**6500** shards. Pivoted OFF the Bigwig→Hazel path
because [[hazel-not-ready]]. The JSONL CLI spec
(`docs/cottontail-jsonl-cli-spec.md`) already targets SimpleWarren; see
[[project-cottontail-overview]].

Machine: **512 GB RAM** (Mark, 2026-06-12) → can tune large build buffers.

POC plan (approved by Mark 2026-06-12): `Working::mkdir` → JSON featurizer (over
hashing) → utf8 tokenizer → `SimpleBuilder` → `Scribe::make(builder)` +
`scribe_jsonl` (already reads `.gz` via `inhale`/`zcat`) → produce tf-idf stats →
`finalize()` → `Warren::make(burrow)` (SimpleWarren) → rank a query. Burrow
written INSIDE the repo (`Scrapheap/`, gitignored). Measure per-stage time, peak
RSS, temp-disk high-water, FD count, burrow bytes on the 20 test shards;
extrapolate to 6500. Mechanics/limits in [[simplewarren-scaling-model]].

Bridge facts: `apps/simple.cc` `--json` builder is a STUB (`json_build` returns
false). The real static path is **Scribe-over-SimpleBuilder**. `trec-example.cc`
builds a **Bigwig**, not a SimpleWarren, despite the spec citing it as the model.

Reading these files is free; editing/committing still needs an approved plan and
running is in-scope for this experiment (reads authorized corpus, writes only
inside repo, no network).

## Results (2026-06-12, 1-shard baseline)

`apps/climbmix-poc.cc` was rewritten to the SimpleWarren path and runs green.
Build idiom mirrors `apps/treccast21-build.cc`: per row `add_text(docid)+":docno"`,
`add_text(contents)+":item"` (whole-row container); ascii/noxml tokenizer +
hashing featurizer; container `:item`, id `:docno`; then `tf_idf_annotations` →
`bm25_ranking`. Burrow at `Scrapheap/climbmix.burrow` (gitignored).

1 shard = 86,016 rows: **build 32 s, stats (`tf_idf_annotations`) 164 s, rank 2 ms**;
burrow 199 MB → 521 MB after stats; peak RSS 2.2 GB (default buffers).

**Headline finding:** query and build scale fine; the **`tf_idf_annotations`
stats precompute is the scaling blocker** — 5× build time, single-threaded,
CPU-bound (translate every doc → tokenize → stem → write a tf annotation per
(doc,term), >2× index size). Linear extrapolation to 6500 shards: build ~58 h,
**stats ~12 days**, rank still ~ms, disk ~3.4 TB, ~560 M rows. The 2 ms query
confirms [[simplewarren-scaling-model]] (on-demand postings + WAND, no rescan).
Next engineering lever = parallelize/replace the tf-idf stats pass. 100 shards
now available (Mark added them).

## Direction (2026-06-12): "powerful grep", drop BM25 precompute

Mark's intent is a **super-powerful grep-like tool for an agent**, which does NOT
need BM25. We confirmed Cottontail delivers this on the bare index (NO
`tf_idf_annotations`): full GCL structured search (Boolean `^`/`+`, phrase/region
`...`/`<>`, containment `<<`/`>>`) + cover-density ranked retrieval
(`icover_ranking`, `ssr_ranking`, `tiered_ranking`) + instant df/vocab/token
counts. Only BM25 and LMD need the expensive per-(doc,term) `tf` precompute; the
proximity rankers need none. See capability breakdown logic in `src/ranking.cc`
(icover `:389`, ssr `:305`, lmd `:1204` reads tf hopper, bm25 `:1307` gates on
`have(avgl/rsj/tf)`).

`apps/climbmix-poc.cc` rewritten accordingly: builds a no-precompute SimpleWarren
then demonstrates (a) term df, (b) icover ranking, (c) ssr proximity-AND,
(d) containment counting `(>> :item (^ ...))`, (e) arbitrary `--gcl`; BM25 is
opt-in `--bm25`. Verified on 3 shards (257k rows): build 97 s, all queries
0–23 ms, burrow 564 MB (~188 MB/shard, ~1/3 the size of the with-stats build).
GCL operator tokens: `^`=ALL_OF, `+`=ONE_OF, `...`/`<>`=FOLLOWED_BY,
`<<`=CONTAINED_IN, `>>`=CONTAINING. Container tag `:item`, id tag `:docno`.

**Verdict so far:** as a structured/ranked grep tool, SimpleWarren scales to 6500
shards (build ~58 h, queries stay ms, disk ~1.2 TB). A 100-shard no-stats run is
running for the full-scale confirmation (`Scrapheap/poc-100-nostats.log`).
