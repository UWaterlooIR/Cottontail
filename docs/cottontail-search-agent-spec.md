# Specification: Cottontail search as an LLM agent tool

**Audience:** an implementing agent with full access to this repository.
**Goal:** harden `cottontail-jsonl-query` into a clean **tool API for an LLM
search agent**, and build a **minimal example app** that drives it in a ReAct
loop against an LLM served by **vLLM**.

This extends `docs/cottontail-jsonl-cli-spec.md` (the query/index contract) and
`docs/stemming.md` (`--stem`). It does **not** change the index format or the
ranking model.

## 0. Strategy and scope

The CLI is the **exemplar where we get the API right**. Everything here is
designed so the *same action schema and JSON contract* can later be lifted into a
server (REST/MCP) verbatim — the server is explicitly **out of scope** for now
(§8). Two pieces:

- **Part A — refine the CLI for tool use** (§§2–4): add a *read-document-by-docid*
  action, a machine-readable *tool description*, and small result-set signals an
  agent needs to reformulate.
- **Part B — an example LLM-driven search agent** (§§5–6): a small program that
  loops an LLM over the tools via native function calling, plus a concrete vLLM
  model recommendation.

Non-negotiable principles carried over: exact-by-default, no precomputed stats,
token-cheap output, stable `snake_case` JSON, and **the query tool never mutates
the burrow**.

## 1. Why these specific additions (agent-usability rationale)

A ReAct agent runs Thought → Action → Observation and reformulates as it learns.
The current tool already gives it a progressive action space (`--text` → `--gcl`
→ `--stem`), token-cheap observations (best-passage snippets, full text on
demand), and a cheap self-correction signal (`--explain`'s per-term `df` and
`stream`). The gaps:

1. **Read a document by id.** The classic loop is *search → pick a hit → read it
   in full*. Today full text only comes attached to a search hit; the agent needs
   a direct `docid → full row` action to read a candidate it found earlier.
2. **A tool description the model can consume.** The agent must be *taught* the
   action space — especially GCL — as structured tool definitions + a cheatsheet,
   or it will default to bag-of-words and never use precision/recall operators.
3. **Result-set signals.** The agent needs to know whether there is *more* beyond
   `top_k` (refine vs. stop) and roughly how selective a query is.

## 2. The action space (the API we are converging on)

Five actions. Each maps 1:1 to a future server/MCP tool. Names in parentheses are
the tool-schema names (§4).

| Action | Tool name | Purpose | Exists? |
|---|---|---|---|
| Ranked bag-of-words | `search_text` | Broad "just find relevant rows", cover-density ranked. | yes (`--text`) |
| Structured query | `search_gcl` | Boolean / phrase / proximity / containment precision. | yes (`--gcl`) |
| Validate / diagnose | `explain` | Dry-run: per-term `df` + `stream`, no ranking. Spot zero-posting terms before spending a query. | yes (`--explain`) |
| Read a document | `get_document` | Fetch a full row by `docid`. | **new (§3.1)** |
| Count | `count_matches` | Cheap count of matching rows for selectivity. | **new (§3.3)** |

`--stem` is a **modifier** on `search_text`/`search_gcl` (a boolean arg), not a
separate action. `top_k`, `full_text`, `snippet_chars`, `ranker` are args as
today.

## 3. CLI additions (Part A — the concrete work)

### 3.1 `get_document` — read a row by docid (required)

**CLI:** `cottontail-jsonl-query --burrow <b> --get <docid> [--format json|jsonl]`.
Add `--get` to the mode set; exactly one of `--text` / `--gcl` / `--get` /
`--batch` must be supplied.

**Library:** add to `apps/jsonl_core.{h,cc}`:

```cpp
// Fetch the full body of the row whose :docno equals `docid`.
// found=false (not an error) if no such row. Returns false only on a hard error.
bool jsonl_get(std::shared_ptr<Warren> warren, const std::string &docid,
               std::string *text, bool *found, std::string *error);
```

**Mechanism (recommended).** The index lays each row down as
`add_text(docid) → [p_id,q_id]` with `:docno` over `[p_id,q_id]`,
`add_text(contents) → [p_body,q_body]`, and `:item` over `[p_id,q_body]`
(`apps/jsonl_core.cc`). To resolve a docid:

