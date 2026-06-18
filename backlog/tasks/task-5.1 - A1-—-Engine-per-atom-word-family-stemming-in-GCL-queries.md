---
id: TASK-5.1
title: 'A1 — Engine: cover_search tool with per-atom word* family stemming'
status: Done
assignee: []
created_date: '2026-06-17 12:49'
updated_date: '2026-06-18 17:35'
labels:
  - engine
  - cpp
  - searcher
dependencies: []
references:
  - docs/searcher-agent-lessons-June-16-2026.md
  - docs/stemming.md
  - docs/cottontail-jsonl-cli-spec.md
  - apps/jsonl_core.cc
  - apps/jsonl_core.h
  - src/parse.cc
  - test/jsonl.cc
  - test/jsonl_cli.cc
  - CLAUDE.md
parent_task_id: TASK-5
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Where this lives (architecture — read before touching anything)

C++ change in the JSONL search-tool layer. This task CREATES A NEW TOOL, `cover_search`
— it does NOT modify the existing `search_gcl`. The Cottontail server is just a collection
of tools (`/tools/<name>` + `/describe`); it is NOT aware of agents or profiles. cover_search
is simply one more tool the server offers.

1. GCL core — `src/parse.cc`, `src/gcl.h`, the hoppers. DO NOT MODIFY. Read only.
2. `search_gcl` — the existing tool, a PURE interface to GCL. LEAVE IT ALONE: it must NOT
   learn about `word*`. (The earlier POC agent perverted search_gcl by piling agent
   conveniences onto it; we are undoing that by adding a separate cover_search tool.)
