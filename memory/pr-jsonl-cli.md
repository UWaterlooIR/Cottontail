---
name: pr-jsonl-cli
description: PR status — #1/#3/#4 merged; PR #5 OPEN on claude/trec-rag-2026-design is where ALL open backlog work lands; gh-https push now wired
metadata:
  type: reference
---

The original JSONL CLI / SimpleWarren grep-tool work (see [[climbmix-poc-plan]]:
Hazel-not-ready docs, the SimpleWarren grep-tool POC, the revised JSONL CLI spec,
and the `cottontail-jsonl-index`/`-query` CLIs + `//test:jsonl_test`) shipped via
**PR #1** (https://github.com/UWaterlooIR/Cottontail/pull/1), now **MERGED**.

**PR #3** ("Add stemming CLI support and LLM agent specification",
https://github.com/UWaterlooIR/Cottontail/pull/3) is now **MERGED** into `main`.
It carried the `--stem` CLI + tokenizer choice ([[stemming-tokenizer]]), the
agent-tool CLI actions (`--get`/`--count`/`--describe`, result signals),
`docs/cottontail-search-agent-spec.md`, the example ReAct agent under
`examples/agent/` (uv project), and `scripts/`.

**PR #4** ("Add HTTP/JSON search server (cottontail-jsonl-server)",
https://github.com/UWaterlooIR/Cottontail/pull/4) is **MERGED** into `main` (built
on branch `claude/agent-server`). It carried `cottontail-jsonl-server` (cpp-httplib
over `jsonl_core`: `GET /healthz`, `GET /describe`, `POST /tools/<name>`), the
shared `apps/jsonl_json.{h,cc}`, bearer-token auth (optional on loopback, required
on a non-loopback bind), the **clone-per-thread pool** (`--threads`,
`WarrenProvider` — a fixed pool of pre-cloned Warrens, TSan-clean), the example
agent HTTP transport, `//test:jsonl_server_test`, and
`docs/cottontail-search-server-spec.md` + `docs/cottontail-server-threadpool-spec.md`.

**PR #5** ("Implement Searcher agent and cover_search engine tool for ISJ",
https://github.com/UWaterlooIR/Cottontail/pull/5) is **OPEN** on branch
`claude/trec-rag-2026-design`. **Decided (2026-06-25, the user): ALL open backlog
work lands on this one PR/branch — TASK-5.x (Searcher) and TASK-6.x (cp-native
indexing). Do NOT create new branches or new PRs; stay on `claude/trec-rag-2026-design`
and push commits onto PR #5.** See [[climbmix-poc-plan]] and the cp-native indexing
design (docs/indexing.md, doc-6).

Access note: push access **now works** for the agent. As of 2026-06-25 the repo is
wired **repo-local** (in `.git/config` only — nothing global, nothing outside the
repo) to push over **HTTPS using the already-authenticated `gh` token**
(account `profsmucker`, `viewerPermission: ADMIN`):
`origin` = `https://github.com/UWaterlooIR/Cottontail.git`, and
`credential.https://github.com.helper = !gh auth git-credential`. Verified: read
(`git ls-remote`), write (`git push --dry-run`), and `gh pr` ops all succeed.
Reversible with `git remote set-url origin git@github.com:UWaterlooIR/Cottontail.git`
(+ unset the local helper) to restore SSH. Still: commit/push only on explicit user
approval per the working agreement.
