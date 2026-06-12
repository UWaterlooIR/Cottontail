---
name: simplewarren-scaling-model
description: How SimpleWarren build & query scale (external-memory build, on-demand posting reads, WAND ranking) + tuning levers
metadata:
  type: project
---

Verified 2026-06-12 by reading `src/simple_builder.{h,cc}`, `src/simple_idx.{h,cc}`,
`src/ranking.cc`. These are the non-obvious conclusions behind the climbmix
SimpleWarren experiment ([[climbmix-poc-plan]]). (Earlier I wrongly assumed the
build was all-in-RAM — it is not.)

**Build is external-memory (SPIMI), NOT all-in-RAM.** `SimpleBuilder` buffers
tokens/annotations in RAM, spills *sorted* temp files when a buffer exceeds
`tok_file_size_`/`ann_file_size_` (constructor args; default `256*1024*1024`
**records** ≈ 4 GB tok / 8 GB ann), then `finalize()` does a streaming k-way
merge (`build_index`) emitting the final `.idx`/`.pst`. Peak RAM ≈ buffer size,
independent of corpus size. Raw text is written straight to disk as compressed
chunks during ingest.
- Real scaling limits (not RAM): transient **temp disk** (≈ whole tokenized
  corpus before merge), **open FDs at merge** (`build_index` opens every spill
  file at once, count ∝ corpus/buffer — raise buffers to reduce), a single
  monolithic burrow, and a single-threaded merge.

**Query loads only portions on demand.** `SimpleIdx::make` loads ONLY the `.idx`
dictionary into RAM (`pst_map_` = one 16-byte IdxRecord per *distinct feature*).
Postings stay on disk: `hopper_(feature)` binary-searches the dict and `pread`s
only that feature's compressed bytes from `.pst`, decompresses, caches. df is a
tiny header read (`count_`). The posting cache has an LRU eviction cap
`large_limit_` = **hardcoded 1 GB** (`simple_idx.h:63`), NOT a recipe param.

**Ranking does NOT rescan the collection.** `bm25_ranking` (`ranking.cc:1307`) is
WAND over query-term hoppers only, with skip-ahead; document length = posting
interval width (`qivot-pivot+1`), so scoring reads no text. BUT it early-returns
empty unless `stats->have("avgl") && have("rsj") && have("tf")` — **silent zero
results if those stats are absent.** Confirm how avgl/rsj/tf are produced on a
plain SimpleWarren vs. the meadow forager path (the open question for the POC).

**Tuning levers for the 512 GB machine:** (1) build buffers
`tok_file_size`/`ann_file_size` — crank up. (2) query posting-cache `large_limit_`
(hardcoded 1 GB) — small code change needed to make it tunable if we want more
hot postings. See [[climbmix-corpus-location]] for the machine/corpus.
