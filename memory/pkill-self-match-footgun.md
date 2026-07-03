---
name: pkill-self-match-footgun
description: pkill/pgrep -f patterns in a Bash tool call match the wrapper shell's own cmdline — the shell kills itself (exit 143/144); use [b]racket patterns or exact PIDs
metadata:
  type: feedback
---

The Bash tool runs commands via a wrapper shell whose command line contains the
FULL literal command text. So `pkill -f 'cottontail-jsonl-server --burrow'` (or
any -f pattern that appears verbatim in the command) matches the wrapper itself
and kills the running shell mid-command — observed as exit code 143/144 with
the rest of the compound command silently never executing. This hit three times
on 2026-07-03..05 (server restarts, A/B stop).

**How to apply:**
- Prefer two steps: `pgrep -f 'pattern'` to capture PIDs, inspect, then `kill <pids>`.
- If pattern-matching is needed, break the self-match with a character class:
  `pgrep -f 'searcher-ab/run[.]py'` — the wrapper's cmdline contains `run[.]py`,
  which the regex itself does not match.
- After ANY kill/pkill in a compound command, verify the rest of the command
  actually ran (an exit 143/144 means it did not).
- Related: `kill $(pgrep ...)` inside the same compound still self-matches if
  the pattern is literal — the class trick applies there too.
