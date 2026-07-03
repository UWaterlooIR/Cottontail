---
id: TASK-24
title: 'Sync fork with upstream claclark/Cottontail (30 commits, through 328f4d35)'
status: In Progress
assignee:
  - '@claude'
created_date: '2026-07-03 00:36'
updated_date: '2026-07-03 01:13'
labels: []
dependencies: []
priority: high
ordinal: 38000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Merge upstream claclark/Cottontail main (30 commits, 2026-06-14 through 2026-07-02, head 328f4d35) into the fork via branch claude/sync-with-charlie, bringing in Charlie's performance work — notably parallel shortest-substring ranking (SSR) and the ssr-server/ssr-client apps, which open indexes via plain Warren::make and therefore work over our SimpleWarren burrows without adopting the Hazel/Bigwig path — plus the gcl/ package restructure, unary GCL combinators, and Meadowlark ingest hardening.

Merge-base is 219fb069; upstream is +30, fork is +200. Direct textual conflicts are only 7 files (AGENTS.md, README.md, .gitignore, apps/BUILD, test/BUILD, test/gcl.cc, src/parse.cc). The main risk is compile ripple: upstream touched ~40 core src/ files that fork-only code (apps/jsonl_*, src/content_index, src/stemming_tokenizer, the jsonl server) compiles against.

