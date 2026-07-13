# SearchCoach novelty-signal scouting (v7–v10)

**Result: prompt-v10 shipped as `isj_agent/agents/search_coach.md` (2026-07-13).**

## Motivation

Analyzing dev runs, the coach could not tell when the searcher was **stuck re-mining
already-judged documents** — `CoachContext` carried `is_new` per result and novelty `stats`, but
the `SearchCoachAgent` never surfaced them to the prompt. So it couldn't coach a searcher out of
a rut (the plateau counterpart to a 0-result over-constrained query).

## Prompt / rendering progression

- **v7** — feed the novelty signal: each already-judged passage tagged
  `(already judged on an earlier query)` (from `is_new`), plus a one-line **RESULT NOVELTY**
  summary (`{novelty}`: N judged, X new, Y revisits, total_matches). Prompt adds a "Watch for a
  searcher stuck in a rut → shift/loosen" instruction. Code: `search_coach._novelty_line` + the
  `{novelty}` substitution; scout `run.py` is novelty-aware (gated on the `{novelty}` placeholder,
  so v6 still runs unchanged).
- **v8 — REJECTED (kept as evidence of failure).** Idea: *withhold the text* of already-judged
  revisits (only `[Rn] grade=X (resurfaced document: …)`), to steer the coach off their content.
  **It hallucinated** — starved of the text, the model fabricated the hidden passages' content
  (e.g. described `[R1]`/`[R20]` in detail though it never saw them). Lesson: keep the text; fix
  over-focus with *instruction*, not by *withholding information*. (Scout flag: `--revisit-text hide`.)
- **v9** — v7 + "Do NOT re-critique the content of a resurfaced passage." gpt-oss largely ignored
  the negative instruction; ≈ v7 (a bit tighter, fewer passages cited). Soft effect.
- **v10 — shipped.** Blunt rut-coaching addressed to "you" (in every section: if mostly judged,
  tell them plainly to change strategy — shift/loosen). Plus a source-type rule mirroring the
  Analyst v3 fix ("cleaned web text, no source info; do NOT specify sources unless requested").

## Multi-query experiment (the single q19 data point was confounded + oversold)

Ran v6/v7/v9 (and v10) over **4 revisit cases from *sensible* intents** (societal-impact-of-sports,
`gcl-cover/14` + `multitext/14` intent-00 — the same traces earlier scouting used): a 0%-revisit
control, 96%, 100%, and a 46% partial rut. Transcripts in `captured/experiment/`.

Findings:
1. **Novelty (v7/v9/v10) > blind (v6), but modestly.** With the signal the coach consistently
   *names* the rut and leads with shift/broaden; v6 only stumbles onto it. Not the dramatic effect
   the single q19 (v6-vs-v7) contrast suggested — that point was confounded (q19's intent was the
   pathological source-hunting intent-02, since removed by Analyst v3).
2. **v10's rut-coaching is the best** — blunt, "you"-addressed, correctly flags "only newly
   surfaced document" / "you keep resurfacing the same pool."
3. **v10's source-type rule did NOT take.** Source-type mentions per report were ~unchanged across
   v6/v7/v9/v10 (e.g. mt14-q6: 12/19/14/17). The coach still recommends "handbook / edited volume /
   policy report / peer-reviewed." Likely cause: on these topics the *high-grade relevant passages
   genuinely are* academic books/handbooks (*Routledge Handbook of the Sociology of Sport*, *The
   Economics of Football*), and the coach is told to mine vocabulary *from the relevant passages* —
   so the rule fights the data. Buried at the bottom of the prompt, it was ignored.

## Open / next

- **Report-by-inspection has weak signal.** The only test that matters — does the coaching improve
  **recall**? — is unmeasured. The Analyst change moved recall 6→35 on a real run+qrels; the coach's
  marginal contribution is unknown. Next step: a **coach-A/B recall measurement** on a few dev
  topics (v10 vs mechanical, or vs coach-off), now feasible OOM-free via `run_topics_cycled.py`.
