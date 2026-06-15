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
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request

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


def _render_json(obj, indent=6):
    """Full, pretty-printed JSON rendering of any value (a tool observation, the
    request messages, the LLM response payload), wrapped to the terminal width for
    readable display. Nothing is truncated. Each output line is prefixed with
    `indent` spaces and over-long lines (long passages/bodies/prompts) are
    word-wrapped with a hanging indent so the structure stays readable."""
    width = max(40, shutil.get_terminal_size().columns)
    pad = " " * indent
    out = []
    for line in json.dumps(obj, indent=2, ensure_ascii=False).splitlines():
        if indent + len(line) <= width:
            out.append(pad + line)
            continue
        stripped = line.lstrip(" ")
        lead = len(line) - len(stripped)
        out.extend(textwrap.wrap(
            stripped, width=width,
            initial_indent=pad + " " * lead,
            subsequent_indent=pad + " " * (lead + 2),
            break_long_words=True, break_on_hyphens=False) or [pad + line])
    return "\n".join(out)


def _response_payload(resp):
    """The LLM's reply as a plain JSON-able dict — content, any tool calls (with
    their raw arguments), and the finish reason — so the verbose trace can show
    exactly what came back. Tolerant of stub/minimal responses."""
    choice = resp.choices[0]
    msg = choice.message
    out = {"finish_reason": getattr(choice, "finish_reason", None),
           "content": getattr(msg, "content", None)}
    calls = getattr(msg, "tool_calls", None) or []
    if calls:
        out["tool_calls"] = [
            {"id": tc.id, "name": tc.function.name,
             "arguments": tc.function.arguments} for tc in calls]
    return out


def _harvest_seen(name, obs, into):
    """Record docids that appeared in a tool observation (search hits / reads)."""
    if name in _RESULT_TOOLS:
        for r in obs.get("results", []) or []:
            if isinstance(r, dict) and r.get("docid"):
                into.add(r["docid"])
    elif name == "get_document" and obs.get("found") and obs.get("docid"):
        into.add(obs["docid"])


