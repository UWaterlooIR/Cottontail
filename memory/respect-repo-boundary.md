---
name: respect-repo-boundary
description: Hard rule — never access anything outside the repo without explicit permission
metadata:
  type: feedback
---

Operate **only within the project repository**. Never read, list, write, run
against, or otherwise touch anything outside the repo root without **explicit,
specific permission for that exact action** — especially credentials (SSH/GPG
keys, tokens, `~/.ssh`, credential stores), the home dir/dotfiles, other repos,
and system files. Actions that reach outside (installing software, pushing,
external network calls) also each need their own go-ahead. Permission for one
outside action does not generalize.

**Why:** the user gave this as firm correction after I listed `~/.ssh` and probed
SSH keys while debugging git push — a real boundary/credential violation. Trust
depends on never doing that.

**How to apply:** if something outside the repo seems needed, stop and ask first,
naming exactly what and why. When in doubt, treat it as outside and ask. The same
rule is written into `/CLAUDE.md` ("Boundaries — read this first"). See
[[project-cottontail-overview]].
