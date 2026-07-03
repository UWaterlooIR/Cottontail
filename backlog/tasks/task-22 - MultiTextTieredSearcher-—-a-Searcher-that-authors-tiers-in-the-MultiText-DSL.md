---
id: TASK-22
title: MultiTextTieredSearcher — a Searcher that authors tiers in the MultiText DSL
status: In Progress
assignee:
  - '@claude'
created_date: '2026-07-02 16:10'
updated_date: '2026-07-03 04:50'
labels:
  - enhancement
dependencies:
  - TASK-26
references:
  - isj/scouting/multitext-dsl/captured/FINDINGS.md
  - gcl/mt.cc
  - apps/mt-compile.cc
priority: medium
ordinal: 36000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A THIRD, interchangeable Searcher implementation (alongside the plain Searcher and the JSON TieredSearcher/TASK-20). Instead of emitting a JSON `tiers: [string]` list, the librarian writes a MultiText DSL PROGRAM — `name = expr` macros over `+` (OR), `^` (AND), `<>` (followed-by), `( ) < [N]` (width/proximity), quoted literals incl. `word*` stem families — ending in `@rank t0 t1 ...` (tiers, most precise first). Cottontail compiles this natively: gcl/mt.cc (Mt::infix_expression) parses statements and emits GCL; the compiled tiers feed the SAME tiered_query_search cascade (TASK-19, now parallel via TASK-25).

Motivation: the multitext-dsl scouting found this path beats the JSON-tool tiered designs — 100% compile, 0 timeouts, ~16x faster, cleaner query craft (isj/scouting/multitext-dsl/captured/FINDINGS.md).