1. Tokenize the docid with `warren->tokenizer()->split(docid)` and build a GCL
   that finds an `:item` containing a `:docno` that contains that token sequence,
   e.g. `(>> :item (>> :docno (... t1 t2 … tn)))` (a lone token for a
   single-token docid).
2. Walk the solutions; for each, recover the candidate docid via the `:docno`
   hopper + `txt()->translate(...)` (same idiom as `jsonl_query`) and **require an
   exact string match** to `docid` (guards against a docid whose token sequence is
   a subset of another's). On match, set `*found=true` and
   `*text = txt()->translate(p_body, q_body)` (the body after the `:docno` span).
3. No match → `*found=false`.

**Output (`--format json`):**

```json
{ "docid": "shard_00057_0", "found": true,
  "text": "The elephant ... full row body ..." }
```

`found:false` (unknown docid) is **success, exit 0** with `"found": false` and
`"text": ""` — consistent with "empty results are success" (§2 of the CLI spec).
A missing/corrupt burrow is still exit 2 with `{"error","where"}`.

**Tests:** a known docid returns the full body; an unknown docid →
`found:false`, exit 0; a docid whose tokens are a prefix/subset of another's
resolves to the right row (exact-match guard).

### 3.2 Result-set signals on search output

Add to the `search_text`/`search_gcl` result object (§4.4 of the CLI spec):

- `"result_count"`: number of results returned (≤ `top_k`).
- `"truncated"`: the **cheap heuristic** `result_count == top_k` — i.e. "the
  result set was at least as large as the slice you asked for, so there may be
  more." This is free (no extra pass). It is intentionally approximate (exactly
  `top_k` matches looks the same as far more) and carries **no count** — when the
  agent wants the exact number it calls `count_matches` (§3.3).

This lets the agent decide *refine vs. stop* at zero cost, and keeps the common
ranked-search path from paying for a full match count on broad queries.

### 3.3 `count_matches` (required)

A cheap "how many rows match" for selectivity, with **no ranking**: build the
query's `:item` hopper (and for `--text`, an all-of of the terms), walk container
solutions, count. CLI: `--count` with `--text`/`--gcl` (honors `--stem`). Output
`{ "query": ..., "match_count": N }`. It is one container-hopper pass, no scoring
— the agent's on-demand companion to the cheap `truncated` heuristic (§3.2).

### 3.4 `--describe` — emit the tool schema (required)

`cottontail-jsonl-query --describe` prints, to stdout, a JSON array of tool
definitions in the **OpenAI/Anthropic function-tool shape** (name, description,
JSON-Schema `parameters`) for `search_text`, `search_gcl`, `explain`,
`get_document` (and `count_matches` if built). The example app (§5) loads this
verbatim to give the model its tools — and the future server exposes the
identical schema. Keep the GCL cheatsheet (the operator table from CLI-spec §7) in
the `search_gcl` description so the model learns the operators from the tool spec
itself. See §4 for the exact content.

## 4. The tool schema (authoritative content for `--describe`)

Each tool's `description` must teach the model *when* to use it. Sketch (fill in
JSON-Schema `parameters`):

- **`search_text`** — "Find rows relevant to a natural-language phrase, ranked by
  proximity (cover density). Use first for broad recall. Params: `query`
  (string), `top_k` (int, default 10), `stem` (bool — set true to also match
  morphological variants, e.g. run↔running; trades precision for recall),
  `full_text` (bool)."
- **`search_gcl`** — "Structured search when you need precision: Boolean,
  phrase, proximity, containment. Query is a GCL S-expression. Operators:
  `(^ a b)` both terms (smallest covering span); `(+ a b)` either; `(... a b)`
  a then b in order/proximity; `(>> :item (^ a b))` rows *containing* both;
  `(<< a :item)` a contained in a row. Tags: `:item` = a whole row, `:docno` =
  the id. Params: `query`, `top_k`, `stem`, `full_text`."
- **`explain`** — "Dry-run a query without ranking: returns each term's document
  frequency and which stream (exact|stemmed) it resolved against. Use to check a
  term isn't zero-hit before spending a real search. Params: `query`, `is_gcl`
  (bool), `stem` (bool)."
- **`get_document`** — "Read a full row by its docid (from a prior result).
  Params: `docid` (string)."

The agent harness sends these as the model's `tools`; the model replies with tool
calls, which the harness executes against the CLI/library.

## 5. Part B — the example LLM-driven search agent

A minimal, readable program that demonstrates an LLM driving the tools in a
ReAct loop. It is an **example/reference**, not production.