3. NEW tool `cover_search` — the ISJ agent's search tool. ALL of this task's behavior goes
   here: a new function in `apps/jsonl_core.{h,cc}`, a new endpoint `POST /tools/cover_search`
   added alongside the existing `/tools/*` endpoints in `apps/cottontail-jsonl-server.cc`,
   and included in `describe_json` (which lists the server's tools).
4. Python isj agent — separate track; it later calls `cover_search`.

May modify: `apps/jsonl_core.{h,cc}`, `apps/jsonl_json.{h,cc}` (cover_search schema +
serialization), `apps/cottontail-jsonl-server.cc` (add the endpoint),
`apps/cottontail-jsonl-query.cc` (a way to run cover_search for testing); tests in
`test/jsonl.cc`, `test/jsonl_cli.cc`, `test/jsonl_server.cc`; docs `docs/stemming.md`,
`docs/cottontail-jsonl-cli-spec.md`, `docs/cottontail-search-server-spec.md`.
Must NOT modify: `src/parse.cc`, `src/gcl.h`, the GCL core, or `search_gcl`'s behavior.
Language: C++. No task dependencies (this is the engine track's entry point).

## Context

The ISJ agent (separate track) writes Boolean cover queries and wants a word AND its
morphological family without enumerating inflections or knowing the engine's stem
encoding. The agent-facing surface is a trailing asterisk on a single word: `bear*` =
"match bear and its family (bears, attacked, ...)". Validated across gpt-oss-120b,
Qwen3.6-27B, gemma-4-31B (docs/searcher-agent-lessons-June-16-2026.md).

`cover_search` is the dedicated tool that understands `word*`. `search_gcl` stays a pure
GCL primitive (and keeps its own whole-query `--stem` flag); the two are separate tools.
Stem parity: the stemmed feature is `porter:` + Cottontail's Porter(word), so resolve via
the burrow's own Porter (`stem_atom(burrow_stemmer(warren), word)`); a second (Python)
Porter would drift. Porter::stem sets stemmed=true and returns `porter:<stem>` for any
alphabetic word >= 3 chars (even when the stem equals the word), so the stemmed stream is
symmetric: `porter:bear` matches both "bear" and "bears". Short/non-alpha words fall back to
the exact surface form.

How the stemmed stream works (docs/stemming.md 4-5): an index built with `--stem porter`
co-locates a stemmed stream; a stemmed feature is `porter:`+Porter(word); GCL leaves
featurize verbatim, so `porter:<stem>` resolves to it.

How ssr scores (so you know what covers are): ssr enumerates the query's minimal COVERS
(p,q) and, per :item, scores the document as the SUM over its covers of 1/(K + q - p).
A document typically contains MULTIPLE covers. (Today's ssr returns only the CONTAINER
span as a result and jsonl_core mislabels it `best_passage` = the document head — this
task replaces that with a real cover-biased summary, see below.)

## Required behavior (the contract) — all in the NEW cover_search tool

1. cover_search takes a GCL cover query that MAY use `word*`, ranks documents (:item) by
   `ssr` cover density (score = sum over the document's covers of 1/(K+q-p)), and returns
   per document: { rank, score, docid, summary }. `summary` REPLACES the old
   `best_passage` (which was merely the document head). (A2 adds the request `window`
   override plus total_matches/unjudged_matches/atom_counts/exclude_docids.)
2. `word*` (a single word token ending in a literal `*`) -> the stemmed-stream atom via a
   SHARED helper resolve_family_atom(stemmer, word) = stem_atom(stemmer, word). cover_search
   ALWAYS interprets `word*` (no flag). Symmetric fallback for unstemmable words (`ox*` ->
   exact `ox`).
3. Bare terms without `*` are exact. Operators, parens, `:tags`, and quoted phrases with
   no `*` are unmodified.
4. `word*` is honored INSIDE a quoted phrase: a phrase desugars to (>> (# n) (... ...));
   do the translation BEFORE the normal expand_phrases pass. A non-trailing, mid-token
   `*` is a clear error (CLI exit 2 / server 400), no crash.
5. `word*` needs a stemmed stream; if the burrow has none and the query uses `word*`,
   fail with a clear error (CLI exit 2 / server 400) — no silent fallback to exact.
6. Add the cover_search endpoint INLINE in cottontail-jsonl-server.cc (the same way the
   existing `/tools/*` endpoints are registered with svr.Post), and include its schema in
   describe_json so `GET /describe` lists it. There is NO per-agent filtering — the server
   simply offers cover_search alongside its other tools.

## The `summary` field — a cover-biased extractive summary

For each returned document, build `summary` from the query's covers within it (the same
covers ssr summed). Window size W is in TOKENS (corpus term positions), default 75
(about 3 sentences at ~25 words); A2 lets the request override it.

WHERE THE COVERS COME FROM — a cheap PHASE 2 over the top_k results only (do NOT re-rank the
corpus): ssr_ranking (src/ranking.cc:305-350) computes covers internally (score +=
1/(K+q-p)) but RETURNS ONLY THE CONTAINER SPAN (cp,cq) per result — the individual covers are
discarded, and RankingResult exposes no per-cover data for an ssr hit (its p()/q() equal the
container). So build the summary in a SECOND PHASE over ONLY the top_k RETURNED documents
(standard rank-then-snippet): for each returned container (cp,cq), seek the query hopper to
cp and advance tau while q <= cq, collecting THAT document's (p,q) covers (the same inner
recurrence as ranking.cc:327-345). This re-enumerates covers within ~top_k documents only —
it is NOT a second corpus-wide pass and is negligible next to ranking. Do NOT read covers off
RankingResult (they are not there), and do NOT call ssr_ranking again over :item. (Capturing
covers during phase 1 is intentionally avoided: ssr does not know which documents survive
into top_k until scoring finishes, so buffering covers for every matching document would be
unbounded memory; the localized re-walk trades trivial recomputation for bounded memory.)

Algorithm (per returned document, using that document's phase-2 covers):
1. Enumerate the query's covers within the document, in DOCUMENT ORDER.
2. For each cover (p,q): width T = max(W, cover_length). Center a T-token window on the
   cover. If it runs past the document body start or end, SHIFT it inward to keep T
   tokens (clamp to the whole body if the body is shorter than T). If W < cover_length,
   the cover itself is the window.
3. Take the UNION of these windows in document order (never reorder).
4. MERGE windows that overlap or touch into one longer extent (do NOT repeat material).
5. Render each merged extent (translate its tokens to text); join consecutive
   (non-contiguous) extents with the separator space-dot-space-dot-space-dot-space
   ( . . . ) to show a gap. A single extent has no separator.
`summary` is that joined string. (Optionally also return the merged extents' token
offsets for later grounding; the text is the required deliverable.)

## Non-goals

- Do NOT modify `search_gcl` (pure GCL) or the GCL core.
- Do NOT add total_matches/unjudged_matches/atom_counts/exclude_docids or the request-side
  `window` override — that is A2 (A2 reuses this summary, parameterized by `window`).
- Do NOT give cover_search a whole-query stem flag; per-atom `word*` is its mechanism.
- Do NOT build a tool registry or per-agent/profile filtering on the server (rejected
  design): the server is just a bag of tools; clients choose what their agent uses.
- Do NOT touch the Python isj agent. Do NOT write a warren-level stemmer into dna; only
  READ the burrow's stemmer.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 In cover_search on a --stem porter burrow, bear* matches a row whose body contains only 'bears' (family recall).
- [x] #2 In cover_search, the bare term bear (no asterisk) does NOT match a row containing only 'bears'; an index built without --stem is unaffected.
- [x] #3 Mixed cover (^ black bear*) matches with black exact and bear* as a family; a quoted phrase with no asterisk is left exact.
- [x] #4 Symmetric fallback: ox* matches a row containing 'ox' (Porter leaves 'ox' unchanged, so the asterisk is dropped and the exact word matches) with no error.
- [x] #5 A starred word inside a quoted phrase is honored: a phrase of black followed by bear* matches a row containing 'black bears' (desugar-with-stem before expand_phrases; adjacency preserved via shared addresses).
- [x] #6 A non-trailing, mid-token asterisk (e.g. at*ack, or a star mid-word in a phrase) produces a clear error (CLI exit 2 / server 400), with no crash.
- [x] #7 A cover_search query using word* against a burrow with no stemmed stream fails with a clear error (CLI exit 2 / server 400) and does NOT silently fall back to exact.
- [x] #8 Operators and :tags are untouched: (<< bear* :item) parses and runs with :item intact and only bear* translated.
- [x] #9 The word*-to-feature translation is a SINGLE shared helper (used by cover_search ranking and reusable by A2's atom_counts) so the feature searched cannot drift; an unstemmable word* resolves through it to the exact feature.
- [x] #10 search_gcl's behavior and response are unchanged (regression check).
- [x] #11 bazel test //test:tests //test:hazel_test //test:jsonl_test is green, with new cases in test/jsonl.cc, test/jsonl_cli.cc, and test/jsonl_server.cc; docs/stemming.md and the cli/server specs document cover_search and the word* marker as distinct from search_gcl and the whole-query --stem flag.
- [x] #12 cover_search's per-document response is {rank, score, docid, summary}: score is the ssr sum over the document's covers of 1/(K+q-p), rank is 1-based, and summary REPLACES the old best_passage.
- [x] #13 summary is a cover-biased extractive summary: for each of the query's covers (in document order) center a window of max(window, cover_length) tokens on the cover, shifting inward at a document boundary to preserve the width (clamped to the body); take the union of the windows; merge overlapping or touching windows into one extent with no repeated text.
- [x] #14 summary renders each merged extent and joins non-contiguous extents with a spaced-dots separator ( . . . ); extents are never reordered (always document start to end); a single extent has no separator.
- [x] #15 The summary window size is a parameter in tokens with default 75 (about 3 sentences at ~25 words); cover_search collects the query's covers within each returned :item to build the summary; A2 adds the request field to override the window.
- [x] #16 A new cover_search tool exists (a jsonl_core function + POST /tools/cover_search endpoint added alongside the existing server tools), included in describe_json; search_gcl is unchanged and remains a pure GCL interface with no word* handling.
- [x] #17 cover_search is included in describe_json so GET /describe lists it (the server advertises all its tools; there is no per-agent/profile filtering).
- [x] #18 The summary is built in a PHASE 2 over only the top_k returned documents: because ssr_ranking returns only the container span per result (not the covers), the builder recovers each returned document's covers by walking the query hopper within that container [cp,cq] (mirroring ranking.cc:327-345); it does NOT re-rank the corpus and does NOT read covers off RankingResult.
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Grounded in the current code (verified): hopper_from_gcl = from_string -> expand_phrases(tokenizer,'"') -> to_hopper; ssr_ranking takes a GCL STRING and re-parses it; stem_gcl is already a string-level rewriter; ssr_ranking returns only the container span (covers discarded). On branch claude/trec-rag-2026-design (do NOT branch). Adapt as needed.

DESIGN DECISIONS (made during the read; flagged to the user):
- D1 Rewrite word* at the STRING level (a new cover_rewrite, mirroring stem_gcl), producing an ordinary GCL string fed to BOTH ssr_ranking (phase 1) and hopper_from_gcl (phase 2). Avoids touching the GCL core and reuses existing parsing.
- D2 Phrase-internal word* must be desugared BEFORE the standard expand_phrases (which would tokenize porter:<stem> wrongly): in cover_rewrite, a star-containing quoted phrase is split on WHITESPACE (to preserve each word's trailing *), each word* translated, emitted as the explicit (>> (# n) (... a b ...)); n = whitespace-token count. Star-free phrases stay quoted for the normal pass. (Known simplification: whitespace split, not tokenizer->split; fine for the corpus; note in docs.)
- D3 The summary window W is an INTERNAL parameter (default 75) in A1; A1 does NOT parse a request-side window (that is A2's boundary).

1. resolve_family_atom(stemmer, word) -> stem_atom(stemmer, word): the SINGLE shared word*->feature helper (A2's atom_counts reuses it). bear -> porter:bear; ox -> ox (symmetric fallback).
2. cover_rewrite(query, stemmer, &error) in apps/jsonl_core.cc (anon ns): scan like stem_gcl. Operators/:tags verbatim; a token ending in * -> strip the star, error on any remaining * (mid-token) or empty word, else resolve_family_atom; bare token exact; inside quotes desugar star-containing phrases per D2, leave star-free phrases quoted. Returns the rewritten GCL string (false/error on a mid-token star).
3. Structs in jsonl_core.h: CoverSpec { string query; size_t top_k = 10; } and CoverHit { int rank; double score; string docid; string summary; }. (A2 extends CoverSpec with exclude_docids/window.)
4. jsonl_cover_search(warren, CoverSpec, vector<CoverHit>*, &error) in jsonl_core.cc:
   a. If the query uses word* and burrow_stemmer(warren)==nullptr -> error (no stemmed stream; CLI exit 2 / server 400).
   b. rewritten = cover_rewrite(...); validate via hopper_from_gcl (bad GCL / mid-token star -> error).
   c. PHASE 1: ssr_ranking(warren, rewritten, ":item", top_k) -> container spans + scores; docid via the :docno hopper (as jsonl_query does).
   d. PHASE 2 (per RETURNED container only): build the query hopper from rewritten; tau(cp); iterate while q<=cq collecting that doc's (p,q) covers (mirroring ranking.cc:327-345). Do NOT re-rank the corpus and do NOT read covers off RankingResult.
   e. cover_summary(warren, covers, body_start=dq+1, body_end=cq, W=75) -> summary.
5. cover_summary(warren, covers, body_start, body_end, W): per cover width T=max(W,cover_len), center on the cover, shift inward at body edges (clamp to body if shorter than T); union in document order; merge overlapping/touching extents; render each via txt()->translate; join non-contiguous extents with " . . . "; single extent no separator.
6. apps/jsonl_json.{h,cc}: cover_results_json(hits) -> { "results":[{rank,score,docid,summary}] }; add a cover_search entry to describe_json() (query + top_k + a word* description). (A2 adds exclude_docids/window + the enrichment fields.)
7. apps/cottontail-jsonl-server.cc: cover_spec_from(b) + svr.Post("/tools/cover_search", ...) mirroring the search handler (parse -> jsonl_cover_search -> cover_results_json; errors -> fail(res,400,...)).
8. apps/cottontail-jsonl-query.cc: add a --cover mode (a new mutually-exclusive mode) for CLI/test use; errors exit 2.
9. Tests (build an inline --stem porter burrow via the existing build(...,stemmer,...) helper; assert docid SET membership, not order):
   - test/jsonl.cc: AC#1-5,#8,#9,#12-15 (family recall, bare-exact, mixed cover, ox* fallback, phrase-internal star, :tags untouched, shared-helper invariant, response shape, summary windowing/merge/dots/edge-clamp/cover-longer-than-window).
   - test/jsonl_cli.cc: --cover happy path; mid-token star -> exit 2 (#6); word* on a non-stemmed burrow -> exit 2 (#7).
   - test/jsonl_server.cc: POST /tools/cover_search round-trip; GET /describe lists cover_search (#16/#17); search_gcl unchanged (#10).
10. Docs: docs/stemming.md (word* marker, honored in phrases, distinct from whole-query --stem); cli-spec + server-spec describe cover_search.

Build (per CLAUDE.md): bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example
Test: bazel test //test:tests //test:hazel_test //test:jsonl_test (plus server test).
Determinism: stemmed and exact share addresses -- assert docid SET membership, not order.
<!-- SECTION:PLAN:END -->
