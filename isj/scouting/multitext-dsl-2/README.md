# multitext-dsl-2 — TASK-26 pre-scouting for TASK-22

Three scouts over the MultiText-DSL librarian (sequel to `../multitext-dsl/`):

1. **Tool-call emission** (`run_toolcall.py`, `prompt-toolcall.md`) — the
   program submitted through `submit_tiered_query` with `tool_choice=required`
   (the real BaseSearcher path), not the content channel.
2. **stem\*** (`prompt-stem.md`; same runner with `--prompt/--out`) — `word*`
   family markers in the DSL, validated end-to-end (Mt → cover_rewrite →
   stemmed stream).
3. **Multi-turn** (`run_turns.py`, `prompt-turns.md`) — 3+ turns against the
   live 1M dev server with real tiered_query_search feedback appended;
   `run_bounce_replay.py` replays a captured compile failure to test the
   bounce self-correction.

Verdicts + data: [`captured/FINDINGS.md`](captured/FINDINGS.md). All three: GO.
Requires: vLLM (127.0.0.1:8000), the port-8081 dev server, and
`bazel build //apps:mt-compile`.
