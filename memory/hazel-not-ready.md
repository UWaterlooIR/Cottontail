---
name: hazel-not-ready
description: Hazel is not declared ready for use — fork builds no features on it, even though upstream landed the Bigwig integration
metadata:
  type: project
---

**Hazel has not been declared ready for use — the fork builds no features on
the Hazel path.** Source: Charlie Clarke (the original author), relayed by Mark
Smucker on 2026-06-12; status revisited at the 2026-07 upstream sync
([[upstream-sync-claclark]]).

**Update (2026-07-03):** upstream finished the Hazel/Bigwig integration in June
2026 (restartable Hazel merges, OwslaCache, Hazel shards activated inside
Bigwig, consolidation policy in the merge workers) and that code is now merged
into the fork. But "integration landed" ≠ "declared ready": until Charlie says
Hazel is ready, keep fork features off the Hazel path.

**Why:** a green `//test:hazel_test` is a narrow regression check, **not** a
readiness signal, and readiness is upstream's call.

**How to apply:**
- Don't build new fork features on the Hazel path (`Fiver::hazel(...)`,
  `Hazel::merge(...)`, opening Hazel shards, `//apps:fiver2hazel`,
  `//apps:merge-hazels`). Prefer `SimpleWarren` (static disk burrow) or
  `Bigwig`/`Fiver`.
- The Hazel format spec is upstream's live `ai/hazel.md`
  (`docs/design/reference-specs/hazel-format.md` is just a pointer stub now).
- If Charlie declares Hazel ready, update this memory and the CLAUDE.md
  Warren-table caution together.
