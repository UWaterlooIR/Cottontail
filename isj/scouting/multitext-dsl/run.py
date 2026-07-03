"""Scouting: can gpt-oss-120b write VALID MultiText DSL programs?

For each TREC-4 topic, prompt gpt-oss with the librarian prompt (role + primer + the
topic-208 example) and a `submit_tiered_query(program)` tool. Feed the emitted program
to the EXISTING Cottontail MultiText compiler (bazel-bin/apps/mt-compile) and record
whether every statement compiled, the errors, and the compiled tier s-expressions.

The question: does the LLM produce valid, compilable MultiText (like ChatGPT did), and
are the errors the kind a compiler-error bounce would fix?

Run (from repo root, vLLM up, //apps:mt-compile built):
  uv run --directory isj python scouting/multitext-dsl/run.py
  uv run --directory isj python scouting/multitext-dsl/run.py --topics 214,224   # subset
"""

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import openai

HERE = Path(__file__).parent
REPO = HERE.resolve().parents[2]  # multitext-dsl -> scouting -> isj -> <repo>

MT_COMPILE = REPO / "bazel-bin" / "apps" / "mt-compile"
TOPICS_FILE = REPO / "docs" / "trec4" / "topics.201-250"
PROMPT = (HERE / "librarian-prompt.md").read_text(encoding="utf-8")

# A spread of TREC-4 topics (208 is the worked example, so it is excluded).
DEFAULT_TOPICS = [203, 207, 211, 214, 220, 224, 229, 238, 244, 249]

TOOL = {
    "type": "function",
    "function": {
        "name": "submit_tiered_query",
        "description": "Submit your MultiText GCL program: the facet/tier macro definitions "
                       "(one per line, `name = expr`) followed by a single `@rank` line listing "
                       "the tier macros in precise->broad order.",
        "parameters": {
            "type": "object",
            "properties": {
                "program": {"type": "string",
                            "description": "The full program text: macro definitions, then one @rank line."}
            },
            "required": ["program"],
        },
    },
}


def load_topics():
    """Return {num: plain single-statement need} -- the topic DESCRIPTION text with the
    TREC <top>/<num>/<desc> markup stripped (the real task gets a bare intent)."""
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
    """Run the MultiText compiler over `program`; parse its per-statement report."""
    p = subprocess.run([str(MT_COMPILE)], input=program, capture_output=True, text=True)
    lines = p.stdout.splitlines()
    defs_ok = sum(1 for l in lines if l.startswith("DEF\tOK"))
    defs_err = sum(1 for l in lines if l.startswith("DEF\tERR"))
    tiers_ok = sum(1 for l in lines if l.startswith("TIER\tOK"))
    tiers_err = sum(1 for l in lines if l.startswith("TIER\tERR"))
    errors = [l.split("\t", 2)[-1] for l in lines if "\tERR\t" in l]
    tiers = [l.split("\t", 3)[-1] for l in lines if l.startswith("TIER\tOK")]
    m = re.search(r"statements=(\d+) errors=(\d+)", p.stdout)
    statements = int(m.group(1)) if m else 0
    n_errors = int(m.group(2)) if m else (defs_err + tiers_err)
    return {
        "compiled": p.returncode == 0 and n_errors == 0,
        "statements": statements, "errors": n_errors,
        "n_macros": defs_ok, "n_tiers": tiers_ok,
        "error_messages": errors, "tier_s_expressions": tiers,
        "raw": p.stdout,
    }


def extract_program(text: str) -> str:
    """Pull the MultiText program out of a free-form completion: prefer a fenced code
    block, else take from the first macro definition / @-line through the @rank line."""
    m = re.search(r"```[a-zA-Z]*\n(.*?)```", text, re.S)
    body = m.group(1) if m else text
    lines = body.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if re.match(r"\s*[A-Za-z_]\w*\s*=", l) or l.lstrip().startswith("@")), None)
    if start is None:
        return body.strip()
    end = next((i for i, l in enumerate(lines) if l.lstrip().startswith("@rank")), len(lines) - 1)
    if end < start:
        end = len(lines) - 1
    return "\n".join(lines[start:end + 1]).strip()


