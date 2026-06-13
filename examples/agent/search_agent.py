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
import subprocess
import sys

DEFAULT_SYSTEM = """\
You are a search agent over a document corpus. Answer the user's question using \
ONLY the search tools; do not rely on prior knowledge.

How to work:
- Start broad with search_text. If results look off, use explain to check whether \
a key term is rare or zero-hit, then refine.
- Escalate to search_gcl for precision (both-of, either-of, phrase/proximity, \
"rows containing X"). Use count_matches to gauge how selective a query is.
- Set stem=true when you want morphological recall (run/running); leave it off \
for exact matching.
- Before answering, use get_document to read the full text of the row(s) you will \
rely on.
- When you have enough evidence, STOP calling tools and write a concise final \
answer that cites the docids you used, e.g. "... [shard_00057_0]".
"""

# Tool names that return documents/results we can harvest docids from.
_RESULT_TOOLS = {"search_text", "search_gcl"}


def _shrink(obj, cap):
    """Truncate long string values so observations don't blow the context."""
    if isinstance(obj, str):
        return obj if len(obj) <= cap else obj[:cap] + "…[truncated]"
    if isinstance(obj, list):
        return [_shrink(x, cap) for x in obj]
    if isinstance(obj, dict):
        return {k: _shrink(v, cap) for k, v in obj.items()}
    return obj


def _harvest_citations(name, obs, into):
    """Collect docids seen in a tool observation."""
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
    citations = set()

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
                    "citations": sorted(citations), "messages": messages}

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
            _harvest_citations(name, obs, citations)
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(_shrink(obs, obs_char_cap)),
            })

    return {"answer": None, "stopped": "budget", "steps": max_steps,
            "tool_calls": tool_calls_made, "citations": sorted(citations),
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
        print(f"[stopped: step budget ({args.max_steps}) exhausted]",
              file=sys.stderr)
    print(result["answer"] or "(no answer)")
    if result["citations"]:
        print("\nsources: " + ", ".join(result["citations"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
