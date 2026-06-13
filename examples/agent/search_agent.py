#!/usr/bin/env python3
"""A minimal ReAct search agent over a Cottontail burrow.

The LLM (served by vLLM behind an OpenAI-compatible endpoint) is given the
cottontail-jsonl-query tools via native function calling, and loops:
  user question -> tool call(s) -> observations -> ... -> final answer.

Tools come straight from `cottontail-jsonl-query --describe`, and each tool call
is executed by shelling out to that same binary. See
docs/cottontail-search-agent-spec.md.

This is an *example*, not production. The core loop (`run_agent`) takes the LLM
client and the tool-executor as arguments, so it can be unit-tested with stubs
(see test_agent.py) without a GPU.
"""

import argparse
import json
import re
import subprocess
import sys

DEFAULT_SYSTEM = """\
You are a search agent over a document corpus. Answer the user's question using \
ONLY what you retrieve with the tools; do not rely on prior knowledge.

These are LEXICAL tools — keyword and proximity matching over exact words, NOT a \
semantic search box. This changes how you must query:
- Query with the DISTINCTIVE CONTENT WORDS only. Strip stopwords and meta-phrasing: \
"I am looking for scientific facts about elephants" should just be `elephants`. \
Extra common words (looking, facts, about, the) DILUTE the ranking and make \
results WORSE, not broader.
- Counter-intuitive but important: FEWER words = BROADER results; MORE words = \
NARROWER and noisier. To broaden, drop words (often down to a single keyword). To \
narrow, ADD a distinctive word or switch to search_gcl.

Strategy — go broad first, then hone:
1. Start with the one or two most salient keywords to see what the corpus actually \
contains (e.g. `elephants`). Skim the snippets.
2. THEN add precision: more specific terms, or search_gcl operators — (^ a b) both \
terms, (... a b) a-near-b in order, (+ a b) either, (>> :item (^ a b)) rows \
containing both. e.g. (^ elephant conservation) or (... elephant population decline).
Iterate broad → specific. Do NOT make small tweaks to a long natural-language query.

- Use explain (term doc-frequency) and count_matches (how many rows match) to tell \
whether a term is too rare or too common, and adjust.
- stem=true broadens recall (elephant matches elephants). search_text ignores \
quotation marks — use search_gcl for exact phrases or proximity.
- Don't re-search the same intent repeatedly. After a couple of searches, read the \
most promising hit with get_document or answer from what you have. Read a document \
before you cite it.
- The corpus may simply not contain the answer. If so, say that plainly rather \
than guessing.

Finish: when you have enough evidence (or have concluded the corpus lacks it), \
STOP calling tools and write a concise final answer, citing the docids you relied \
on in square brackets, e.g. "... [shard_00057_0]".
"""

# Sent as a final user turn when the step budget is spent, to force a best-effort
# answer instead of returning nothing.
WRAP_UP = (
    "You have used your search budget. Do not call any more tools. Answer the "
    "question using ONLY the evidence gathered above; if the corpus does not "
    "contain the answer, say so plainly. Cite the docids you relied on in square "
    "brackets."
)

# Tool names that return documents/results we can harvest docids from.
_RESULT_TOOLS = {"search_text", "search_gcl"}


def _cited(answer, seen):
    """Of the docids actually seen, return those the final answer cites.

    Matches each seen docid as a whole token in the answer (so a docid is not a
    spurious substring of a longer one), so "sources" reflects what the model
    cited, not everything the searches surfaced.
    """
    if not answer:
        return []
    return sorted(d for d in seen
                  if re.search(r"(?<![\w-])" + re.escape(d) + r"(?![\w-])", answer))


def _shrink(obj, cap):
    """Truncate long string values so observations don't blow the context."""
    if isinstance(obj, str):
        return obj if len(obj) <= cap else obj[:cap] + "…[truncated]"
    if isinstance(obj, list):
        return [_shrink(x, cap) for x in obj]
    if isinstance(obj, dict):
        return {k: _shrink(v, cap) for k, v in obj.items()}
    return obj


def _harvest_seen(name, obs, into):
    """Record docids that appeared in a tool observation (search hits / reads)."""
    if name in _RESULT_TOOLS:
        for r in obs.get("results", []) or []:
            if isinstance(r, dict) and r.get("docid"):
                into.add(r["docid"])
    elif name == "get_document" and obs.get("found") and obs.get("docid"):
        into.add(obs["docid"])


