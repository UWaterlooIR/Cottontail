# Findings — multitext-dsl-2: tool-call emission, stem*, multi-turn (TASK-26, 2026-07-03)

Three scouts de-risking TASK-22 (MultiTextTieredSearcher), requested by Mark.
Setup: gpt-oss-120b on vLLM (127.0.0.1:8000), temperature 0, reasoning_effort
medium (the combo validated in ../multitext-dsl/), `//apps:mt-compile` as the
validity oracle, the live 1M dev server (port 8081) for end-to-end runs. Same
10 TREC-4 topics as the original scout for S1/S2; hand-written general-web
needs for S3 (ClimbMix is a general web corpus — nothing to do with climbing).

## S1 — program as a TOOL CALL: **GO** (10/10 emit, 10/10 compile)

The original scout captured programs from the plain content channel (its
`run.py` defined the tool but never passed it), and earlier attempts at
tool-call emission reportedly failed. Re-run through the REAL emission path —
`tools=[submit_tiered_query]`, `tool_choice="required"`, non-streaming, exactly
`BaseSearcher.propose` (`captured/2026-07-03-toolcall*.jsonl`):

- **10/10 topics returned a proper tool call**; the multi-line program survived
  JSON newline escaping every time; zero content-channel leakage; reasoning
  stayed 1.2–3.3K chars (the content-mode baseline's range); ~5 s/topic.
- First pass compiled 8/10. Both failures were ONE root cause, new to us:
  **Mt's lexer rejects underscores in identifiers** (`q_ind`, `int_med` →
  "Undefined symbol"; verified directly: `a_b = "x"` fails, `ab = "x"`
  compiles). The old scout never saw it because those models happened to write
  `bc0`-style names.
- One prompt line ("Macro names are short lowercase letters+digits like bc0 —
  NO underscores, NO hyphens") → **10/10 compile** (`captured/2026-07-03-toolcall.jsonl`;
  the pre-fix run is `2026-07-03-toolcall-v1.jsonl`).
- Also verified harmless: unparenthesized `+`/`<>` mixing compiles (left-assoc).

## S2 — stem* (word* families): **GO** (10/10 compile, sensible usage, e2e clean)

- **No-LLM pre-check:** starred quoted tokens (`"bear*"`, incl. inside `<>` and
  `< [N]`) compile through Mt unchanged, and the compiled tier desugars
  end-to-end through the cover path (`--cover` on the 1M burrow): `bear*`
  resolved to its stem family (63,691 family occurrences in atom_counts) and
  ranked normally. Note: Mt does NOT validate star placement — that is
  cover_rewrite's job at the server, so a mid-word star only surfaces at run
  time (the bounce covers it).
- **LLM run** (prompt + a word* rule and a star-using example;
  `captured/2026-07-03-stem.jsonl`): 10/10 tool calls, 10/10 compile; 105 of 279 quoted
  tokens starred (38%), ZERO bad star placements; usage is sensible (stars on
  content words, exact forms kept where appropriate).
- **All 35 compiled tiers ran against the live 1M cover path.** This sweep also
  smoked out a REAL BUG unrelated to the DSL: TASK-25's parallel_cover_ranking
  used `std::vector<bool>` for per-worker status — a packed bitfield, so
  concurrent workers' writes raced and intermittently reported a successful
  worker as failed (~3–10% of queries at 64 workers). Fixed (vector<char> +
  stage-tagged worker errors); verified with 210 consecutive tier runs, 0
  failures. Scouting with real queries pays.
- Cosmetic wart confirmed: the `N` in `(# N)` proximity windows shows up as an
  atom_counts "term" (e.g. `("10", 273740)`). The TASK-22 handler should skip
  numeric leaves.

## S3 — multi-turn with appended output: **GO** (16/17 turns clean, no loop regression)

Adapted the prompt to a turn loop (role + feedback instructions; kept the
anti-loop properties: no markup, tool-only output, medium effort). 4 general-web
needs × 3 turns (+ a 4-turn rerun) against the live server, prior turns' cps
excluded (controller-style paging), real responses (match counts, atom_counts,
280-char summaries) appended as tool results (`captured/2026-07-03-turns*.jsonl`):

- **16/17 turns emitted a valid tool call whose program compiled and ran**; the
  one failure was a malformed proximity chain (`t0 = (if) < [5] ad ^ h ^ s` →
  "Extra characters at the end" — the exact bounce-fixable class from the
  original scout).
- **Reasoning stayed 1.1–2.2K chars across ALL turns** — no bloat as the
  conversation grows; no degenerate loops. 3–13 s/turn.
- **Programs adapt**: 5–25 new quoted terms per turn (summaries' vocabulary
  folded into later facets); every turn surfaced 10 NEW documents (exclusion
  honored). Weakest adaptation: invasive t3 (1 new term). Match counts move in
  the right direction as tiers tighten/broaden.
- **Bounce self-correction** (`run_bounce_replay.py`, replaying the captured
  failure with its real diagnostics as the tool result): 2/3 trials repaired
  the program in ONE bounce; the temp-0 trial produced a different malformed
  proximity (would need a second bounce). One retry is usually enough; the
  TASK-22 controller loop's normal bounce handling covers the rest.
- Query-craft note: the failing construct wanted proximity-JOIN semantics
  ("A within N tokens of B"), which `< [N]` does not express (it is a width
  constraint on one expression). The prompt could show the idiom
  `((a ^ b)) < [N]` explicitly.

## Net verdict for TASK-22

All three scouted risks clear. The design holds exactly as specified: tool-call
program emission works (with the no-underscore prompt rule), stem* composes
through Mt → cover_rewrite → stemmed stream untouched, and the multi-turn loop
is stable with adapting programs and a working compile-error bounce. Carry into
TASK-22: (1) the no-underscore rule, (2) the word* rule + starred example,
(3) numeric-leaf filtering for atom_counts in the handler, (4) a proximity-join
idiom example, (5) allow >=2 bounce retries per turn.

## Data + code

- `2026-07-03-toolcall-v1.jsonl` (pre-fix), `2026-07-03-toolcall.jsonl`
  (S1 final), `2026-07-03-stem.jsonl` (S2), `2026-07-03-turns.jsonl` +
  `2026-07-03-turns-bounce.jsonl` (S3), `2026-07-03-bounce-replay.jsonl`
  (bounce self-correction) — all in this directory. Working copies live in
  `../results/` (gitignored).
- Prompts: `prompt-toolcall.md`, `prompt-stem.md`, `prompt-turns.md`.
- Harness: `common.py`, `run_toolcall.py`, `run_turns.py`, `run_bounce_replay.py`.
