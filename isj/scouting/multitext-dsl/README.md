# MultiText-DSL scouting — can gpt-oss-120b write valid MultiText queries?

**Idea (from the ChatGPT demo):** the TREC-4 MultiText DSL keeps tokens (quoted) and macros
(bare `name = expr`) in separate namespaces, LLMs are fluent in it, and **Cottontail already
compiles it** — `src/mt.cc` (`Mt::infix_expression`) parses the exact syntax (`+`, `^`, `<>`,
`< [N]`, quoted tokens, `name = expr` macros) and emits Cottontail GCL, with a bool+error for
validity. So instead of a JSON tool schema, we let the model write the **program** and compile it.

**This experiment measures:** does gpt-oss-120b (weaker than ChatGPT) produce **valid, compilable**
MultiText, and are its mistakes the kind a compiler-error bounce would fix?

## Pieces

- `apps/mt-compile.cc` (`//apps:mt-compile`) — the validity oracle: reads a program on stdin,
  compiles each statement via `Mt`, prints `DEF/TIER OK|ERR + s-expression|error`, exit 0 iff clean.
  Warren-free (pure compile). Verified on the ChatGPT topic-201 program: 31 statements, 0 errors.
- `librarian-prompt.md` — role + a short DSL primer + the worked topic-208 example (verbatim).
- `run.py` — per topic: prompt gpt-oss with a `submit_tiered_query(program)` tool, feed the
  emitted program to `mt-compile`, record compiled?/#macros/#tiers/errors/tier s-expressions.
- Topics: a spread of TREC-4 topics (`docs/trec4/topics.201-250`), excluding 208 (the example).

## Run (vLLM up; build the compiler first)

```sh
bazel build -c dbg --cxxopt="-Og" //apps:mt-compile
uv run --directory isj python scouting/multitext-dsl/run.py            # the spread
uv run --directory isj python scouting/multitext-dsl/run.py --topics 214,224   # subset
```

Fail-fast (0 retries, 180 s). Records append to `results/records.jsonl` (resumable).

## Read-out

- **Compile rate** — programs that compile with 0 errors on the first try.
- **Error taxonomy** — what fails (undefined macro, bad operator, malformed `@rank`) and whether
  a one-line compiler error would let the model self-correct.
- **Shape** — #macros, #tiers, and the compiled GCL (does it look like a sensible precise->broad
  ladder, and is it free of the JSON-tool over-enumeration/runaway?).
