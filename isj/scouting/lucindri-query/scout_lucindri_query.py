"""Scout: will gpt.oss.120b author valid Lucindri-language queries from the TASK-33 prompt?

Single-turn generation probe. For each TREC-8 need, one LLM round-trip with the
TASK-33 prompt as system, tool_choice=required (force submit_query), reasoning
medium, temperature 0. Capture the raw query, structurally validate it against the
query language, and report shape (facets / proximity / syn placement / filters).

Run (from repo root):
    uv run --directory isj python <abs-path>/scout_lucindri_query.py
"""
from __future__ import annotations
import argparse, json, re, sys
from openai import OpenAI

ALLOWED = {"#combine", "#weight", "#scoreif", "#scoreifnot", "#syn", "#band"}
def _op_ok(op: str) -> bool:
    return op in ALLOWED or bool(re.fullmatch(r"#\d+", op)) or bool(re.fullmatch(r"#uw\d+", op))

def mask_quotes(q: str) -> str:
    return re.sub(r'"(?:\\.|[^"\\])*"', 'Q', q)

def validate(q: str) -> list[str]:
    """Return a list of structural problems ([] == clean)."""
    probs = []
    m = mask_quotes(q)
    if m.count('"'):
        probs.append("unbalanced quotes")
    if m.count("(") != m.count(")"):
        probs.append(f"unbalanced parens ({m.count('(')} vs {m.count(')')})")
    # every operator token known?
    for op in re.findall(r"#[A-Za-z0-9]+", m):
        if not _op_ok(op):
            probs.append(f"unknown operator {op}")
    # '(' must follow an operator token (prefix form): find '(' not preceded by #op
    for mt in re.finditer(r"(#[A-Za-z0-9]+)?\s*\(", m):
        if mt.group(1) is None:
            probs.append("'(' not attached to an operator (bare group)")
            break
    # bare (unquoted) word operands: after masking, any alpha run that is not an
    # operator name is an unquoted term -> violation ("ALL text is QUOTED").
    leftover = re.sub(r"#[A-Za-z0-9]+", " ", m)
    for tok in re.findall(r"[A-Za-z]{2,}", leftover):
        probs.append(f"unquoted word '{tok}'")
    # single top-level expression?
    s = m.strip()
    if s.startswith("#"):
        depth = 0; end = -1
        for i, ch in enumerate(s):
            if ch == "(": depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0: end = i; break
        if end != len(s) - 1:
            probs.append("more than one top-level expression")
    elif not s.startswith("#"):
        probs.append("does not start with an operator")
    return probs

def shape(q: str) -> str:
    top = q.strip()
    root = re.match(r"#(\w+)", top)
    root = root.group(1) if root else "?"
    n_combine = len(re.findall(r"#combine\(", q))
    n_weight = len(re.findall(r"#weight\(", q))
    n_uw = len(re.findall(r"#uw\d+\(", q))
    n_phrase = len(re.findall(r"#\d+\(", q))
    n_syn = len(re.findall(r"#syn\(", q))
    n_band = len(re.findall(r"#band\(", q))
    n_sif = len(re.findall(r"#scoreif\(", q)) + len(re.findall(r"#scoreifnot\(", q))
    # #syn misuse: a #syn that is a direct operand of a ranking op (#combine/#weight)?
    syn_bad = 0
    for mt in re.finditer(r"#(combine|weight)\(", q):
        # crude: does a #syn appear as an immediate child (not nested in a window)?
        pass
    return (f"root=#{root} combine={n_combine} weight={n_weight} uw={n_uw} "
            f"phrase#1={n_phrase} syn={n_syn} band={n_band} scoreif={n_sif}")


def _is_window(op: str | None) -> bool:
    return bool(op) and (op == "#uw" or bool(re.fullmatch(r"#uw\d+", op)) or bool(re.fullmatch(r"#\d+", op)))


def syn_usage(q: str) -> tuple[int, int]:
    """(ok, misused) counts for #syn. OK == immediate parent is a window (#uwN/#N);
    misused == parent is a ranking op (#combine/#weight/#scoreif...) or root -- the
    'blend stats into a mega-word' anti-pattern the prompt bans."""
    toks = re.findall(r'"(?:\\.|[^"\\])*"|#[A-Za-z0-9]+|\(|\)', q)
    stack: list[str | None] = []
    pending: str | None = None
    ok = bad = 0
    for t in toks:
        if t.startswith("#"):
            pending = t
        elif t == "(":
            if pending == "#syn":
                parent = stack[-1] if stack else None
                if _is_window(parent):
                    ok += 1
                else:
                    bad += 1
            stack.append(pending)
            pending = None
        elif t == ")":
            if stack:
                stack.pop()
            pending = None
    return ok, bad