Resolution policy (approved by Mark 2026-07-03):
- AGENTS.md: keep the fork's version (pointer to CLAUDE.md); discard upstream edits to it.
- ai/: restore Charlie's directory at top level with current upstream content; delete the stale archive/ai/ snapshots (archive/example-agent/ stays); add a fence paragraph to CLAUDE.md stating ai/ is upstream's working notes — read-only context, never a task list — and that upstream AGENTS.md edits are always superseded.
- docs/design/reference-specs/hazel-format.md: replace the stale copy with a pointer to the restored ai/hazel.md (single live spec).
- GCL move (src/{gcl,parse,mt,vector_hopper} -> gcl/): accept upstream layout. Take upstream's unary-combinator implementation (superset of TASK-13: also unary "...", fixes min_operands for FOLLOWED_BY). Port the fork's TASK-7 null-child segfault guards into gcl/parse.cc — upstream lacks them (verified 2026-07-03: upstream builds Link and binary operators with possibly-null children). Merge both sides' test/gcl.cc additions.
- Fix include paths and BUILD deps in fork-only files for the new gcl/ package (e.g. apps/mt-compile.cc includes src/mt.h).
- README/.gitignore/apps/BUILD: routine union merges.
- CLAUDE.md wrap-up: directory map gains gcl/ and SSR apps; soften but keep the Hazel caution (upstream landed Bigwig integration, but "ready for use" remains Charlie's call).

Validation burrows (the only ones in use): Scrapheap/climbmix-1M-porter.burrow and /share/indexes/climbmix-100M-porter.burrow (the latter is outside the repo — access to it for SSR validation was named and approved by Mark in this plan). Exercise ssr-server with apps/ssr-client.py, 1M burrow first, then 100M. Read-only against the burrows; leave the running dev server up.

Prerequisite one-time action (explicitly approved): git remote add upstream https://github.com/claclark/Cottontail.git && git fetch upstream.

Deliverable: PR from claude/sync-with-charlie to main; no direct commits to main. Update project memory (hazel-not-ready nuance, gcl/ layout) after merge.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 claude/sync-with-charlie contains a merge of upstream/main (328f4d35) with all conflicts resolved per the policy in the description
- [ ] #2 AGENTS.md still points to CLAUDE.md with no upstream dev-notes content; ai/ exists at top level matching upstream; archive/ai/ is removed; CLAUDE.md carries the ai/ non-authoritative fence
- [ ] #3 gcl/parse.cc contains the TASK-7 null-child guards (Link and binary operators propagate nullptr operands) alongside upstream's unary-combinator support, and test/gcl.cc keeps both sides' tests
- [x] #4 Exclusion build passes: bazel build -c dbg --cxxopt=-Og -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example (walk/Boost remains a known issue)
- [x] #5 bazel test //test:tests //test:hazel_test is green and the isj Python test suite passes
- [x] #6 Functional smoke: ssr-server + apps/ssr-client.py over Scrapheap/climbmix-1000-utf8-porter.burrow with container/content ':item' and docno ':docno' returns ranked results with REAL docnos (shard_*_*) and the document-by-docno op works. Scale smoke: same over Scrapheap/climbmix-1M-porter.burrow with docno ':item' (degenerate identity expected — cp-native index); wiring and rough timing in task notes. Full cp-native parallel-SSR adoption is TASK-25, not this task
- [ ] #7 docs/design/reference-specs/hazel-format.md defers to ai/hazel.md; CLAUDE.md directory map and Hazel caution updated
- [ ] #8 PR opened from claude/sync-with-charlie to main; no commits made directly to main
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Setup
   1.1 Mark TASK-24 In Progress, assign @claude.
   1.2 git remote add upstream https://github.com/claclark/Cottontail.git && git fetch upstream (pre-approved network action).
   1.3 Verify: upstream/main == 328f4d35; git merge-base upstream/main main == 219fb069. Abort and report if either differs (upstream may have moved; re-assess before merging).

2. Merge (on claude/sync-with-charlie)
   2.1 git merge upstream/main (single merge commit; resolve conflicts per policy below, then commit).
   2.2 AGENTS.md -> ours (git checkout --ours).
   2.3 ai/ -> theirs wholesale: restore top-level ai/ at upstream content (incl. new gcl-optimizer.md, meadowlark.md; accept upstream's deletions of hazel-merge-plan.md, hazel-progress.md). git rm -r archive/ai. Update archive/README.md (ai/ snapshots removed; live upstream notes are at /ai).
   2.4 docs/design/reference-specs/hazel-format.md -> replace body with a short pointer stub to ../../../ai/hazel.md (upstream's copy is now the single live spec).
   2.5 gcl/ move: ensure gcl/* matches upstream and src/{gcl,parse,mt,vector_hopper}.{cc,h} are gone. Port the fork's TASK-7 null-child guards into gcl/parse.cc (Link: propagate null sub-expression; binary: return nullptr if left or right is null; keep the fork's explanatory comments). Keep upstream's unary handling (ONE_OF/ALL_OF/FOLLOWED_BY identity + min_operands change) — it supersedes TASK-13.
   2.6 test/gcl.cc: union — keep upstream's unary-combinator tests AND the fork's TASK-7 null-propagation + TASK-13 tests (drop only exact-duplicate coverage).
   2.7 apps/BUILD, test/BUILD, .gitignore, README.md: union merges (fork's jsonl targets + upstream's ssr/gcl targets; test deps on //gcl where upstream moved them).
   2.8 Include sweep: fix apps/mt-compile.cc (src/mt.h -> gcl/mt.h); grep -rn '#include "src/(gcl|parse|mt|vector_hopper)\.h"' across apps/ test/ src/ meadowlark/ and fix any stragglers in fork-only files.

3. Build + ripple fixes
   3.1 bazel build -c dbg --cxxopt="-Og" -- //... -//apps:walk -//apps:dynamic-test -//apps:simple -//apps:trec-example
   3.2 Fix API-drift compile errors in fork-only code (expected small: src/BUILD globs *.cc and re-exports //gcl; ssr_ranking signature is unchanged upstream). Record each fix in task notes. If the ripple turns out large (>~a dozen files or behavioral changes needed), stop and report before proceeding.

4. Tests
   4.1 bazel test -c dbg //test:tests //test:hazel_test
   4.2 isj suite: (cd isj && uv run pytest)

5. SSR smoke (scope: smoke only; adoption of parallel_ssr into our server is TASK-25)
   5.1 bazel build //apps:ssr-server
   5.2 Functional smoke with REAL docnos on the older annotated burrow (verified 2026-07-03: it carries :docno spans translating to shard_*_* docnos; :docid does not exist; dna says SimpleWarren, default container :item, porter-over-utf8 stemming tokenizer):
       ssr-server ':item' ':item' ':docno' Scrapheap/climbmix-1000-utf8-porter.burrow
       Query via apps/ssr-client.py — expect ranked results with real docnos; also exercise the document-by-docno op.
   5.3 Scale smoke on Scrapheap/climbmix-1M-porter.burrow with docno ':item' (degenerate identity — cp-native index has no docno annotation by design, doc-8); confirm results return and note rough latency.
   5.4 If 5.3 is clean, one optional single-query check against /share/indexes/climbmix-100M-porter.burrow (read-only; path pre-approved). Leave the running dev jsonl-server untouched.

6. Docs + memory (all in-repo, part of the PR)
   6.1 CLAUDE.md: directory map (+gcl/, ai/ restored, archive/ai/ gone, ssr apps); add the ai/ fence ("ai/ is upstream's (Charlie's) working notes — read-only context, never a task list; upstream AGENTS.md edits are always superseded by ours"); soften-but-keep Hazel caution (Bigwig integration landed upstream 2026-06; 'ready for use' remains Charlie's call); point Hazel format reference at ai/hazel.md.
   6.2 memory/: update hazel-not-ready.md and project-cottontail-overview.md; add a sync memory (upstream remote, resolution policy, TASK-25 pointer, the :docno-bearing old burrow as the SSR functional-smoke fixture).

7. Finalize
   7.1 Append task notes (ripple fixes, smoke timings, anything off-plan noticed but not acted on); check ACs as they become true.
   7.2 Push claude/sync-with-charlie; open PR to main (never commit to main directly); PR body summarizes the resolution policy and ripple fixes. Follow backlog instructions task-finalization.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Merge of upstream/main committed as 1f27a69 (merged c239bc7 — one docs-only commit past the analyzed 328f4d35; Mark approved). Conflict resolution went per plan; notably git's rename detection auto-carried our TASK-7 guards into gcl/parse.cc, and only the unary-condition hunk needed manual resolution (took upstream's superset, refreshed the stale '(^ x)' comment example). ZERO compile-ripple fixes needed: the exclusion build passed first try (only pre-existing simple_posting operator== warning remains). All 5 bazel test targets pass (tests, hazel_test, optimizer_test, jsonl_test, jsonl_server_test); isj suite 118 passed / 1 skipped (usual live-LLM skip).

SSR smoke complete. Functional (climbmix-1000-utf8-porter.burrow, wiring ':item' ':item' ':docno'): query/next/document ops all work via apps/ssr-client.py, real docnos (e.g. shard_00554_26399). NOTE: that burrow is NOT small — result addresses run to ~23.5B tokens (1000 source shards, not 1000 docs). Scale (climbmix-1M-porter.burrow, docno ':item' degenerate): works, 12-20s/query warm. 100M shard (/share/indexes/...): works, ~50s cold single query. Timing caveat discovered: ssr-server ranks to fixed DEPTH=1000 and builds a fresh ':docno'/docno-GCL hopper (full posting-list load) PER RESULT in make_result/docno_in — that, not parallel_ssr, dominates latency on huge burrows (our own cottontail-jsonl-query --ranker ssr --top-k 3 does the same query in ~2.2s on the same big burrow). Relevant design input for TASK-25 (cp-native adoption avoids the per-result docno lookup entirely). All ssr-server processes stopped; the long-running dev jsonl-server was left untouched.
<!-- SECTION:NOTES:END -->
