# Repro: phrase (FollowedBy) performance investigation

Reproduction harnesses and raw captured data behind
[`../phrase-search-performance-and-proposal.md`](../phrase-search-performance-and-proposal.md).
Read that document first — it interprets everything here.

## What this shows

A single quoted phrase (`"camp placement"`) OR'd into one facet of a 4-facet
cover query on a 100M-document burrow turned a ~19 s query into ~650 s while
adding **zero** matches. The cost is CPU spent re-driving the phrase's
`FollowedBy` hopper billions of times. The deadliness trigger is
`freq(first word) / (times the phrase occurs)`.

## Environment (all runs)

- Index: `/share/indexes/climbmix-100M-porter.burrow` (SimpleWarren, ~100M docs,
  ~250 GB, Porter). Not in the repo.
- Server: `bazel-bin/apps/cottontail-jsonl-server --burrow <burrow> --host
  127.0.0.1 --port 8080 --threads 8 --no-auth`
- Queries: `POST /tools/cover_search` (and `/tools/tiered_query_search`),
  `top_k = 200`, issued in parallel.
- Harnesses use `httpx`; run e.g. `uv run --directory ../../.. python harness/trigger.py`
  (they hard-code `http://127.0.0.1:8080`).

## harness/  (Python)

| script | produces | what it measures |
|---|---|---|
| `parallel200.py` | `data/01-cold-vs-warm.txt` | F1–F4, tier1, tier2 cold then warm → cold≈warm (CPU-bound) |
| `decomp.py` | `data/02-…-decomposition.txt` | tier1 + each tier2 phrase one at a time → isolates `camp placement` |
| `probe.py` | `data/03-word-and-phrase-counts.txt` | constituent word counts + standalone phrase timings |
| `mech.py` | `data/04-mechanism-discrimination.txt` | phrase-only vs phrase-in-OR vs reordered → cost is emergent in the cover |
| `trigger.py` | `data/05-trigger-test.txt` | same cover, vary only the phrase → confirms the ρ trigger + word-order asymmetry |
| `one.py` | (stdout) | clean standalone full enumeration: `camp placement` 1.98 s / 40; `selection campsite` 0.20 s / 4 |

## data/

Raw captured stdout from the runs above, plus:

- `tier2-flat-profile.txt` — `gprof -b` flat profile of `tier2` and the
  call-graph block proving 99.9% of `ArrayHopper::L_` calls come from
  `FollowedBy::L_`. Profiled binary:
  `bazel build -c dbg --cxxopt=-Og --copt=-pg --linkopt=-pg //apps:cottontail-jsonl-query`,
  run with `GMON_OUT_PREFIX` set, then `gprof -b <bin> gmon.<pid>`.
  (`perf` was unavailable: `kernel.perf_event_paranoid = 4`.)

## Headline numbers

| | time | matches |
|---|---:|---:|
| tier1 | 18.9 s | 5,765 |
| tier2 (= tier1 + 3 phrases) | 711.8 s | 5,765 |
| tier2 with only `+ "camp placement"` removed's effect isolated | +630 s | — |
| `"camp placement"` standalone (1 pass) | 1.98 s | 40 |
| `"camp placement"` inside the cover | 651 s | — (328× re-drive) |
| `"campsite selection"` vs reversed `"selection campsite"` | 15 s vs 806 s | — (53× from word order) |
