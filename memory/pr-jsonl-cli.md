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

Active branch is **`claude/tool-agent`** (→ `main`), with **open PR #3**
("Add stemming CLI support and LLM agent specification",
https://github.com/UWaterlooIR/Cottontail/pull/3). **Reference PR #3 for this
branch's ongoing work — do not open new PRs; pushing more commits to
`claude/tool-agent` updates it.** PR #3 carries: the `--stem` CLI + tokenizer
choice ([[stemming-tokenizer]]), the agent-tool CLI actions (`--get`/`--count`/
`--describe`, result signals), `docs/cottontail-search-agent-spec.md`, the example
ReAct agent under `examples/agent/` (uv project), and `scripts/`.

Access note: this sandbox shell has **no push access** to
`git@github.com:UWaterlooIR/Cottontail` (fetch/push fail). Local commits reach a
remote/PR only when pushed via the Claude Code UI or by the user — so after
committing, tell the user if local is ahead of its upstream.