TOOLS = [{
    "type": "function",
    "function": {
        "name": "submit_query",
        "description": "Submit ONE full query in the structured query language.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "the full query string"}},
            "required": ["query"],
        },
    },
}]

TOPICS = [
    ("401", "What language and cultural differences impede the integration of foreign minorities in Germany?"),
    ("403", "Find information on the effects of the dietary intakes of potassium, magnesium and fruits and vegetables as determinants of bone mineral density in elderly men and women thus preventing osteoporosis (bone decay)."),
    ("416", "What is the status of The Three Gorges Project?"),
    ("419", "What new uses have been developed for old automobile tires as a means of tire recycling?"),
    ("426", "Provide information on the use of dogs worldwide for law enforcement purposes."),
    ("438", "What countries are experiencing an increase in tourism?"),
    ("448", "Identify instances in which weather was a main or contributing factor in the loss of a ship at sea."),
    ("450", "How significant a figure over the years was the late Jordanian King Hussein in furthering peace in the Middle East?"),
]

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt.oss.120b")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--reasoning", default="medium")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--topics", default=None,
                    help="2-column TSV (id<TAB>need); default = built-in TREC-8 subset")
    args = ap.parse_args()

    topics = TOPICS
    if args.topics:
        topics = []
        for line in open(args.topics, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                topics.append((parts[0].strip(), parts[1].strip()))

    system = open(args.prompt).read()
    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    n_clean = syn_ok_tot = syn_bad_tot = n_scoreif_root = 0
    for num, desc in topics:
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Information need: {desc}"},
        ]
        try:
            resp = client.chat.completions.create(
                model=args.model, messages=msgs, tools=TOOLS,
                tool_choice="required", temperature=0.0,
                extra_body={"reasoning_effort": args.reasoning},
            )
        except Exception as e:
            print(f"\n### {num}: LLM ERROR {e}")
            continue
        ch = resp.choices[0]
        u = resp.usage
        tcs = ch.message.tool_calls or []
        preamble = (ch.message.content or "").strip()
        print(f"\n{'='*90}\n### TOPIC {num}: {desc}")
        print(f"finish={ch.finish_reason} tool_calls={len(tcs)} "
              f"tokens(prompt/complet)={u.prompt_tokens}/{u.completion_tokens}"
              + (f"  [PREAMBLE {len(preamble)} chars!]" if preamble else ""))
        if not tcs:
            print("  NO TOOL CALL. content:", preamble[:400]); continue
        for t in tcs:
            if t.function.name != "submit_query":
                print(f"  WRONG TOOL: {t.function.name}"); continue
            try:
                q = json.loads(t.function.arguments or "{}").get("query", "")
            except json.JSONDecodeError:
                print(f"  BAD ARGS JSON: {t.function.arguments!r}"); continue
            probs = validate(q)
            clean = not probs
            n_clean += clean
            syn_ok, syn_bad = syn_usage(q)
            syn_ok_tot += syn_ok
            syn_bad_tot += syn_bad
            if q.strip().startswith("#scoreif"):
                n_scoreif_root += 1
            print(f"  QUERY:\n    " + q.replace("\n", "\n    "))
            print(f"  SHAPE: {shape(q)}")
            print(f"  SYN:   in-window(ok)={syn_ok}  ranking-operand(MISUSE)={syn_bad}")
            print(f"  VALID: {'CLEAN' if clean else 'PROBLEMS: ' + '; '.join(probs)}")
    print(f"\n{'='*90}")
    print(f"CLEAN queries:            {n_clean}/{len(topics)}")
    print(f"#syn in-window (ok):      {syn_ok_tot}")
    print(f"#syn as ranking operand:  {syn_bad_tot}   <-- the anti-pattern; want 0")
    print(f"filter-first (root=#scoreif): {n_scoreif_root}/{len(topics)}")

if __name__ == "__main__":
    main()
