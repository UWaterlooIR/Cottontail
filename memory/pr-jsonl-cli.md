---
name: pr-jsonl-cli
description: PR status for the JSONL CLI / search-agent work — PR #1 merged, PR #3 OPEN on branch claude/tool-agent
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

Active branch is **`claude/agent-server`** (→ `main`), with **open PR #4** ("Add
HTTP/JSON search server (cottontail-jsonl-server)",
https://github.com/UWaterlooIR/Cottontail/pull/4). **Reference PR #4 for this
branch's work — don't open new PRs; pushing more commits updates it.** It carries
`cottontail-jsonl-server` (cpp-httplib over `jsonl_core`), the shared
`apps/jsonl_json.{h,cc}`, `docs/cottontail-search-server-spec.md`, the agent HTTP
transport, and `//test:jsonl_server_test`.

Access note: this sandbox shell has **no push access** to
`git@github.com:UWaterlooIR/Cottontail` (fetch/push fail). Local commits reach a
remote/PR only when pushed via the Claude Code UI or by the user — so after
committing, tell the user if local is ahead of its upstream.
