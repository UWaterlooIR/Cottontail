---
name: memory-location
description: Project memory lives inside the repo at ./memory/, not in ~/.claude
metadata:
  type: feedback
---

The user wants project memory maintained **inside the repo** at `./memory/`
(relative to repo root), not in the default `~/.claude/projects/.../memory/`
location. Write/update memory files and `MEMORY.md` there.

**Why:** keeps project knowledge versioned with the code and shareable via git
(the `memory/` dir is not gitignored).

**How to apply:** create and update memory under `<repo>/memory/`. Note the
harness auto-loads `MEMORY.md` from the `~/.claude` path, so the in-repo index is
not injected automatically — read `<repo>/memory/MEMORY.md` at session start to
pick up project memory. See [[project-cottontail-overview]].
