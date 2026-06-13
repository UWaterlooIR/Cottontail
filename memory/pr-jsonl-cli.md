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

Active branch is now **`claude/agent-server`** (→ `main`, already pushed) for the
search **server** work (spec §8: lift the CLI's tool API into a persistent
REST/MCP layer over `jsonl_core`, opening the burrow once). It will get its own
PR — confirm with the user before opening one.

Access note: this sandbox shell has **no push access** to
`git@github.com:UWaterlooIR/Cottontail` (fetch/push fail). Local commits reach a
remote/PR only when pushed via the Claude Code UI or by the user — so after
committing, tell the user if local is ahead of its upstream.