### 5.1 Architecture

- **LLM:** served by **vLLM** behind its OpenAI-compatible
  `/v1/chat/completions` endpoint, with **native tool/function calling** enabled
  (vLLM `--enable-auto-tool-choice --tool-call-parser <parser>`). Prefer native
  tool calling over text-pattern ReAct parsing — it is far more robust.
- **Tools:** load the JSON from `cottontail-jsonl-query --describe` and pass it as
  the request `tools`. Map each tool call to a CLI invocation (subprocess) or, if
  the example is C++, a direct `jsonl_core` call.
- **Loop:**
  1. System prompt: role ("you are a search agent over corpus X"), how to use the
     tools (start broad with `search_text`; use `explain` to check rare terms;
     escalate to `search_gcl` for precision; `get_document` to read a hit before
     answering; cite docids), and the answer format.
  2. User question → request with `tools`.
  3. If the model returns tool calls: execute each, append the JSON result as a
     `tool` message, loop. If it returns content: that's the final answer.
  4. **Budgets:** max tool calls per question (e.g. 8), default `top_k` small
     (e.g. 5), truncate `text`/snippets fed back into context, hard wall-clock or
     token cap.
- **Output:** final answer plus the list of `docid`s cited and the tool-call
  trace (for inspection).

### 5.2 Configuration

CLI/env: vLLM base URL + model name + API key (dummy ok), burrow path, max steps,
default `top_k`, snippet budget. No secrets in the repo.

### 5.3 Language and placement

Implement in **Python** (the OpenAI client pointed at vLLM) under
`examples/agent/`. Python and shell are first-class in this repo (the old
`*.py`/`*.sh` `.gitignore` rules were removed), so the demo is a normal committable,
runnable file — no special handling. Keep it dependency-light (the `openai`
client + the standard library) and shell out to `cottontail-jsonl-query`, or call
a thin Python wrapper around it. Pin deps in an `examples/agent/requirements.txt`.

### 5.4 Acceptance / tests

The LLM is non-deterministic, so test the **harness**, not the model:

- A **stub LLM** (canned tool-call sequence) drives the loop end-to-end against a
  tiny fixture burrow and asserts the loop executes the right tool calls, feeds
  observations back, and terminates on a final answer within budget.
- `--describe` output parses as JSON and contains the expected tool names/params
  (a schema-shape regression).
- `get_document` round-trips a known docid (§3.1 tests).

A separate, **manual** smoke script (not committed if `.sh`/`.py`) runs the real
vLLM model on a couple of questions for a human to eyeball.

## 6. Recommended LLM(s) to serve via vLLM

**Hardware (measured, `nvidia-smi` 2026-06-13):** two *heterogeneous* GPUs —
GPU 1 = **RTX PRO 6000 Blackwell Max-Q, 96 GB** (sm_120, native FP4/FP8);
GPU 0 = **RTX A6000, 48 GB** (Ampere sm_86, no FP8/FP4). Driver 580.142, CUDA 13.0.
Do **not** tensor-parallel across them (heterogeneous TP is unsupported and the
Ampere card blocks FP4/FP8) — run **two separate vLLM instances**, pinned with
`CUDA_VISIBLE_DEVICES`.

> Models below were researched **2026-06-13** (past this doc author's training
> cutoff). Vendor/agentic benchmark figures for the newest models are largely
> unverified secondary claims — treat as directional, and confirm the model, its
> license, and vLLM tool-parser support on your exact build before committing.

### 6.1 Agent LLM — on the 96 GB Blackwell (GPU 1)

Priorities: (1) reliable multi-step tool calling, (2) reasoning, (3) ≥32k (ideally
128k) context. Fits = weights + KV on the one 96 GB card.

| Pick | Model | Type / params | Fit on 96 GB | Ctx | vLLM parser | License |
|---|---|---|---|---|---|---|
| **Primary** | **gpt-oss-120b** | MoE 117B / 5.1B act | native MXFP4 ~63 GB | 131k | `openai` | Apache 2.0 |
| Safest tool-caller | GLM-4.5-Air | MoE 106B / 12B act | 4-bit ~55 GB | 131k | `glm45` (+`--reasoning-parser glm45`) | MIT |
| Best dense fit | Qwen3.6-27B | dense 27B | FP8 ~27 GB / BF16 ~54 GB | 262k | `qwen3_coder`/`qwen3_xml` | Apache 2.0 |
| Fast dev | gpt-oss-20b | MoE 21B / 3.6B act | native MXFP4 ~14 GB | 131k | `openai` | Apache 2.0 |