class SearchTools:
    """Loads the tool schema from, and executes tool calls against, the CLI."""

    def __init__(self, query_bin, burrow):
        self.query_bin = query_bin
        self.burrow = burrow

    def schema(self):
        out = subprocess.run(
            [self.query_bin, "--describe"], capture_output=True, text=True
        )
        if out.returncode != 0:
            raise RuntimeError(f"--describe failed: {out.stderr.strip()}")
        return json.loads(out.stdout)

    def call(self, name, args):
        b = ["--burrow", self.burrow]
        fmt = ["--format", "jsonl"]

        def common(cmd):
            if args.get("top_k"):
                cmd += ["--top-k", str(int(args["top_k"]))]
            if args.get("stem"):
                cmd += ["--stem"]
            if args.get("full_text"):
                cmd += ["--full-text"]
            return cmd

        if name == "search_text":
            cmd = common(b + ["--text", str(args["query"])]) + fmt
        elif name == "search_gcl":
            cmd = common(b + ["--gcl", str(args["query"])]) + fmt
        elif name == "explain":
            flag = "--gcl" if args.get("is_gcl") else "--text"
            cmd = b + ["--explain", flag, str(args["query"])]
            if args.get("stem"):
                cmd += ["--stem"]
        elif name == "get_document":
            cmd = b + ["--get", str(args["docid"])] + fmt
        elif name == "count_matches":
            flag = "--gcl" if args.get("is_gcl") else "--text"
            cmd = b + ["--count", flag, str(args["query"])] + fmt
            if args.get("stem"):
                cmd += ["--stem"]
        else:
            return {"error": f"unknown tool: {name}"}

        out = subprocess.run([self.query_bin] + cmd, capture_output=True, text=True)
        if out.returncode != 0:
            try:
                return json.loads(out.stderr)  # {"error","where"}
            except json.JSONDecodeError:
                return {"error": out.stderr.strip() or "tool failed",
                        "exit_code": out.returncode}
        return json.loads(out.stdout)


def run_agent(client, model, tools, call_tool, question, *,
              system=DEFAULT_SYSTEM, max_steps=8, obs_char_cap=2000,
              reasoning="low", temperature=0.0):
    """Run the ReAct loop. Returns a result dict.

    client      : OpenAI-compatible client (`client.chat.completions.create`).
    tools       : tool schema list (from SearchTools.schema()).
    call_tool   : fn(name: str, args: dict) -> dict observation.
    """
    sys_content = (f"Reasoning: {reasoning}\n\n{system}" if reasoning else system)
    messages = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": question},
    ]
    tool_calls_made = []
    seen = set()  # every docid the tools surfaced; cited subset chosen at the end

    for step in range(max_steps):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=tools,
            tool_choice="auto", temperature=temperature,
        )
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        if not calls:
            return {"answer": msg.content, "stopped": "answer",
                    "steps": step, "tool_calls": tool_calls_made,
                    "citations": _cited(msg.content, seen), "messages": messages}

        # Echo the assistant's tool-call message back into the history.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in calls
            ],
        })
        for tc in calls:
            name = tc.function.name
            try:
                cargs = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                cargs = {}
            tool_calls_made.append((name, cargs))
            obs = call_tool(name, cargs)
            _harvest_seen(name, obs, seen)
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(_shrink(obs, obs_char_cap)),
            })

    # Budget spent: one final turn with no tools to force a best-effort answer
    # (or an explicit "not in the corpus") rather than returning nothing.
    messages.append({"role": "user", "content": WRAP_UP})
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature,
    )
    answer = resp.choices[0].message.content
    return {"answer": answer, "stopped": "budget", "steps": max_steps,
            "tool_calls": tool_calls_made, "citations": _cited(answer, seen),
            "messages": messages}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--burrow", required=True, help="Cottontail burrow path")
    ap.add_argument("--question", required=True)
    ap.add_argument("--query-bin", default="cottontail-jsonl-query",
                    help="path to the cottontail-jsonl-query binary")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="gpt-oss-120b",
                    help="must match vLLM --served-model-name")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--reasoning", default="low",
                    help="gpt-oss reasoning effort (low|medium|high; '' to omit)")
    ap.add_argument("--trace", action="store_true",
                    help="print the tool-call trace to stderr")
    args = ap.parse_args(argv)

    from openai import OpenAI  # lazy: tests import this module without openai

    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    tools = SearchTools(args.query_bin, args.burrow)
    schema = tools.schema()
    result = run_agent(client, args.model, schema, tools.call, args.question,
                       max_steps=args.max_steps, reasoning=args.reasoning)

    if args.trace:
        for name, cargs in result["tool_calls"]:
            print(f"  → {name}({json.dumps(cargs)})", file=sys.stderr)
    if result["stopped"] == "budget":
        print(f"[step budget ({args.max_steps}) spent; answered from evidence "
              f"gathered so far]", file=sys.stderr)
    print(result["answer"] or "(no answer)")
    if result["citations"]:
        print("\nsources: " + ", ".join(result["citations"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
