"""Scout a tool-using LLM against the Searcher loop, with a canned engine.

This is a *probe*, not part of the `isj_agent` package and not a test: it makes
live network calls to a vLLM (or any OpenAI-compatible) endpoint and reports how a
given model behaves in the Interactive-Searching-and-Judging loop we are designing
for the Searcher. It runs the validated "current working scout":

  - the `word*` family-marker prompt + Charlie's facet-cover query shape,
  - a four-call loop (search -> judge[batch]) with one tool call per turn,
  - the loop-controller guardrails (valid-GCL gate, judge-before-search, and a
    model-agnostic termination: stop-on-dry + no-progress break + budget cap),
  - against a tiny canned "black bear attacks" corpus,

and prints an instrumented report. See docs/searcher-agent-lessons-June-16-2026.md
for the full rationale and the per-model findings this script produced
(gpt-oss-120b, Qwen3.6-27B, gemma-4-31B).

Usage (from the repo root):
    uv run --directory isj python scouting/scout_searcher.py --model gpt.oss.120b
    uv run --directory isj python scouting/scout_searcher.py --model Qwen3.6.27B \
        --base-url http://127.0.0.1:8000/v1
"""

from __future__ import annotations

import argparse
import json
import re

from openai import OpenAI

# --- the validated system prompt (docs/searcher-agent-lessons §3) ----------------

SYSTEM_PROMPT = (
    "You are a search analyst exploring a large text collection to answer ONE question.\n"
    "You find the passages relevant to it and grade each 0-3.\n\n"
    "Write queries in GCL, a Boolean cover language. Use PREFIX form ONLY — never infix,\n"
    "never the words AND/OR/NOT.\n"
    "  (^ A B C)  all of A,B,C appear together\n"
    "  (+ A B C)  any of A,B,C\n"
    '  "a b c"    the exact phrase\n'
    "  (!> A B)   an A that does NOT contain B  (carve out a false sense you have READ)\n\n"
    "Three ways to write a term:\n"
    "  black      a bare word matches EXACTLY — use for proper nouns and the question's\n"
    "             defining words.\n"
    "  bear*      a word followed by * matches that word AND its whole family (bear/bears,\n"
    "             attack/attacked/attacking). Write the FULL ordinary word then * — e.g.\n"
    "             statistics*, injury* — NEVER a shortened stem. The system expands it.\n"
    "             Use it for ordinary content words (not proper nouns/defining terms).\n"
    "  (+ X Y Z)  is for SYNONYMS — distinct words for one concept — NOT inflections of one word.\n\n"
    "Build each query as a COVER: one facet per concept, AND-ed with ^. Example for\n"
    "'Do I need to worry about black bear attacks while hiking in the woods?':\n"
    "  (^ black bear* attack*)\n"
    "Broaden a facet by SYNONYM, e.g. (+ attack* maul* encounter*) — never by adding plurals.\n\n"
    "Loop, ONE tool call per turn:\n"
    "1. `search` a GCL query.\n"
    "2. JUDGE every returned passage (one `judge` call) before searching again.\n"
    "3. Reformulate using words learned from passages.\n"
    "4. `search` reports total_matches; if it returns 0 or only grade-0 passages the query\n"
    "   is DRY. After at most 2 dry searches in a row, STOP.\n"
    "5. At most {max_searches} searches. When done, STOP: no tool call, output nothing."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Run a GCL query; returns unjudged passages and total_matches.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "judge",
            "description": "Record relevance judgements for the passages you just read.",
            "parameters": {
                "type": "object",
                "properties": {
                    "judgements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "docid": {"type": "string"},
                                "grade": {"type": "integer", "enum": [0, 1, 2, 3]},
                                "reason": {"type": "string"},
                            },
                            "required": ["docid", "grade", "reason"],
                        },
                    }
                },
                "required": ["judgements"],
            },
        },
    },
]

# --- GCL validation + report helpers --------------------------------------------

_OPS = {"^", "+", "<>", "...", "<<", ">>", "!>", "!<", "#"}


