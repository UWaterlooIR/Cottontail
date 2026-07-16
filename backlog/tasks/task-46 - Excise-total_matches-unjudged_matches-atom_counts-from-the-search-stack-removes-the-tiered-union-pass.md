---
id: TASK-46
title: >-
  Excise total_matches / unjudged_matches / atom_counts from the search stack
  (removes the tiered union pass)
status: In Progress
assignee: []
created_date: '2026-07-15 22:12'
updated_date: '2026-07-15 23:15'
labels: []
dependencies: []
ordinal: 67000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Remove the three diagnostic fields total_matches, unjudged_matches, and atom_counts from the entire search stack -- C++ server responses, Python protocol/engines/controller/coach, the search-agent prompts, and tests -- so every engine presents a UNIFORM feedback surface (results returned + judged summaries/grades/coverage), matching what the Lucindri engine already does (it omits all three). None of the three drive control flow (they are purely diagnostic; verified by grep -- no if/while/break/budget/stopping reads them). The over-constrained auto-coaching is driven by RESULTS-RETURNED == 0 (controller.py stats['count']==len(descended)), NOT total_matches, and is unaffected. PRIMARY MOTIVATION beyond uniformity: computing the tiered path's total/unjudged requires a UNION COUNTING PASS (apps/jsonl_core.cc ~1137-1158) that ORs every tier into one hopper tree and thus pins the FULL program vocabulary's decompressed posting lists simultaneously (unevictable, shared_ptr-held) on every paging refill -- the dominant, avoidable driver of the mt memory blow-ups (see the rag2026-2 mt OOMs). Removing it drops the pinned peak from 'union of all tiers' terms' to 'the widest single tier', restores the cache cap's effectiveness on the tiered path, and speeds mt up (no per-refill full-corpus counting walk). ACCEPTED TRADEOFF: the searcher loses the 'term with atom count 0 is dead -> respell' hint; it must infer dead/misspelled terms from weak results (Lucindri already runs this way, hence uniform). CAVEAT -- 'atom' is overloaded: KEEP the query-REWRITING machinery (stem_atom, resolve_family_atom, phrase_atoms, cover_rewrite, and 'a cover IS the atom of retrieval' in searcher.md); remove only atom_COUNTS and cover_leaves (used solely to enumerate leaves for atom_counts). This does NOT add the separate per-query materialization admission guard (a follow-up task) and does NOT touch large_limit_/the 4GB experiment branch (abandoned separately; build this on a fresh branch off main = ejection on, large_limit_ 3e9).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 C++: the query-REWRITING atom machinery (stem_atom, resolve_family_atom, phrase_atoms, cover_rewrite) is UNCHANGED and all ranked queries still evaluate correctly
- [x] #2 Python: SearchResponse drops the three fields and AtomCount is removed; every engine adapter (http, multishard incl. _merge_atom_counts, fake, lucindri) is updated; controller stops tracking/emitting them and _compose_feedback reduces to query + coverage(count/relevant) + coach report; run_output trace line updated; the tiered tool descriptions in protocol/queryable.py are scrubbed
- [x] #3 Prompts: searcher.md, mt_tiered_searcher.md, and tiered_searcher.md have all total_matches/atom-count guidance removed while the 'cover IS the atom of retrieval' language is kept; search_coach.md is unchanged; stale 'atom-blind' comments in search_coach.py are tidied
- [x] #4 Over-constrained auto-coaching still fires on results-returned==0 (unchanged); a functional check confirms a 0-result query still returns the broaden-it feedback
- [x] #5 Build green (bazel build //... minus the known Boost-excluded apps:walk targets) and tests green: C++ (test/jsonl.cc, test/jsonl_server.cc, test/jsonl_cli.cc) and the Python isj suite (test_multishard, test_controller, test_search_coach, test_lucindri_engine, test_http_engine, test_engine, test_run_output, test_queryable, test_tiered_searcher, test_mt_tiered_searcher) updated for the removed fields and passing
- [x] #6 C++: CoverResponse no longer declares total_matches/unjudged_matches/atom_counts; the AtomCount struct is removed and jsonl_json.cc no longer serializes any of the three; the tiered union counting pass is deleted; cover_ranking/parallel_cover_ranking no longer compute/return total/unjudged; the two atom_counts build loops are removed -- but cover_leaves and idx->count are RETAINED (unused until TASK-47 consumes them for the posting-budget guard)
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
## Implementation Plan

