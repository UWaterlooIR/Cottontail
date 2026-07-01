"""Run the tiered-query 2x2x2 factorial.

GENERATION + static metrics are the core; live server validation is OPTIONAL
(--validate). Records are appended to results/records.jsonl as each cell/need completes
(so a crash keeps progress), and the run is RESUMABLE: an already-recorded (cell, need)
is skipped. Static metrics do NOT need the server; --validate additionally executes each
cascade on a running cottontail server.

Run (from the repo root):
    uv run --directory isj python scouting/tiered-factorial/run.py            # full grid
    uv run --directory isj python scouting/tiered-factorial/run.py --needs au_pair   # 1-need smoke
    uv run --directory isj python scouting/tiered-factorial/run.py --validate        # + live parse/exec

Cost: 8 cells x N needs generations at high reasoning (~1-2 min each). The full grid
(N=4) is ~32 calls -> ~30-60 min; run it in the background.
"""

import argparse
import json
import time
from pathlib import Path

import httpx
import openai

import factors
import metrics

HERE = Path(__file__).parent


def _generate(client, model, prompt_text, tool, need_text, effort, temperature):
    """One generation. Returns (tiers, raw_dict). raw carries reasoning + args + usage."""
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


def _validate(server, tiers, timeout):
    """Execute the whole cascade once. A malformed tier 400s fast; a valid-but-huge
    cascade may exceed the timeout (still 'parsed', just degenerate)."""
    try:
        r = httpx.post(f"{server}/tools/tiered_query_search",
                       json={"tiers": tiers, "top_k": 5}, timeout=timeout)
        if r.status_code == 400:
            return {"status": "parse_fail", "error": r.json().get("error")}
        r.raise_for_status()
        d = r.json()
        return {"status": "ok", "total_matches": d["total_matches"],
                "results": len(d["results"]),
                "dead_atoms": [a["term"] for a in d["atom_counts"] if a["count"] == 0]}
    except httpx.ReadTimeout:
        return {"status": "timeout_degenerate"}
    except Exception as e:  # noqa: BLE001 -- record any engine/transport failure
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vllm", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="gpt.oss.120b")
    ap.add_argument("--effort", default="high", help="reasoning_effort ('' to omit)")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--server", default="http://127.0.0.1:8080")
    ap.add_argument("--validate", action="store_true",
                    help="also execute each cascade on the cottontail server")
    ap.add_argument("--validate-timeout", type=float, default=30.0)
    ap.add_argument("--client-timeout", type=float, default=600.0,
                    help="per-attempt request timeout (seconds)")
    ap.add_argument("--max-retries", type=int, default=2,
                    help="OpenAI client auto-retries (0 = fail fast on a timeout)")
    ap.add_argument("--prompts", default="scout,task20",
                    help="comma-separated prompt levels to run (e.g. 'task20')")
    ap.add_argument("--needs", default="", help="comma-separated need ids (default: all)")
    ap.add_argument("--out", default=str(HERE / "results" / "records.jsonl"))
    args = ap.parse_args()

    needs = factors.NEEDS
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
                done.add((r["prompt"], r["query"], r["tool"], r["need"]))
            except Exception:  # noqa: BLE001
                pass

    client = openai.OpenAI(base_url=args.vllm, api_key="EMPTY",
                           timeout=args.client_timeout, max_retries=args.max_retries)
    want_prompts = set(args.prompts.split(","))
    cells = [c for c in factors.cells() if c["prompt"] in want_prompts]
    total = len(cells) * len(needs)
    n = 0
    with out.open("a") as f:
        for cell in cells:
            for need in needs:
                n += 1
                key = (cell["prompt"], cell["query"], cell["tool"], need["id"])
                if key in done:
                    print(f"[{n}/{total}] skip {key}", flush=True)
                    continue
                need_text = need[cell["query"]]
                t0 = time.time()
                rec = {"prompt": cell["prompt"], "query": cell["query"], "tool": cell["tool"],
                       "need": need["id"], "need_text": need_text, "entity": need["entity"]}
                try:
                    tiers, raw = _generate(client, args.model, factors.PROMPTS[cell["prompt"]],
                                           factors.TOOLS[cell["tool"]], need_text,
                                           args.effort or None, args.temperature)
                    rec["tiers"] = tiers
                    rec["metrics"] = metrics.analyze(tiers)
                    rec["entity_dropped"] = metrics.entity_dropped(tiers, need["entity"])
                    rec["raw"] = raw
                    if args.validate and tiers:
                        rec["validation"] = _validate(args.server, tiers, args.validate_timeout)
                except Exception as e:  # noqa: BLE001 -- one bad cell must not kill the grid
                    rec["error"] = f"{type(e).__name__}: {e}"
                rec["elapsed_s"] = round(time.time() - t0, 1)
                f.write(json.dumps(rec) + "\n")
                f.flush()
                m = rec.get("metrics", {})
                print(f"[{n}/{total}] {cell['prompt']:6} {cell['query']:7} {cell['tool']:7} "
                      f"{need['id']:16} max_terms/facet={m.get('max_terms_per_facet', '-'):>3} "
                      f"n_tiers={m.get('n_tiers', '-')}  {rec['elapsed_s']}s"
                      + (f"  ERROR {rec['error']}" if "error" in rec else ""), flush=True)
    print("done ->", out, flush=True)


if __name__ == "__main__":
    main()
