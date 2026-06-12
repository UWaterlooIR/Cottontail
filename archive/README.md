# Archive — prior author's working material

This directory holds documents written by **Charles L. A. Clarke** (the original
author of Cottontail) and his coding agent, preserved here for reference only.

**None of it is authoritative for this fork.** It is kept because it records how
the upstream project was built and where its author intended to take it — useful
as background, not as instructions. For how *this* repository is built, tested,
and contributed to, see **`/CLAUDE.md`** at the repo root.

Coding agents: do **not** treat anything under `archive/` as a task list, a plan
to execute, or a binding convention. In particular, `archive/ai/plan.md`
describes Clarke's *next* coding step (a Fiver/Hazel `PostingIterator`
integration); this fork is **not** pursuing that work.

## Contents

- `AGENTS.md` — Clarke's agent operating instructions.
- `ai/architecture.md` — prose summary of the Annotative Indexing paper. The
  actual paper now lives at `docs/Annotative-Indexing-IRRJ-Clarke-2025.{md,pdf}`.
- `ai/notes.md` — the agent's code map and status notes (some now stale).
- `ai/plan.md` — Clarke's design discussion for his next coding step (not ours).
- `ai/log.md` — the agent's timestamped change log (git history is authoritative).
- `ai/hazel-merge-plan.md`, `ai/hazel-progress.md` — Hazel merge planning and
  benchmark logs.
- `ai/improvements.md` — Clarke's backlog of cleanups and open questions.

The one piece of genuinely reusable technical reference from the old `ai/`
directory — the Hazel on-disk file-format specification — was kept and moved to
`docs/hazel-format.md`.