**Primary = gpt-oss-120b:** best reasoning that *fits one card*, permissive license,
128k context, and its native MXFP4 checkpoint slots into ~63 GB (no lossy re-quant),
leaving ~33 GB for KV; 5.1B active params keep the ReAct loop snappy. **Validate two
things on our sm_120 build before committing** — these are the real risk, not raw
quality:
1. **MXFP4 kernel maturity on sm_120** (Blackwell workstation) — has been uneven;
   smoke-test that it generates clean tokens on a current vLLM.
2. **Tool-calling on `/v1/chat/completions`** — historically less mature for gpt-oss
   than the Harmony `/v1/responses` path; since reliable multi-step calling is
   priority #1, validate multi-step **and** parallel tool calls on our harness.
   Run it with `Reasoning: low`/`medium` (it's a thinking model) in the agent loop.

**If those caveats bite → GLM-4.5-Air** (4-bit): the lowest-risk tool-caller here —
agent-tuned, with a mature dedicated `glm45` parser (the GLM-4.5 family led BFCL-v3).
**Or Qwen3.6-27B** if you want a dense model that fits at full BF16 with the biggest
context — but its vLLM tool parser has a documented fragility history on long
multi-step runs (test `qwen3_coder` vs the newer `qwen3_xml`).

**vLLM launch (primary):**
```
vllm serve openai/gpt-oss-120b --served-model-name gpt-oss-120b \
  --max-model-len 131072 --enable-auto-tool-choice --tool-call-parser openai \
  --gpu-memory-utilization 0.92 --port 8000
# MXFP4 is the native format — do NOT pass --quantization. If "No available memory
# for cache blocks": lower --max-model-len / --max-num-seqs.
```

**Won't fit even at 4-bit (rule out for one card):** DeepSeek-V3.x, GLM-4.6/4.7
(355B), Qwen3-235B / Qwen3.5-397B, Kimi K2, Llama 4 Maverick.

### 6.2 Optional report-writer — on the 48 GB A6000 (GPU 0)

A clean two-model topology this enables: the **agent** (Blackwell) searches and
gathers evidence; a separate **report-writer** (A6000) synthesizes the final cited
answer from the gathered bundle — no tool calling, just faithful grounded synthesis.
Recommended: **Gemma 4 31B-it** (dense, 4-bit/QAT-int4 ~17 GB, Apache 2.0, 256k ctx,
native system role) as its own vLLM instance on GPU 0; alternatives **Qwen3.6-27B**
(family consistency) or **GLM-4.7-Flash** (MLA → very cheap KV for huge bundles).
Ampere has no FP8/FP4, so use 4-bit there. This is **additive** — the agent works
standalone; the writer is an upgrade for long, well-formatted reports.

## 7. Testing & acceptance (summary)

- CLI: `get_document` (found / not-found / subset-guard); `--describe` JSON shape;
  `result_count`/`truncated`; `count_matches`. Keep
  `bazel test //test:tests //test:hazel_test //test:jsonl_test` green.
- Agent: stub-LLM loop test (deterministic); manual real-model smoke (uncommitted).

## 8. Out of scope / future

- **The server.** Once this action schema is settled, a REST/MCP server reuses it
  verbatim (open the burrow once, answer over a socket; same JSON contract). The
  per-process CLI cost (reloading the `.idx` dictionary, cold posting cache) is
  exactly what the server removes — but only after the API is right here.
- Ranking-model changes, multi-burrow federation, and auth are all out of scope.

## 9. Decisions

1. ~~Example app placement~~ — **resolved:** Python under `examples/agent/` (the
   `*.py`/`*.sh` `.gitignore` rules were removed).
2. ~~`count_matches`~~ — **resolved: build it** (§3.3).
3. ~~`truncated` semantics~~ — **resolved (§3.2):** cheap heuristic
   `truncated = result_count == top_k` on every search; exact number via
   `count_matches` on demand.
4. ~~Model~~ — **resolved** (§6): two heterogeneous GPUs; agent LLM
   **gpt-oss-120b** on the 96 GB Blackwell (validate sm_120 MXFP4 + chat-completions
   tool calling; fall back to GLM-4.5-Air), optional report-writer on the 48 GB
   A6000.
