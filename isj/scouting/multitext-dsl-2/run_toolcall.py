"""S1 (TASK-26): can the LLM submit the MultiText program THROUGH A TOOL CALL?

The original multitext-dsl scout got 10/10 compile validity with the program in
the plain content channel; earlier attempts at tool-call emission reportedly
failed, and the run.py there defined the tool but never passed it. TASK-22's
real Searcher uses tools + tool_choice="required" (BaseSearcher.propose), so
this is the go/no-go question for that design.

Run (from repo root, vLLM up, //apps:mt-compile built):
  uv run --directory isj python scouting/multitext-dsl-2/run_toolcall.py
"""

import argparse
import json
import time
from pathlib import Path

from common import (DEFAULT_TOPICS, HERE, compile_program, load_topics,
                    make_client, propose_toolcall)

PROMPT = (HERE / "prompt-toolcall.md").read_text(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vllm", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="gpt.oss.120b")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--topics", default="")
    ap.add_argument("--prompt", default=str(HERE / "prompt-toolcall.md"))
    ap.add_argument("--out", default=str(HERE / "results" / "toolcall.jsonl"))
    args = ap.parse_args()

    prompt = Path(args.prompt).read_text(encoding="utf-8")
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

    client = make_client(args.vllm)
    with out.open("a") as f:
        for i, topic in enumerate(want, 1):
            if topic in done:
                print(f"[{i}/{len(want)}] skip topic {topic}", flush=True)
                continue
            rec = {"topic": topic, "mode": "toolcall", "effort": args.effort}
            t0 = time.time()
            try:
                messages = [{"role": "system", "content": prompt},
                            {"role": "user", "content": topics_text[topic]}]
                rec.update(propose_toolcall(client, args.model, messages,
                                            effort=args.effort,
                                            temperature=args.temperature))
                rec.pop("assistant_message", None)  # bulky; not needed single-turn
                if rec.get("program"):
                    rec["compile"] = compile_program(rec["program"])
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
            rec["elapsed_s"] = round(time.time() - t0, 1)
            f.write(json.dumps(rec) + "\n")
            f.flush()
            c = rec.get("compile", {})
            print(f"[{i}/{len(want)}] topic {topic}: emit={rec.get('emit', rec.get('error', '?'))}"
                  f" lines={rec.get('program_lines')}"
                  f" compiled={c.get('compiled')} errors={c.get('errors')}"
                  f" reason={len(rec.get('reasoning') or '')}c {rec['elapsed_s']}s",
                  flush=True)
    print("done ->", out, flush=True)


if __name__ == "__main__":
    main()