def stream_completion(client, model, system, user, effort, temperature, deadline):
    """Stream a completion, accumulating REASONING and CONTENT separately, capped at
    `deadline` wall-clock seconds. Returns (reasoning, content, usage_dict, timed_out).
    Keeps the partial output on a deadline break OR a mid-stream transport error."""
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        extra_body={"reasoning_effort": effort} if effort else {},
        stream=True,
        stream_options={"include_usage": True},
    )
    reasoning, content, usage, timed_out = [], [], None, False
    t0 = time.time()
    try:
        for chunk in stream:
            if chunk.choices:
                d = chunk.choices[0].delta
                r = getattr(d, "reasoning", None) or getattr(d, "reasoning_content", None)
                if r:
                    reasoning.append(r)
                if getattr(d, "content", None):
                    content.append(d.content)
            u = getattr(chunk, "usage", None)
            if u:
                usage = u.model_dump()
            if time.time() - t0 > deadline:
                timed_out = True
                break
    except Exception:  # noqa: BLE001 -- read timeout / transport error: keep the partial
        timed_out = True
    finally:
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass
    return "".join(reasoning), "".join(content), usage, timed_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vllm", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="gpt.oss.120b")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--client-timeout", type=float, default=180.0)
    ap.add_argument("--max-retries", type=int, default=0)
    ap.add_argument("--topics", default="", help="comma-separated topic numbers (default: the spread)")
    ap.add_argument("--out", default=str(HERE / "results" / "records.jsonl"))
    args = ap.parse_args()

    if not MT_COMPILE.exists():
        raise SystemExit(f"build it first: bazel build //apps:mt-compile  (missing {MT_COMPILE})")
    topics_text = load_topics()
    want = [int(t) for t in args.topics.split(",")] if args.topics else DEFAULT_TOPICS

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.open():
            try:
                done.add(json.loads(line)["topic"])
            except Exception:  # noqa: BLE001
                pass

    # generous per-read timeout so our manual wall-clock deadline is what caps a run
    client = openai.OpenAI(base_url=args.vllm, api_key="EMPTY",
                           timeout=args.client_timeout + 60, max_retries=args.max_retries)
    with out.open("a") as f:
        for i, topic in enumerate(want, 1):
            if topic in done:
                print(f"[{i}/{len(want)}] skip topic {topic}", flush=True)
                continue
            rec = {"topic": topic}
            t0 = time.time()
            try:
                reasoning, content, usage, timed_out = stream_completion(
                    client, args.model, PROMPT, topics_text[topic],
                    args.effort or None, args.temperature, args.client_timeout)
                rec["reasoning"] = reasoning
                rec["content"] = content
                rec["timed_out"] = timed_out
                rec["usage"] = usage
                program = extract_program(content or "")
                rec["program"] = program
                if program.strip():
                    rec["compile"] = compile_program(program)
                elif timed_out:
                    rec["error"] = "timed out before a program was emitted"
                else:
                    rec["error"] = "no program extracted"
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
            rec["elapsed_s"] = round(time.time() - t0, 1)
            f.write(json.dumps(rec) + "\n")
            f.flush()
            c = rec.get("compile", {})
            status = ("compiled={} macros={} tiers={} errors={}".format(
                        c.get("compiled"), c.get("n_macros"), c.get("n_tiers"), c.get("errors"))
                      if "compile" in rec else rec.get("error", "?"))
            print(f"[{i}/{len(want)}] topic {topic}: {status}"
                  + ("  [TIMED OUT]" if rec.get("timed_out") else "")
                  + f"  reason={len(rec.get('reasoning') or '')}c content={len(rec.get('content') or '')}c"
                  + f"  {rec['elapsed_s']}s", flush=True)
    print("done ->", out, flush=True)


if __name__ == "__main__":
    main()
