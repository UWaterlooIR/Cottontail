"""Shared helpers for the multitext-dsl-2 scouts (TASK-26).

Reuses the patterns of ../multitext-dsl/run.py: TREC-4 topic loading, the
mt-compile validity oracle, and the vLLM client. New here: tool-call emission
(mirroring isj BaseSearcher.propose: tools + tool_choice="required",
non-streaming) and a live tiered_query_search runner against the dev server.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import openai

HERE = Path(__file__).parent
REPO = HERE.resolve().parents[2]  # multitext-dsl-2 -> scouting -> isj -> <repo>

MT_COMPILE = REPO / "bazel-bin" / "apps" / "mt-compile"
TOPICS_FILE = REPO / "docs" / "trec4" / "topics.201-250"

# The same 10-topic spread as the original scout (208 is the worked example).
DEFAULT_TOPICS = [203, 207, 211, 214, 220, 224, 229, 238, 244, 249]

TOOL = {
    "type": "function",
    "function": {
        "name": "submit_tiered_query",
        "description": (
            "Submit your MultiText program: the facet/tier macro definitions "
            "(one per line, `name = expr`) followed by a single `@rank` line "
            "listing the tier macros in precise->broad order."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "program": {
                    "type": "string",
                    "description": (
                        "The full program text: macro definitions, one per line, "
                        "then one @rank line."
                    ),
                }
            },
            "required": ["program"],
        },
    },
}


def load_topics() -> dict[int, str]:
    """{num: plain single-statement need} with the TREC markup stripped."""
    text = TOPICS_FILE.read_text(encoding="utf-8", errors="replace")
    out = {}
    for m in re.finditer(r"<top>(.*?)</top>", text, re.S):
        block = m.group(1)
        num = re.search(r"<num>\s*Number:\s*(\d+)", block)
        desc = re.search(r"<desc>\s*Description:\s*(.*)", block, re.S)
        if num and desc:
            out[int(num.group(1))] = re.sub(r"\s+", " ", desc.group(1)).strip()
    return out


def compile_program(program: str) -> dict:
    """Run mt-compile over `program`; parse its per-statement report."""
    p = subprocess.run(
        [str(MT_COMPILE)], input=program, capture_output=True, text=True
    )
    lines = p.stdout.splitlines()
    errors = [l.split("\t", 2)[-1] for l in lines if "\tERR\t" in l]
    tiers = [l.split("\t", 3)[-1] for l in lines if l.startswith("TIER\tOK")]
    m = re.search(r"statements=(\d+) errors=(\d+)", p.stdout)
    return {
        "compiled": p.returncode == 0 and m is not None and m.group(2) == "0",
        "statements": int(m.group(1)) if m else 0,
        "errors": int(m.group(2)) if m else len(errors),
        "n_macros": sum(1 for l in lines if l.startswith("DEF\tOK")),
        "n_tiers": len(tiers),
        "error_messages": errors,
        "tier_s_expressions": tiers,
    }


def make_client(base_url: str = "http://127.0.0.1:8000/v1",
                timeout: float = 240.0) -> openai.OpenAI:
    return openai.OpenAI(base_url=base_url, api_key="EMPTY", timeout=timeout,
                         max_retries=0)


def propose_toolcall(
    client: openai.OpenAI,
    model: str,
    messages: list[dict],
    *,
    effort: str = "medium",
    temperature: float = 0.0,
) -> dict:
    """One non-streaming round-trip with the submit_tiered_query tool required —
    the exact emission path of isj BaseSearcher.propose. Returns a record with
    the raw assistant message plus extracted program (or the failure class):

      emit:    "tool_call" | "content_only" | "no_output" | "bad_json" | "no_program_key"
      program: the program text when extractable (from the tool args), else None
      content: assistant content channel (should be empty in tool mode)
    """
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=[TOOL],
        tool_choice="required",
        temperature=temperature,
        extra_body={"reasoning_effort": effort},
    )
    choice = response.choices[0]
    message = choice.message
    usage = getattr(response, "usage", None)
    rec: dict = {
        "finish_reason": getattr(choice, "finish_reason", None),
        "usage": usage.model_dump() if usage is not None else None,
        "reasoning": getattr(message, "reasoning_content", None)
        or getattr(message, "reasoning", None),
        "content": message.content,
        "n_tool_calls": len(message.tool_calls or []),
        "program": None,
    }
    calls = message.tool_calls or []
    if not calls:
        rec["emit"] = "content_only" if (message.content or "").strip() else "no_output"
        return rec
    call = calls[0]
    rec["tool_name"] = call.function.name
    rec["raw_arguments"] = call.function.arguments
    rec["assistant_message"] = {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [{
            "id": call.id,
            "type": "function",
            "function": {"name": call.function.name,
                         "arguments": call.function.arguments},
        }],
    }
    rec["tool_call_id"] = call.id
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError as e:
        rec["emit"] = "bad_json"
        rec["json_error"] = str(e)
        return rec
    program = args.get("program")
    if not isinstance(program, str) or not program.strip():
        rec["emit"] = "no_program_key"
        rec["args_keys"] = sorted(args)
        return rec
    rec["emit"] = "tool_call"
    rec["program"] = program
    rec["program_lines"] = program.count("\n") + 1
    return rec
