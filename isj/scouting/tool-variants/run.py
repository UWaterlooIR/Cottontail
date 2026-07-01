"""Run prompt_type x tool_type (query = TREC-4 questions), FAIL-FAST by default
(0 retries, 120 s/attempt) so a runaway generation caps at 2 min instead of retrying.

  uv run --directory isj python scouting/tool-variants/run.py            # full grid (6 cells x 4 needs)
  uv run --directory isj python scouting/tool-variants/run.py --needs quebec_independence  # smoke
  uv run --directory isj python scouting/tool-variants/summarize.py

Records append to results/records.jsonl (incremental, resumable). A timeout is DATA
(the runaway signal), recorded as an error row.
"""

import argparse
import json
import time
from pathlib import Path

import openai

import metrics
import variants

HERE = Path(__file__).parent


def _generate(client, model, prompt_text, tool, need_text, effort, temperature):
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": f"Information need: {need_text}"},
        ],
        tools=[tool["schema"]],
        tool_choice="required",
        temperature=temperature,
        extra_body={"reasoning_effort": effort} if effort else {},
    )
    msg = resp.choices[0].message
    calls = msg.tool_calls or []
    usage = getattr(resp, "usage", None)
    raw = {"content": msg.content, "usage": usage.model_dump() if usage else None}
    if not calls:
        raw["error"] = "no tool call"
        return [], raw
    args = json.loads(calls[0].function.arguments or "{}")
    raw["arguments"] = args
    return tool["extract"](args), raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vllm", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="gpt.oss.120b")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--client-timeout", type=float, default=120.0, help="per-attempt timeout (s)")
    ap.add_argument("--max-retries", type=int, default=0, help="OpenAI client auto-retries")
    ap.add_argument("--needs", default="", help="comma-separated need ids (default: all)")
    ap.add_argument("--out", default=str(HERE / "results" / "records.jsonl"))
    args = ap.parse_args()

    needs = variants.NEEDS
    if args.needs:
        want = set(args.needs.split(","))
        needs = [n for n in needs if n["id"] in want]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.open():
            try:
                r = json.loads(line)
                done.add((r["prompt"], r["tool"], r["need"]))
            except Exception:  # noqa: BLE001
                pass

    client = openai.OpenAI(base_url=args.vllm, api_key="EMPTY",
                           timeout=args.client_timeout, max_retries=args.max_retries)
    cells = list(variants.cells())
    total = len(cells) * len(needs)
    n = 0
    with out.open("a") as f:
        for cell in cells:
            for need in needs:
                n += 1
                key = (cell["prompt"], cell["tool"], need["id"])
                if key in done:
                    print(f"[{n}/{total}] skip {key}", flush=True)
                    continue
                need_text = need["trec"]
                t0 = time.time()
                rec = {"prompt": cell["prompt"], "tool": cell["tool"], "query": "trec",
                       "need": need["id"], "need_text": need_text, "entity": need["entity"]}
                try:
                    tiers, raw = _generate(client, args.model, variants.PROMPTS[cell["prompt"]],
                                           variants.TOOLS[cell["tool"]], need_text,
                                           args.effort or None, args.temperature)
                    rec["tiers"] = tiers
                    rec["metrics"] = metrics.analyze(tiers)
                    rec["entity_dropped"] = metrics.entity_dropped(tiers, need["entity"])
                    rec["raw"] = raw
                except Exception as e:  # noqa: BLE001 -- one bad cell must not kill the grid
                    rec["error"] = f"{type(e).__name__}: {e}"
                rec["elapsed_s"] = round(time.time() - t0, 1)
                f.write(json.dumps(rec) + "\n")
                f.flush()
                m = rec.get("metrics", {})
                print(f"[{n}/{total}] {cell['prompt']:6} {cell['tool']:16} {need['id']:16} "
                      f"max_terms/facet={m.get('max_terms_per_facet', '-'):>3} "
                      f"n_tiers={m.get('n_tiers', '-')}  {rec['elapsed_s']}s"
                      + (f"  ERROR {rec['error']}" if "error" in rec else ""), flush=True)
    print("done ->", out, flush=True)


if __name__ == "__main__":
    main()
