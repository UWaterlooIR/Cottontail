---
name: working-agreement-plan-approval
description: Hold an explicitly approved plan before making any repository change
metadata:
  type: feedback
---

**Hold an explicitly approved plan before making any change to the repository.**
Reading/exploring/summarizing never needs approval. "Familiarize yourself with
X", "look at Y", "what does Z do?" are exploration only — they do **not**
authorize edits, commits, or pushes. Before creating/editing/moving/deleting any
file, or any commit/push, state the plan explicitly and wait for approval. Once a
plan is approved, execute it in full without asking per step. After finishing,
flag anything noticed that was outside the approved plan, but don't act on it
without new approval.

**Why:** the user's standing working agreement. Pairs with the boundary rule —
together they define how I'm expected to operate. See [[respect-repo-boundary]].

**How to apply:** treat ambiguous "do work" requests as needing a stated plan
first. Same text is in `/CLAUDE.md` ("Working agreements with Claude") and the
user's global `~/.claude/CLAUDE.md`. See [[project-cottontail-overview]].
