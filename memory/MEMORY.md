# Project Memory Index

- [Repo boundary (hard rule)](respect-repo-boundary.md) — never access outside the repo without explicit permission
- [Plan-approval agreement](working-agreement-plan-approval.md) — hold an approved plan before changing anything
- [Memory location](memory-location.md) — project memory lives in-repo at ./memory/, not ~/.claude
- [User: Mark Smucker](user-mark-smucker.md) — IR researcher, acknowledged reviewer of the Annotative Indexing paper
- [Cottontail overview](project-cottontail-overview.md) — what the project is, authoritative docs, and where active work sits
- [Hazel not ready](hazel-not-ready.md) — Hazel is a WIP, not ready for use; don't build features on it
- [ClimbMix corpus location](climbmix-corpus-location.md) — gzip'd JSONL shards at /share/corpora/climbmix-400b-corpus-jsonl/ (outside repo)
- [SimpleWarren scaling model](simplewarren-scaling-model.md) — external-memory build, on-demand posting reads, WAND ranking; tuning levers + stats caveat
- [ClimbMix POC plan](climbmix-poc-plan.md) — pivot the POC to SimpleWarren, scaling target ~6500 shards, 512GB machine
- [PR: JSONL CLI](pr-jsonl-cli.md) — PR #1 merged; now on branch claude/tool-agent (shell has no push access)
