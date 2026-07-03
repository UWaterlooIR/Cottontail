---
name: leave-dev-server-running
description: Don't ask about killing/restarting the running cottontail-jsonl-server; leave it up
metadata:
  type: feedback
---

Do not offer to kill or ask about restarting the running `cottontail-jsonl-server` (currently the
100M burrow `/share/indexes/climbmix-100M-porter.burrow` on port 8080). Assume it persists across
turns and keep using it for live probes.

**Why:** Mark runs a long-lived dev server on purpose; repeated "want me to kill it?" prompts are
friction.

**How to apply:** Only restart the server when something server-side actually changes — a rebuild
of the server binary, a burrow/index change, a config/port change, or a crash. Otherwise leave it
running and don't bring it up. Related: [[dev-burrow-climbmix-100k]], [[simplewarren-scaling-model]].