def validate_gcl(q: str) -> str | None:
    """Return an error string if `q` is not a single well-formed prefix-GCL
    expression, else None. (A lightweight stand-in for SExpression::from_string.)"""
    masked = re.sub(r'"[^"]*"', "PHRASE", q)
    if masked.count("(") != masked.count(")"):
        return "unbalanced parentheses"
    for t in re.findall(r"[^\s()]+", masked):
        if t in ("AND", "OR", "NOT"):
            return f"keyword '{t}' not allowed"
    for m in re.finditer(r"\(\s*([^\s()]+)", masked):
        if m.group(1) not in _OPS:
            return f"'(' must be followed by an operator; found '{m.group(1)}'"
    s = masked.strip()
    if s.startswith("("):
        depth = 0
        end = -1
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != len(s) - 1:
            return "must be ONE GCL expression"
    return None


def _plus_groups(q: str) -> list[list[str]]:
    """Return the operand-token lists of each (+ ...) group in `q`."""
    groups = []
    i = 0
    while True:
        idx = q.find("(+", i)
        if idx < 0:
            break
        depth = 0
        j = idx
        while j < len(q):
            if q[j] == "(":
                depth += 1
            elif q[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        groups.append([t for t in re.findall(r"[^\s()]+", q[idx + 2 : j]) if t not in _OPS])
        i = j + 1
    return groups


def _is_inflection(a: str, b: str) -> bool:
    """Heuristic: do `a` and `b` look like inflections of one word (e.g. bear/bears)?
    Used to flag hand-enumerated inflections, which `word*` should make unnecessary."""
    a, b = a.rstrip("*"), b.rstrip("*")
    x, y = sorted([a, b], key=len)
    return y != x and y.startswith(x) and y[len(x) :] in ("s", "es", "ed", "d", "ing", "r", "rs")


# --- canned engine ---------------------------------------------------------------

# (total_matches, passages) per successive search; later searches go dry so the loop
# must terminate. Topic: "risk of black bear attacks while hiking in forests."
_BATCHES = [
    (50, [
        {"docid": "b1", "text": "Black bear attacks on humans are rare; most encounters end without injury."},
        {"docid": "b2", "text": "Grizzly bear attacks are far more dangerous than black bear encounters."},
        {"docid": "b3", "text": "Bear-resistant food containers are required at many campsites."},
    ]),
    (15, [
        {"docid": "b4", "text": "Hikers cut black bear attack risk by making noise and carrying bear spray."},
        {"docid": "b5", "text": "A black bear was spotted near the trailhead parking lot."},
    ]),
    (4, [
        {"docid": "b6", "text": "Fatal black bear maulings average roughly one per year across North America."},
    ]),
    (0, []), (0, []), (0, []), (0, []), (0, []),
]

INTENT = "assess the risk of black bear attacks on people hiking in forests"


class CannedEngine:
    """Returns the next canned batch per search, excluding already-judged docids."""

    def __init__(self) -> None:
        self._i = 0
        self.accepted_searches = 0

    def search(self, judged: set[str]) -> dict:
        tm, batch = _BATCHES[min(self._i, len(_BATCHES) - 1)]
        self._i += 1
        self.accepted_searches += 1
        fresh = [p for p in batch if p["docid"] not in judged]
        note = (
            "no matches — broaden or stop"
            if tm == 0
            else ("no NEW passages" if not fresh else "")
        )
        return {"total_matches": tm, "results": fresh, "note": note}


# --- the scout loop --------------------------------------------------------------


def run_scout(client: OpenAI, model: str, max_turns: int, budget: int) -> None:
    system = SYSTEM_PROMPT.format(max_searches=budget)
    msgs: list = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Information need: {INTENT}."},
    ]
    engine = CannedEngine()
    judged: set[str] = set()
    surfaced: set[str] = set()
    pending: list[str] = []
    searches = dry_streak = no_progress = 0
    gcl_reject = prem_reject = porter_leak = infl_enum = multi_call = 0
    star_words: set[str] = set()
    terminated = "HIT turn cap"

    def llm():
        return client.chat.completions.create(
            model=model, messages=msgs, tools=TOOLS, tool_choice="auto", temperature=0
        ).choices[0].message

    for step in range(max_turns):
        if searches >= budget:
            terminated = "HIT search budget"
            break
        m = llm()
        tcs = m.tool_calls or []
        if len(tcs) > 1:
            multi_call += 1
        msgs.append({
            "role": "assistant",
            "content": m.content or "",
            "tool_calls": [
                {"id": t.id, "type": "function",
                 "function": {"name": t.function.name, "arguments": t.function.arguments}}
                for t in tcs
            ],
        })
        if not tcs:
            terminated = f"STOP at turn {step} (no tool call)"
            if (m.content or "").strip():
                terminated += f" [emitted {len(m.content)} chars of prose]"
            break
        print(f"turn {step}: #calls={len(tcs)} -> {[t.function.name for t in tcs]}")
        for t in tcs:
            try:
                args = json.loads(t.function.arguments or "{}")
            except json.JSONDecodeError:
                print(f"          BAD ARGS json: {t.function.arguments!r}")
                args = {}
            if t.function.name == "search":
                q = args.get("query", "")
                if pending:  # GUARDRAIL 1: judge before searching
                    prem_reject += 1
                    print(f"          search REJECTED (judge {pending} first)")
                    res = {"error": f"Judge these first: {pending}"}
                else:
                    err = validate_gcl(q)  # GUARDRAIL 2: valid prefix GCL
                    if err:
                        gcl_reject += 1
                        print(f"          search REJECTED ({err}): q={q}")
                        res = {"error": f"Invalid GCL: {err}. Use prefix form like (^ black bear* attack*)."}
                    else:
                        porter_leak += q.count("porter:")
                        star_words.update(re.findall(r"([A-Za-z][\w-]*)\*", q))
                        infl_enum += sum(
                            1
                            for g in _plus_groups(q)
                            for i in range(len(g))
                            for k in range(i + 1, len(g))
                            if _is_inflection(g[i], g[k])
                        )
                        r = engine.search(judged)
                        pending = [p["docid"] for p in r["results"]]
                        surfaced.update(pending)
                        searches += 1
                        dry_streak = dry_streak + 1 if r["total_matches"] == 0 else 0
                        no_progress = 0
                        print(f"          search OK tm={r['total_matches']} ret={pending}: q={q}")
                        res = r
            elif t.function.name == "judge":
                js = args.get("judgements", [])
                new = [j for j in js if j.get("docid") not in judged]
                for j in new:
                    judged.add(j.get("docid"))
                pending = [d for d in pending if d not in judged]
                no_progress = no_progress + 1 if not new else 0  # empty/dup judge = no progress
                print(f"          judge {[(j.get('docid'), j.get('grade')) for j in js]}")
                res = {"ok": True, "recorded": len(new)}
            else:
                print(f"          UNKNOWN TOOL: {t.function.name}")
                res = {"error": "unknown tool"}
            msgs.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps(res)})
        if dry_streak >= 2:  # GUARDRAIL 3: stop on dryness
            terminated = f"STOP at turn {step} (controller: 2 dry searches)"
            break
        if no_progress >= 2:  # GUARDRAIL 4: model spinning (e.g. Qwen empty judge[])
            terminated = f"STOP at turn {step} (controller: no progress)"
            break

    print(f"\n=== report ({model}) ===")
    print(f"terminated: {terminated} | accepted searches: {engine.accepted_searches}")
    print(f"turns with >1 tool call (parallel): {multi_call}")
    print(f"invalid-GCL rejections: {gcl_reject} | premature-search rejections: {prem_reject}")
    print(f"porter: leakage: {porter_leak} | hand-enumerated inflection pairs: {infl_enum}")
    print(f"starred words used: {sorted(star_words)}")
    print(f"never judged: {sorted(surfaced - judged) or 'none'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Scout a tool-using LLM against the Searcher loop.")
    ap.add_argument("--model", required=True, help="served model name (e.g. gpt.oss.120b)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--max-turns", type=int, default=16, help="hard cap on LLM turns")
    ap.add_argument("--budget", type=int, default=8, help="max accepted searches (prompt + controller)")
    args = ap.parse_args()
    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    run_scout(client, args.model, args.max_turns, args.budget)


if __name__ == "__main__":
    main()
