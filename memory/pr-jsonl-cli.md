---
name: pr-jsonl-cli
description: PR status — PRs #1, #3, #4 all merged into main (JSONL CLI, stemming, agent tooling, HTTP search server + thread pool); no active feature branch
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

So **PRs #1, #3, #4 are all merged** — the full JSONL CLI + stemming + tokenizer
choice + agent-tool CLI actions + example ReAct agent + HTTP search server + thread
pool are in `main`. **No feature branch is active; ask the user which branch/PR new
work belongs to before assuming.**

Access note: this sandbox shell has **no push access** to
`git@github.com:UWaterlooIR/Cottontail` (fetch/push fail). Local commits reach a
remote/PR only when pushed via the Claude Code UI or by the user — so after
committing, tell the user if local is ahead of its upstream.
