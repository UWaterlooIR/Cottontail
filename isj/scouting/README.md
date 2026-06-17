# Scouting — probing tool-using LLMs against the Searcher loop

`scout_searcher.py` is a **probe**, not part of the `isj_agent` package and not a
test. It makes **live network calls** to an OpenAI-compatible endpoint (a local
vLLM) and reports how a given model behaves in the Interactive-Searching-and-Judging
loop we are designing for the Searcher. It is deliberately kept out of the package
and the test suite because it needs a running model.

Full rationale and the per-model findings this script produced are in
[`docs/searcher-agent-lessons-June-16-2026.md`](../../docs/searcher-agent-lessons-June-16-2026.md).

## What it runs

The validated "current working scout":

- the `word*` family-marker prompt + Charlie's facet-cover query shape (§3 of the
  lessons doc, embedded as `SYSTEM_PROMPT`);
- a loop with **one tool call per turn**: `search` (GCL query) then `judge` (a
  **batch** array of `{docid, grade, reason}`);
- the loop-controller **guardrails**: a valid-GCL gate, judge-before-search, and a
  model-agnostic termination (stop after 2 dry searches, a no-progress break for
  models that spin, and a hard turn/search budget);
- a tiny canned **"black bear attacks"** corpus, so runs are deterministic and need
  no real index.

## Running it

From the repo root, with a model already served at the endpoint:

```sh
uv run --directory isj python scouting/scout_searcher.py --model gpt.oss.120b
uv run --directory isj python scouting/scout_searcher.py --model Qwen3.6.27B
uv run --directory isj python scouting/scout_searcher.py --model gemma.4.31b.it
```

Flags: `--base-url` (default `http://127.0.0.1:8000/v1`), `--api-key` (default
`EMPTY`, fine for unauthenticated local vLLM), `--max-turns` (default 16),
`--budget` (max accepted searches, default 8).

## Reading the report

Each turn is logged (`#calls`, the tool, the GCL query or judgements). The summary:

| Field | Healthy value | What a bad value means |
|---|---|---|
| `terminated` | `STOP …` (no tool call, or a controller stop) | `HIT turn cap` / `HIT search budget` → the model would not stop on its own |
| `turns with >1 tool call (parallel)` | `0` | model emits parallel calls — but vLLM/the parser may drop all but one (gpt-oss did); the batch `judge` tool is the workaround |
| `invalid-GCL rejections` | `0` | model wrote non-prefix / infix / `AND`/`OR` GCL (regresses if the prompt's worked example is weakened) |
| `premature-search rejections` | low, and recovered | model tried to search before judging surfaced passages |
| `porter: leakage` | `0` | model used the engine's `porter:` form instead of the `word*` marker (invites stem-guessing) |
| `hand-enumerated inflection pairs` | `0` | model spelled out plurals/tenses instead of relying on `word*` |
| `starred words used` | full words (`attack`, `injury`) | truncated stems (`stat`, `injur`, `hik`) → silent misses under tool-side stemming |
| `never judged` | `none` | a surfaced passage was dropped without a judgement (recall bug) |

## Caveats

- **Live calls only** — never run in CI; it talks to whatever model is up on the
  endpoint.
- **Canned engine** — this measures *loop behavior and GCL/stemming hygiene*, not
  retrieval quality on real text.
- It freezes the current working scout. Earlier diagnostic variants (tool-call
  capability checks; the `porter:` vs `word*` stemming-landmine comparison) live in
  the conversation record and the lessons doc, not here.
