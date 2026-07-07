"""S3 (TASK-26): does the MultiText librarian hold up over MULTIPLE TURNS?

Per need (hand-written GENERAL-WEB needs -- ClimbMix is a general web corpus,
nothing to do with climbing): 3 turns. Each turn the model submits a program via
the tool; we compile it (mt-compile); a compile failure is bounced back verbatim
as the tool result (the TASK-22 design); otherwise the compiled tiers run
against the LIVE 1M dev server's tiered_query_search (cps surfaced in earlier
turns are excluded, mirroring the controller's paging), and the real response --
match counts, atom_counts, per-document summaries -- is appended as the tool
result for the next turn.

Watched: per-turn emission/compile validity, reasoning size stability (loop
regression), and whether programs ADAPT (new quoted terms per turn) rather than
repeat.

Run (from repo root; vLLM + the port-8081 dev server up; mt-compile built):
  uv run --directory isj python scouting/multitext-dsl-2/run_turns.py
"""

import argparse
import json
import time
from pathlib import Path

import httpx

from common import HERE, compile_program, make_client, propose_toolcall

PROMPT = (HERE / "prompt-turns.md").read_text(encoding="utf-8")

NEEDS = {
    "fasting": "the health effects of intermittent fasting on adults",
    "solarloss": "how and why solar panel efficiency degrades over time",
    "reading": "methods for teaching reading comprehension to elementary school students",
    "invasive": "the impact of invasive species on freshwater ecosystems",
}


def run_tiers(server: str, tiers: list[str], exclude: list[int]) -> dict:
    r = httpx.post(f"{server}/tools/tiered_query_search",
                   json={"tiers": tiers, "top_k": 10, "exclude": exclude,
                         "window": 75},
                   timeout=300.0)
    r.raise_for_status()
    return r.json()


def feedback(resp: dict, max_summary: int = 280) -> str:
    """The tool-result text the model sees: compact but real."""
    out = {
        "total_matches": resp.get("total_matches"),
        "unjudged_matches": resp.get("unjudged_matches"),
        "atom_counts": resp.get("atom_counts"),
        "results": [
            {"rank": h.get("rank"), "score": h.get("score"), "cp": h.get("cp"),
             "summary": (h.get("summary") or "")[:max_summary]}
            for h in resp.get("results", [])
        ],
    }
    return json.dumps(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vllm", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="gpt.oss.120b")
    ap.add_argument("--server", default="http://127.0.0.1:8081")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--needs", default="", help="comma-separated need ids (default: all)")
    ap.add_argument("--out", default=str(HERE / "results" / "turns.jsonl"))
    args = ap.parse_args()
    needs = {k: v for k, v in NEEDS.items()
             if not args.needs or k in args.needs.split(",")}

    client = make_client(args.vllm)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("a") as f:
        for need_id, need in needs.items():
            messages = [{"role": "system", "content": PROMPT},
                        {"role": "user", "content": need}]
            exclude: list[int] = []
            prev_tokens: set[str] = set()
            bounce_retries = 0  # a compile bounce grants ONE extra turn: the
            turn = 0            # self-correction path is exactly what we scout
            while turn < args.turns + min(bounce_retries, 1):
                turn += 1
                rec = {"need": need_id, "turn": turn}
                t0 = time.time()
                try:
                    p = propose_toolcall(client, args.model, messages,
                                         effort=args.effort)
                    rec.update({k: p.get(k) for k in
                                ("emit", "program", "program_lines", "content",
                                 "n_tool_calls", "finish_reason", "usage")})
                    rec["reasoning_chars"] = len(p.get("reasoning") or "")
                    if p.get("emit") != "tool_call":
                        rec["outcome"] = "no_tool_call"
                        f.write(json.dumps(rec) + "\n"); f.flush()
                        break
                    messages.append(p["assistant_message"])
                    comp = compile_program(p["program"])
                    rec["compile"] = comp
                    import re as _re
                    tokens = set(_re.findall(r'"([^"]+)"', p["program"]))
                    rec["n_tokens"] = len(tokens)
                    rec["n_new_tokens"] = len(tokens - prev_tokens)
                    prev_tokens |= tokens
                    if not comp["compiled"]:
                        tool_result = json.dumps(
                            {"error": "program did not compile",
                             "compiler": comp["error_messages"]})
                        rec["outcome"] = "compile_bounce"
                        bounce_retries += 1
                    else:
                        resp = run_tiers(args.server,
                                         comp["tier_s_expressions"], exclude)
                        new_cps = [h["cp"] for h in resp.get("results", [])]
                        exclude += new_cps
                        rec["outcome"] = "ran"
                        rec["total_matches"] = resp.get("total_matches")
                        rec["n_results"] = len(new_cps)
                        rec["zero_atoms"] = [a["term"] for a in
                                             resp.get("atom_counts", [])
                                             if a.get("count") == 0]
                        tool_result = feedback(resp)
                    messages.append({"role": "tool",
                                     "tool_call_id": p["tool_call_id"],
                                     "content": tool_result})
                except Exception as e:  # noqa: BLE001
                    rec["outcome"] = f"error: {type(e).__name__}: {e}"
                rec["elapsed_s"] = round(time.time() - t0, 1)
                f.write(json.dumps(rec) + "\n")
                f.flush()
                print(f"[{need_id} t{turn}] {rec.get('outcome')}"
                      f" compiled={rec.get('compile', {}).get('compiled')}"
                      f" results={rec.get('n_results')}"
                      f" matches={rec.get('total_matches')}"
                      f" new_tokens={rec.get('n_new_tokens')}"
                      f" reason={rec.get('reasoning_chars')}c"
                      f" {rec['elapsed_s']}s", flush=True)
                if rec.get("outcome", "").startswith("error"):
                    break
    print("done ->", out, flush=True)


if __name__ == "__main__":
    main()