### Branch
Fresh feature branch off **main** (`claude/excise-diagnostic-counts`). NOT the `claude/cache-limit-4gb` branch (that 4 GB experiment is abandoned separately). Baseline: ejection on, `large_limit_ = 3e9` -- untouched by this task.

### Disambiguation (do not break query evaluation)
"atom" is overloaded. REMOVE only the diagnostic `atom_counts`. KEEP the query-REWRITING atom machinery: `stem_atom` (jsonl_core.cc:135), `resolve_family_atom` (208), `phrase_atoms` (245), `cover_rewrite` (276), and the "a cover IS the atom of retrieval" wording in searcher.md:62. `cover_leaves` (548) is used ONLY by the two atom_counts loops (983, 1114) -> remove it.

### Order of work (compile-checkable at each layer)

**1. C++ server (apps/) -- remove the counting + response fields.**
- `apps/jsonl_core.h`: delete the `AtomCount` struct (122-124); delete `CoverResponse::{total_matches, unjudged_matches, atom_counts}` (130-132); drop the `long *total_matches, long *unjudged_matches` params from the `cover_ranking`/`parallel_cover_ranking` decls (154-166, 189-209); refresh the A2 comments (31, 128, 189-195, 209).
- `apps/jsonl_core.cc`:
  - `cover_ranking` (466-530): remove the `total_matches`/`unjudged_matches` out-params and the increments at 473-474, 493-495.
  - `parallel_cover_ranking` (624-706): remove the totals/unjudgeds vectors and aggregation (632-633, 659-660, 674, 691, 705-706); simplify the single-range fast path.
  - `jsonl_cover_search` (955-1049): drop `out->total_matches/unjudged_matches` init (959-960) and the args passed to parallel_cover_ranking (1003-1004); delete the atom_counts block (958, 976 comment, 981-995).
  - `jsonl_tiered_query_search` (1058-...): drop the init (1063-1064); delete the atom_counts loop (1062, 1109-1130); **delete the entire UNION COUNTING PASS block (1137-1158)** and its `nonempty`/`orq`/`discard`/`tm`/`um` locals; in the per-tier cascade drop the now-unused `long tm, um` discards (1179).
  - Delete `cover_leaves` (533-590) and its forward decl.
  - `compile_multitext` path is unaffected (it only builds tier strings).
- `apps/jsonl_json.cc`: delete the serialization of `total_matches`/`unjudged_matches` (74-75) and the `atom_counts` array build (76-83). Refresh the header comment in jsonl_json.h:31.

**2. Python protocol (isj/isj_agent/protocol/).**
- `search.py`: delete `class AtomCount` (22-23); delete `SearchResponse.{total_matches, unjudged_matches, atom_counts}` (52-54).
- `queryable.py`: scrub the tiered tool DESCRIPTIONS shown to the model that promise "union atom_counts" / "count of distinct documents matched" (123, 145, 220) -> describe only ranked results + per-tier summaries.

**3. Python engines (isj/isj_agent/engine/).**
- `http.py`: drop the `AtomCount` import (26) and the parsing of atom_counts/total/unjudged (130-134) -> build `SearchResponse(results=...)` only.
- `multishard.py`: drop the `AtomCount` import (27), `_merge_atom_counts` (122-135) and `_sum_opt` (if now unused), the merged fields (77-79); refresh the module docstring (8-10).
- `fake.py`: remove the three fields from the fabricated response (86) and the exclude-decrement bookkeeping that adjusts unjudged_matches (100, 110-111).
- `lucindri.py`: already omits them; update the comment at 17 (they are no longer "omitted" -- they no longer exist).
- `base.py`: refresh the docstring mentioning atom_counts / exact match count (60).

**4. Controller + coach (isj/isj_agent/).**
- `controller.py`: remove `total_matches` local + capture (315, 332-333), the diag entries (340-345), and both keys from the `_descend` return (421). Simplify `_compose_feedback` (423-435): keep the `Your query:` echo + the `Coverage: judged N, M relevant` line; DROP the `total_matches` clause (429-430) and the entire `Atom matches:` block (432-434); update its docstring (424-426). Update the two call sites (267, 288) to drop the `atom_counts` arg.
- `agents/search_coach.py`: functionally unchanged (already atom-blind); tidy the now-stale comments that reference the "atom header"/"atom-blind" rationale (13, 16, 37, 54) so they don't describe a header that no longer exists.
- `run_output.py`: drop `total=` (and any atom/unjudged) from the `search` trace line (185).

