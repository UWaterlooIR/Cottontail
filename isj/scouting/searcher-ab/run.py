"""TASK-22 A/B: plain Searcher vs JSON TieredSearcher vs MultiTextTieredSearcher.

Same 6 general-web questions through the FULL isj pipeline (CLI subprocess — the
exact production path) for each searcher class. Fairness (per Mark, 2026-07-04):
the binding constraint is the number of DOCS JUDGED — [loop] max_judgments = 250
per run, identical across arms — with max_queries = 50 as a non-binding runaway
backstop. reasoning_effort = medium for every arm (the validated setting; 'high'
is pathological for the tiered searchers). The Analyst runs at temperature 0, so
all three arms see the same intents per question and the same per-intent split
of the judgment budget. Everything else comes verbatim from isj/config.toml,
except the server is the port-8081 1M burrow.

Run (from repo root; vLLM + the 8081 dev server up; server binary must carry
/tools/multitext_tiered_search):
  uv run --directory isj python scouting/searcher-ab/run.py
Then:
  uv run --directory isj python scouting/searcher-ab/summarize.py
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
ISJ = HERE.resolve().parents[1]  # searcher-ab -> scouting -> isj

ARMS = {
    "cover": "isj_agent.agents.searcher.Searcher",
    "tiered": "isj_agent.agents.tiered_searcher.TieredSearcher",
    "multitext": "isj_agent.agents.mt_tiered_searcher.MultiTextTieredSearcher",
}

QUESTIONS = {
    "fasting": "What are the health effects of intermittent fasting on adults?",
    "solarloss": "How and why does solar panel efficiency degrade over time?",
    "reading": "What methods are used to teach reading comprehension to elementary school students?",
    "invasive": "What is the impact of invasive species on freshwater ecosystems?",
    "inflation": "What causes inflation and how do central banks respond to it?",
    "vaccines": "How do vaccines produce immunity and why are booster shots needed?",
}

MAX_JUDGMENTS = 250
MAX_QUERIES = 50


def arm_config(cls: str) -> str:
    s = (ISJ / "config.toml").read_text(encoding="utf-8")
    s = re.sub(r'(\[agents\.searcher\][^[]*?)class = "[^"]*"',
               rf'\g<1>class = "{cls}"', s, count=1, flags=re.S)
    s = re.sub(r'(\[agents\.searcher\][^[]*?)reasoning_effort = "[^"]*"',
               r'\g<1>reasoning_effort = "medium"', s, count=1, flags=re.S)
    s = re.sub(r'(\[agents\.searcher\][^[]*?)max_queries = \d+',
               rf'\g<1>max_queries = {MAX_QUERIES}', s, count=1, flags=re.S)
    s = re.sub(r'base_url = "http://127\.0\.0\.1:8080"',
               'base_url = "http://127.0.0.1:8081"', s)
    if re.search(r'^\s*max_judgments\s*=', s, re.M):
        s = re.sub(r'^\s*#?\s*max_judgments\s*=.*$',
                   f'max_judgments = {MAX_JUDGMENTS}', s, count=1, flags=re.M)
    else:
        s = s.replace("[loop]", f"[loop]\nmax_judgments = {MAX_JUDGMENTS}", 1)
    return s


def main():
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    manifest = results / "manifest.jsonl"
    done = set()
    if manifest.exists():
        for line in manifest.open():
            r = json.loads(line)
            if r.get("ok"):
                done.add((r["arm"], r["qid"]))
    with manifest.open("a") as mf:
        for arm, cls in ARMS.items():
            cfg_path = results / f"config-{arm}.toml"
            cfg_path.write_text(arm_config(cls), encoding="utf-8")
            for qid, question in QUESTIONS.items():
                if (arm, qid) in done:
                    print(f"[{arm}/{qid}] skip (done)", flush=True)
                    continue
                out = results / arm / qid
                t0 = time.time()
                p = subprocess.run(
                    [sys.executable, "-m", "isj_agent.cli",
                     "--config", str(cfg_path), "--question", question,
                     "--out", str(out), "--overwrite"],
                    cwd=ISJ, capture_output=True, text=True, timeout=3600)
                rec = {"arm": arm, "qid": qid, "ok": p.returncode == 0,
                       "wall_s": round(time.time() - t0, 1),
                       "tail": (p.stdout + p.stderr)[-400:]}
                mf.write(json.dumps(rec) + "\n")
                mf.flush()
                print(f"[{arm}/{qid}] ok={rec['ok']} {rec['wall_s']}s", flush=True)
    print("done ->", results, flush=True)


if __name__ == "__main__":
    main()
