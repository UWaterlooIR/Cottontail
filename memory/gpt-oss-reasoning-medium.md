---
name: gpt-oss-reasoning-medium
description: gpt.oss.120b on the local vLLM — use reasoning_effort medium, NOT high (high makes it go nuts)
metadata:
  type: feedback
---

For the local vLLM `gpt.oss.120b` endpoint (`http://127.0.0.1:8000/v1`), use
`reasoning_effort="medium"`, not `"high"`.

**Why:** Mark: "the LLM goes nuts with high reasoning." Confirmed in the
LucindriSearcher query-generation scout (2026-07-08) — medium gives clean,
single-tool-call query generation (~600–1500 completion tokens/turn).

**How to apply:** Pass `extra_body={"reasoning_effort": "medium"}` (the agents'
mechanism). NOTE the tension: `isj/config.toml` currently sets
`reasoning_effort = "high"` for [agents.searcher] and [agents.judger] — revisit
those if gpt-oss misbehaves. See [[interruption-resets-consent]] before acting
on this unprompted.
