---
name: hazel-not-ready
description: Hazel is a work in progress, not ready for use — don't build features on it
metadata:
  type: project
---

**Hazel is a work in progress and not ready for use.** Source: Charlie Clarke
(the original author), relayed by Mark Smucker on 2026-06-12.

**Why:** Hazel (the immutable single-file shard Warren) is incomplete despite
having a passing regression test and an on-disk format spec. A green
`//test:hazel_test` is a narrow regression check, **not** a readiness signal.

**How to apply:**
- Don't build new features on the Hazel path (`Fiver::hazel(...)`,
  `Hazel::merge(...)`, opening Hazel shards, `//apps:fiver2hazel`). Prefer
  `SimpleWarren` (static disk burrow) or `Bigwig`/`Fiver`.
- The JSONL CLI spec (`docs/cottontail-jsonl-cli-spec.md`) already targets a
  static `SimpleWarren` — the right call; keep new work off Hazel.
- The uncommitted `apps/climbmix-poc.cc` exercises the Bigwig→Hazel
  convert/merge/rank tail; treat any result from its `[hazel]` stage as
  unreliable. See [[project-cottontail-overview]].

This sharpens the existing note that the fork's goal is **not** continuing
Clarke's in-progress Fiver/Hazel integration: Hazel itself, not just the
integration, is unfinished.
