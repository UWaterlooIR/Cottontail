"""S3 addendum (TASK-26): the compile-error BOUNCE self-correction path.

Replays the one captured compile failure (fasting turn 3 in turns.jsonl: a
malformed `t0 = (if) < [5] ad ^ h ^ s` proximity chain) as a reconstructed
conversation -- the bad program as the assistant's tool call, the REAL compiler
diagnostics as the tool result -- and asks for the next turn. Question: does the
model repair the program from the diagnostic alone? Three trials (t=0, then 0.3
for variety).

Run: uv run --directory isj python scouting/multitext-dsl-2/run_bounce_replay.py
"""

import json
from pathlib import Path

from common import HERE, compile_program, make_client, propose_toolcall

PROMPT = (HERE / "prompt-turns.md").read_text(encoding="utf-8")
NEED = "the health effects of intermittent fasting on adults"
OUT = HERE / "results" / "bounce-replay.jsonl"


def main():
    bad = None
    for line in (HERE / "results" / "turns.jsonl").open():
        r = json.loads(line)
        if r["need"] == "fasting" and r["turn"] == 3 and r["outcome"] == "compile_bounce":
            bad = r
    assert bad, "captured bounce record not found"
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": NEED},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "call_replay1", "type": "function",
            "function": {"name": "submit_tiered_query",
                         "arguments": json.dumps({"program": bad["program"]})}}]},
        {"role": "tool", "tool_call_id": "call_replay1",
         "content": json.dumps({"error": "program did not compile",
                                "compiler": bad["compile"]["error_messages"]})},
    ]
    client = make_client()
    with OUT.open("a") as f:
        for trial in range(3):
            p = propose_toolcall(client, "gpt.oss.120b", messages,
                                 effort="medium",
                                 temperature=0.0 if trial == 0 else 0.3)
            c = compile_program(p["program"]) if p.get("program") else {"compiled": False}
            rec = {"trial": trial, "emit": p.get("emit"),
                   "compiled": c.get("compiled"), "errors": c.get("errors"),
                   "reasoning_chars": len(p.get("reasoning") or ""),
                   "program": p.get("program")}
            f.write(json.dumps(rec) + "\n")
            print(f"trial {trial}: emit={rec['emit']} compiled={rec['compiled']} "
                  f"errors={rec['errors']} reasoning={rec['reasoning_chars']}c")
            if p.get("program"):
                for l in p["program"].splitlines():
                    if l.strip().startswith(("t0", "t1")):
                        print("   repaired:", l[:120])
    print("done ->", OUT)


if __name__ == "__main__":
    main()
