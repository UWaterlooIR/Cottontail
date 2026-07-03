---
name: upstream-sync-claclark
description: How this fork syncs with claclark/Cottontail — remote, standing resolution policy, and the 2026-07 sync facts
metadata:
  type: project
---

The fork syncs with **`upstream` = https://github.com/claclark/Cottontail.git**
(remote added 2026-07-03). First sync: TASK-24, merged upstream `c239bc7`
(2026-07-02) on branch `claude/sync-with-charlie`; merge-base was `219fb069`.
Charlie pushes frequently — expect divergence to grow between syncs.

**Standing resolution policy (Mark-approved, reuse on future syncs):**
- `AGENTS.md`: always ours (a pointer to CLAUDE.md); discard upstream's edits.
- `ai/`: take upstream wholesale (it's Clarke's live notes, non-authoritative
  for agents — CLAUDE.md carries the fence). No archiving dance anymore.
- `docs/design/reference-specs/hazel-format.md` is a pointer stub to
  `ai/hazel.md`; don't let content accumulate there.
- Keep fork fixes when upstream lacks them — e.g. the TASK-7 null-child guards
  in `gcl/parse.cc` (upstream builds GCL operators with possibly-null children;
  re-check on each sync whether upstream adopted the guards).
- GCL sources live in top-level `gcl/` since June 2026; `src/BUILD` globs and
  re-exports them, so fork targets depending on `//src:cottontail` don't care.

**2026-07 sync experience (calibration for next time):** textual conflicts were
only 7 files; git rename detection carried fork edits into moved files well;
compile ripple was ZERO (upstream keeps signatures backward-compatible, e.g.
ssr_ranking unchanged when parallel_ssr was added). The expensive part was
policy files (ai/, AGENTS.md, hazel-format), not code.

**SSR notes:** `parallel_ssr()` (src/ranking.cc) parallelizes SSR within one
shard by splitting the token span (≥1M tokens/range) over warren->clone()
workers — SimpleWarren supports clone. Upstream's `//apps:ssr-server` works over
our burrows but (a) needs an indexed docno GCL for result identity, which
cp-native burrows don't have (doc-8), and (b) ranks to DEPTH=1000 and does a
full docno-hopper load per result — 12-50s/query on our big burrows vs ~2s for
our own `cottontail-jsonl-query --ranker ssr --top-k 3`. Adoption of
parallel_ssr into our server = TASK-25. The old
`Scrapheap/climbmix-1000-utf8-porter.burrow` (NOT small — ~23.5B token address
space) carries real `:docno` annotations and is the fixture for exercising
docno-based flows.