def _http_request(url, token, payload=None):
    """GET (payload=None) or POST a JSON request; return the parsed body, or a
    parsed {error,...} body on an HTTP/connection error."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode() if payload is not None else None
    method = "POST" if payload is not None else "GET"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:  # server sends a JSON error body
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": f"HTTP {e.code}", "where": "server"}
    except urllib.error.URLError as e:
        return {"error": f"connection failed: {e.reason}", "where": "server"}


class SearchTools:
    """Loads the tool schema from, and executes tool calls against, either the
    CLI binary (subprocess) or a running cottontail-jsonl-server (HTTP). The two
    transports share the identical JSON contract, so the rest of the agent is
    unaffected by the choice."""

    def __init__(self, query_bin=None, burrow=None, server_url=None, token=None):
        self.query_bin = query_bin
        self.burrow = burrow
        self.server_url = server_url.rstrip("/") if server_url else None
        self.token = token

    def schema(self):
        if self.server_url:
            return _http_request(f"{self.server_url}/describe", self.token)
        out = subprocess.run(
            [self.query_bin, "--describe"], capture_output=True, text=True
        )
        if out.returncode != 0:
            raise RuntimeError(f"--describe failed: {out.stderr.strip()}")
        return json.loads(out.stdout)

    def call(self, name, args):
        if self.server_url:  # HTTP transport: POST /tools/<name> with the args
            return _http_request(f"{self.server_url}/tools/{name}", self.token, args)
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


def _llm_summary(resp, t0):
    """One-line summary of an LLM round-trip for the verbose trace: round-trip
    latency, finish reason, tool-call count, and token usage when the server
    reports it. Tolerant of stub/minimal responses (missing finish/usage)."""
    parts = [f"{(time.monotonic() - t0) * 1000:.0f}ms"]
    choice = resp.choices[0]
    finish = getattr(choice, "finish_reason", None)
    if finish:
        parts.append(f"finish={finish}")
    calls = getattr(choice.message, "tool_calls", None) or []
    parts.append(f"{len(calls)} tool call(s)")
    usage = getattr(resp, "usage", None)
    pt = getattr(usage, "prompt_tokens", None)
    ct = getattr(usage, "completion_tokens", None)
    if pt is not None and ct is not None:
        parts.append(f"tokens {pt}+{ct}")
    return ", ".join(parts)


def run_agent(client, model, tools, call_tool, question, *,
              system=DEFAULT_SYSTEM, max_steps=8,
              reasoning="low", temperature=0.0, verbose=False):
    """Run the ReAct loop. Returns a result dict.

    client      : OpenAI-compatible client (`client.chat.completions.create`).
    tools       : tool schema list (from SearchTools.schema()).
    call_tool   : fn(name: str, args: dict) -> dict observation.
    verbose     : if set, stream a live transcript (assistant text, tool calls,
                  and observations) to stderr as each step happens.
    """
    def _emit(line):
        if verbose:
            print(line, file=sys.stderr, flush=True)

    sys_content = (f"Reasoning: {reasoning}\n\n{system}" if reasoning else system)
    messages = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": question},
    ]
    tool_calls_made = []
    seen = set()  # every docid the tools surfaced; cited subset chosen at the end

    for step in range(max_steps):
        _emit(f"\n── step {step + 1}/{max_steps} ──")
        _emit(f"  → LLM request: model={model}, {len(messages)} messages")
        _emit(_render_json(messages))
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=tools,
            tool_choice="auto", temperature=temperature,
        )
        _emit(f"  ← LLM response: {_llm_summary(resp, t0)}")
        _emit(_render_json(_response_payload(resp)))
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        if msg.content and msg.content.strip():
            _emit(f"  assistant: {msg.content.strip()}")
        if not calls:
            _emit("  (no tool calls — final answer)")
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
            _emit(f"  → {name}({json.dumps(cargs)})")
            obs = call_tool(name, cargs)
            _harvest_seen(name, obs, seen)
            _emit("    ↳")
            _emit(_render_json(obs))
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(obs),
            })

    # Budget spent: one final turn with no tools to force a best-effort answer
    # (or an explicit "not in the corpus") rather than returning nothing.
    _emit(f"\n[step budget ({max_steps}) spent — forcing a final answer]")
    messages.append({"role": "user", "content": WRAP_UP})
    _emit(f"  → LLM request (final): model={model}, {len(messages)} messages")
    _emit(_render_json(messages))
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature,
    )
    _emit(f"  ← LLM response: {_llm_summary(resp, t0)}")
    _emit(_render_json(_response_payload(resp)))
    answer = resp.choices[0].message.content
    return {"answer": answer, "stopped": "budget", "steps": max_steps,
            "tool_calls": tool_calls_made, "citations": _cited(answer, seen),
            "messages": messages}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--question", required=True)
    # Search transport: either a running server (--server-url) or the CLI binary.
    ap.add_argument("--server-url",
                    help="cottontail-jsonl-server base URL (HTTP transport); "
                         "token read from env COTTONTAIL_API_TOKEN")
    ap.add_argument("--burrow", help="burrow path (subprocess transport)")
    ap.add_argument("--query-bin", default="cottontail-jsonl-query",
                    help="path to the cottontail-jsonl-query binary (subprocess)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1",
                    help="vLLM OpenAI-compatible base URL (the LLM, not search)")
    ap.add_argument("--model", default="gpt-oss-120b",
                    help="must match vLLM --served-model-name")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--reasoning", default="low",
                    help="gpt-oss reasoning effort (low|medium|high; '' to omit)")
    ap.add_argument("--trace", action="store_true",
                    help="print the tool-call summary to stderr after the run")
    ap.add_argument("--verbose", action="store_true",
                    help="stream a live transcript (assistant text, tool calls, "
                         "and observations) to stderr as the loop runs")
    args = ap.parse_args(argv)

    if args.server_url:
        # Token via env, never a flag (it would show in /proc/<pid>/cmdline).
        tools = SearchTools(server_url=args.server_url,
                            token=os.environ.get("COTTONTAIL_API_TOKEN"))
    elif args.burrow:
        tools = SearchTools(query_bin=args.query_bin, burrow=args.burrow)
    else:
        ap.error("supply --server-url (HTTP) or --burrow (subprocess)")

    from openai import OpenAI  # lazy: tests import this module without openai

    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    schema = tools.schema()
    result = run_agent(client, args.model, schema, tools.call, args.question,
                       max_steps=args.max_steps, reasoning=args.reasoning,
                       verbose=args.verbose)

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
