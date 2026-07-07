---
name: interruption-resets-consent
description: An interruption or mid-task question from Mark PAUSES the work — answer, then propose the next action and WAIT; never silently resume or bundle the fix with the resume
metadata:
  type: feedback
---

When Mark interrupts a running command or asks a question mid-execution, the
task is PAUSED regardless of any earlier plan approval. The right shape is:

1. Answer the question fully.
2. State plainly what the next action would be (and any fix being applied).
3. WAIT for his go-ahead before running anything.

Do NOT bundle "the fix + the re-run" into one command on the heels of answering,
and do not treat the prior plan approval as license to resume — the
interruption itself withdrew it. (2026-07-04, during the TASK-22 live smoke:
after his reasoning-effort question I twice launched the fixed re-run without
proposing it; he had to reject the tool call both times.)

**Why:** Mark interrupts precisely because he wants visibility or has a concern;
resuming unannounced makes the work opaque at the exact moment he asked for
clarity.

**How to apply:** after ANY rejected tool call or interruption, end the next
message with a question/proposal, not an action. Related:
[[working-agreement-plan-approval]].