**5. Prompts (isj/isj_agent/agents/).**
- `searcher.md`: remove the atom-count guidance (152, 217). KEEP line 62 ("a cover IS the atom of retrieval").
- `mt_tiered_searcher.md`: remove the atom_counts guidance (23, 26).
- `tiered_searcher.md`: remove the total_matches + atom_counts feedback-doc lines (103, 106, 117, 126).
- `lucindri_searcher.md`: no change (no refs). `search_coach.md`: no change (no refs).

**6. Tests.**
- C++: `test/jsonl.cc`, `test/jsonl_server.cc`, `test/jsonl_cli.cc` -- drop asserts on total_matches/unjudged_matches/atom_counts; keep result/ranking asserts.
- Python: `test_multishard.py`, `test_controller.py`, `test_search_coach.py`, `test_lucindri_engine.py`, `test_http_engine.py`, `test_engine.py`, `test_run_output.py`, `test_queryable.py`, `test_tiered_searcher.py`, `test_mt_tiered_searcher.py` -- remove the fields from fixtures/asserts; add/keep an assert that a 0-result fetch still yields the OVER_CONSTRAINED broaden-it feedback (AC #5).

### Verify
- `bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example`
- `bazel test -c dbg //test:all` (esp. jsonl, jsonl_server, jsonl_cli, hazel).
- `uv run --directory isj pytest` (full isj suite green).
- Functional (AC #5): drive a deliberately over-constrained query through the controller against the fake engine (0 results) and confirm the broaden-it feedback is produced -- proving the over-constrained path never depended on total_matches.

### Out of scope (separate follow-ups)
- The per-query / per-feature materialization ADMISSION GUARD (the hard memory backstop). Its own task.
- Reverting/deleting the `claude/cache-limit-4gb` branch (large_limit_ stays 3e9 on main).

### Risks / notes
- Wire-protocol change: the server JSON responses lose three fields. Both producers (C++) and the sole consumers (isj engines) are in this repo and updated together, so no external break. The HTTP schema is the fork's own.
- Removing `atom_counts` removes the searcher's dead-term signal (accepted, for uniformity). Watch a post-merge dev run to confirm searcher quality doesn't regress materially.
- Keep changes mechanical and layer-by-layer so each `bazel build` / import stays green as we go.

### Commit / PR
Branch -> PR against the fork: `gh pr create --repo UWaterlooIR/Cottontail --base main --head claude/excise-diagnostic-counts`. Never commit to main.

### CORRECTION -- retain cover_leaves + idx->count (for TASK-47)
Supersedes the "Delete cover_leaves" step above. TASK-47 (the posting-memory budget guard) enumerates a query's leaves via `cover_leaves` and reads each leaf's size via `idx->count` / the PstRecord header. So in THIS task: remove the atom_counts RESPONSE field + serialization + feedback + the two atom_counts CALL SITES (jsonl_core.cc:981-995 and 1109-1128) -- but KEEP the `cover_leaves` function (533-590) and the `idx->count` machinery. They go unused between TASK-46 and TASK-47, then TASK-47 wires them into admission control.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented on branch claude/excise-diagnostic-counts (commit 6a1d9d1). C++ (jsonl_core.{h,cc}, jsonl_json.{cc,h}): removed the 3 fields + AtomCount + the tiered union counting pass + total/unjudged counters from cover_ranking/parallel_cover_ranking (they lost exclude+count params; callers keep their own cp exclude post-filter); cover_leaves + idx->count RETAINED ([[maybe_unused]]) for TASK-47. Python (via subagent): SearchResponse=results-only, all engines/controller/coach/run_output/queryable + searcher/mt/tiered prompts updated; searcher infers dead terms from weak results. Tests green: C++ //test:all 5/5; Python isj 242 passed/1 skipped; 6 removed-field-only tests deleted. Over-constrained coaching still fires on results-returned==0 (verified by retained controller tests + jsonl_server_test asserting the removed keys are absent from the wire). Status: In Progress pending PR/merge.
<!-- SECTION:NOTES:END -->