DE-RISKED by TASK-26 (isj/scouting/multitext-dsl-2/captured/FINDINGS.md) — all three scouted risks GO:
- Tool-call emission works: 10/10 emit AND compile through the exact BaseSearcher path (tools + tool_choice=required), once the prompt constrains macro names (Mt's lexer REJECTS underscores in identifiers — 'Undefined symbol').
- stem* composes end-to-end: Mt passes starred quoted tokens; cover_rewrite desugars them to the stemmed family; the LLM stars ~38% of tokens with 0 bad placements.
- The multi-turn loop is stable: 16/17 turns clean over live feedback, reasoning flat at 1-2K chars, programs adapt; a compile-error bounce self-repairs in 1 retry 2/3 of the time (worst case 2 — the controller's normal bounce loop already allows this).

Carry-ins from scouting (bake into the implementation): (1) the no-underscore macro-name prompt rule; (2) the word* prompt rule + starred worked example; (3) [DONE 2026-07-03, folded into the ssr-parallel-etc branch: cover_leaves now skips a digits-only token iff it follows the '#' operator, fixing cover_search + tiered + the future multitext path at the source — no handler-side filter needed]; (4) add a proximity-join idiom example (((a ^ b)) < [N]) — the one observed failure wanted that semantics; (5) the validated multi-turn prompt is isj/scouting/multitext-dsl-2/prompt-turns.md — adapt it, do not rewrite from scratch.

Architecture (settled during TASK-26 study): a new server endpoint /tools/multitext_tiered_search takes {program, top_k, exclude, window}; the handler compiles the program server-side with a fresh Mt (statement walk exactly like apps/mt-compile.cc), returns HTTP 400 with per-statement diagnostics on any compile error (the controller's existing EngineError bounce carries it back to the model verbatim), and on success feeds the compiled tier s-expressions into jsonl_tiered_query_search. Python side: a MultiTextProgram Queryable (LLM tool name: submit_tiered_query, the scouted name) + engine.multitext_search + a thin MultiTextTieredSearcher(BaseSearcher). //apps:mt-compile remains the warren-free oracle for tests. Per Mark (2026-07-03): build on the CURRENT branch claude/ssr-parallel-etc (no new branch).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 New class isj_agent.agents.mt_tiered_searcher.MultiTextTieredSearcher subclasses BaseSearcher, is config-selectable via [agents.searcher].class, and needs NO base/controller changes
- [ ] #2 It exposes a single tool named submit_tiered_query (the scouted name) that accepts {program: string} — a MultiText DSL program (macros + one @rank line), NOT a JSON tiers list
- [ ] #3 The program is compiled server-side by a new /tools/multitext_tiered_search handler using a fresh cottontail::Mt per request (statement walk like apps/mt-compile.cc); any compile error returns HTTP 400 whose body carries the per-statement diagnostics, and the controller's existing EngineError bounce delivers them to the model as the tool result (verified self-repair in TASK-26); //apps:mt-compile is the warren-free oracle in unit tests
- [ ] #4 The compiled tiers feed the SAME jsonl_tiered_query_search cascade (ranking, summaries, cascade semantics, and atom_counts identical to the JSON TieredSearcher — the (# N) width-operand leaf fix already landed at the source in cover_leaves, 2026-07-03, so no handler-side filtering)
- [ ] #5 The prompt is the TASK-26-validated multi-turn prompt (isj/scouting/multitext-dsl-2/prompt-turns.md) carrying the no-underscore macro rule and the word* rule, plus a proximity-join idiom example; reasoning_effort defaults to medium
- [x] #6 A live end-to-end smoke: the isj CLI runs one real question with [agents.searcher].class set to MultiTextTieredSearcher against the 1M dev server, producing a normal run-output directory with valid traces
- [ ] #7 An A/B procedure compares MultiTextTieredSearcher vs the JSON TieredSearcher vs the plain Searcher on the same scoped needs (query validity, retrieval quality via judged grades, latency) and reports results; the question set and run budget are checkpointed with Mark before the runs
- [ ] #8 Unit tests cover the new Queryable (schema/args/execute/trace), the searcher class, the C++ handler (valid program parity with tiered_query_search, compile-error diagnostics, underscore diagnostic), and the compile-bounce path; bazel test //test:all and the full isj pytest suite pass
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
0. Preconditions
   0.1 Work on the CURRENT branch claude/ssr-parallel-etc (Mark, 2026-07-03: no new branch). Mark TASK-22 In Progress.

1. C++ — the multitext handler (apps/jsonl_core.{h,cc}, apps/cottontail-jsonl-server.cc)
   1.1 jsonl_core.h: struct MtSpec { std::string program; size_t top_k = 10; std::vector<addr> exclude; size_t window = 75; size_t max_covers = 1; size_t max_words = 150; size_t rank_threads = 1; } and
       bool jsonl_multitext_tiered_search(warren, const MtSpec&, CoverResponse*, std::string* error).
   1.2 Implementation (jsonl_core.cc, #include "gcl/mt.h" — available via //src:cottontail's gcl re-export):
       a. Statement walk exactly as apps/mt-compile.cc: split program on newlines, trim, skip blank/#/;; lines; a line starting with @ must be a well-formed '@rank name...' (tolerate the legacy numeric topic label); anything else is a definition fed to a FRESH per-call cottontail::Mt.
       b. Collect per-statement failures as mt-compile-style diagnostic lines ('DEF ERR <line>: <msg>' / 'TIER ERR <name>: <msg>'). ANY failure -> return false with *error = the joined diagnostics (this becomes the bounce text). Also fail on: no @rank line, an @rank naming zero tiers, more than one @rank.
       c. On success: TieredSpec{tiers = the compiled tier s-expressions, top_k/exclude/window/max_covers/max_words/rank_threads copied} -> jsonl_tiered_query_search.
   1.3 Server: POST /tools/multitext_tiered_search; body {program (required), top_k, exclude, window, max_covers?, max_words?}; mt_spec_from() stamps g_rank_threads like the other builders; compile/validation failure -> fail(res, 400, error, "multitext_tiered_search") — rides the existing EngineError bounce. Request/response logging identical to tiered_query_search.
   1.4 Tests: test/jsonl.cc — (i) PARITY: a fixed valid program vs jsonl_tiered_query_search called directly with the same tiers pre-compiled via Mt in the test -> identical CoverResponse; (ii) underscore macro name -> false, diagnostic names the line; (iii) malformed proximity chain (the captured 't0 = (a) < [5] b ^ c' shape) -> false with 'Extra characters' diagnostic; (iv) missing @rank / empty @rank -> false. test/jsonl_server.cc — endpoint 200 happy path; 400 body carries the diagnostics; bad-shape body -> 400.
   1.5 bazel test //test:all green.

2. Python — Queryable, engine, searcher (isj/)
   2.1 protocol/queryable.py: frozen dataclass MultiTextProgram(Queryable){program: str}; tool_name = "submit_tiered_query"; tool_schema = the TASK-26 TOOL schema (program: string, required); from_tool_arguments raises on missing/non-string/empty program (BaseSearcher bounces); execute -> engine.multitext_search(self.program, top_k=, exclude=, window=); trace_arguments {"program": program}; query_string() = the program verbatim (heavy traces are the house style).
   2.2 engine/base.py Protocol + engine/http.py: multitext_search() POSTing /tools/multitext_tiered_search; non-200 -> EngineError carrying the server body (the compiler diagnostics) — same shape as tiered_search. engine/fake.py: scripted multitext_search for controller-level tests.
   2.3 agents/mt_tiered_searcher.py: MultiTextTieredSearcher(BaseSearcher) with query_types=[MultiTextProgram]; prompt file agents/mt_tiered_searcher.md = prompt-turns.md VERBATIM plus (a) the proximity-join idiom example (((a ^ b)) < [N]) with one sentence of when to use it, (b) nothing else changed — the prompt is validated, resist rewrites. config.example.toml gains the commented class line.
   2.4 Tests (isj/tests): test_queryable additions (schema, args validation incl. empty program, execute routing, trace forms); test_mt_tiered_searcher (FakeEngine + scripted LLM: emits a program, malformed tool args bounce); controller compile-bounce e2e vs a FakeEngine whose multitext_search raises EngineError with diagnostics -> next turn's tool result carries them. Full suite: uv run pytest.

3. Live smoke (AC #6)
   3.1 Config-select MultiTextTieredSearcher; run the isj CLI on ONE real question against the port-8081 1M server; verify the run-output directory: programs in traces, judged results, no controller changes needed. Fix only what the smoke exposes.

4. A/B procedure (AC #7) — CHECKPOINT WITH MARK BEFORE THE RUNS
   4.1 Harness isj/scouting/searcher-ab/: for each searcher class (Searcher, TieredSearcher, MultiTextTieredSearcher) run the SAME question set through the full isj pipeline (same Analyst intents replayed to all three if feasible — else same questions), same server, same budgets. Capture per intent: query validity (bounce counts), latency per turn, judged grades of surfaced docs, distinct relevant docs found.
   4.2 Propose the question set (~5-8 general-web questions) + turn/judgment budget to Mark; run after approval; summarize in searcher-ab/captured/FINDINGS.md with a recommendation.
5. Docs + finalize
   5.1 isj/README.md: the three searcher classes and how to select them; brief pointer in running-the-search-stack.md's isj section. backlog notes/ACs; PR from the feature branch to main.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Live smoke (AC6) PASSED: full isj pipeline (Analyst -> MultiTextTieredSearcher -> Judger) on 'health effects of intermittent fasting on adults' vs the 1M dev server: 142 judged ranked entries, 6 searcher turns at medium effort (300-1300 completion tokens/turn, scouting-range), 0 compile bounces, 2 defensive no-tool-call bounces recovered by the inherited BaseSearcher path. Turn-1 program was idiomatic faceted MultiText with stem stars. Two operational findings en route: (1) the first smoke attempt 404'd because the dev servers predated the endpoint — server/agent version skew surfaces as 'HTTP 404:' bounces, and the model responds by needlessly simplifying its programs; (2) Mark's live config sets searcher reasoning_effort=high, which reproduces the known reasoning-bloat mode on this searcher (26K-token turns) — the config MUST say medium when class is switched to tiered/multitext.
<!-- SECTION:NOTES:END -->
