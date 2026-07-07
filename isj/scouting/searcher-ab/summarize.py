"""Summarize the searcher A/B runs (see run.py) from the run-output directories.

Per (arm, question): judged docs, relevant found (grade>=1 / >=2 / ==3),
relevant per judged doc, searcher turns, bounces by kind, searcher completion
tokens, engine latency, wall-clock. Prints a per-arm rollup table and per-
question detail. Reads results/manifest.jsonl + the run dirs.
"""

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"


def one_run(run_dir: Path) -> dict:
    m = {"judged": 0, "g1": 0, "g2": 0, "g3": 0, "turns": 0,
         "bounces": defaultdict(int), "searcher_tokens": 0, "engine_ms": 0.0,
         "intents": 0}
    for f in sorted(run_dir.glob("intent-*.json")):
        r = json.loads(f.read_text())
        entries = r.get("entries") or r.get("ranked_list", {}).get("entries") or []
        m["intents"] += 1
        m["judged"] += len(entries)
        for e in entries:
            g = e.get("grade")
            if isinstance(g, int):
                m["g1"] += g >= 1
                m["g2"] += g >= 2
                m["g3"] += g == 3
    for f in sorted(run_dir.glob("intent-*.trace.jsonl")):
        for line in f.open():
            e = json.loads(line)
            t = e.get("type")
            if t == "llm_call" and e.get("purpose") == "searcher_turn":
                m["turns"] += 1
                m["searcher_tokens"] += e.get("completion_tokens") or 0
            elif t == "bounce":
                m["bounces"][e.get("kind", "?")] += 1
            elif t == "search_response":
                m["engine_ms"] += e.get("duration_ms") or 0.0
    m["bounces"] = dict(m["bounces"])
    return m


def main():
    walls = {}
    for line in (RESULTS / "manifest.jsonl").open():
        r = json.loads(line)
        if r.get("ok"):
            walls[(r["arm"], r["qid"])] = r["wall_s"]
    rows = []
    for (arm, qid), wall in sorted(walls.items()):
        m = one_run(RESULTS / arm / qid)
        m.update(arm=arm, qid=qid, wall_s=wall)
        rows.append(m)

    print(f"{'arm':>10} {'qid':>10} {'judged':>6} {'>=1':>5} {'>=2':>5} {'=3':>4} "
          f"{'rel2/judged':>11} {'turns':>5} {'bounces':>18} {'s_tokens':>8} {'wall_s':>7}")
    for m in rows:
        rj = m["g2"] / m["judged"] if m["judged"] else 0.0
        print(f"{m['arm']:>10} {m['qid']:>10} {m['judged']:>6} {m['g1']:>5} {m['g2']:>5} "
              f"{m['g3']:>4} {rj:>11.2f} {m['turns']:>5} {str(m['bounces']) or '{}':>18} "
              f"{m['searcher_tokens']:>8} {m['wall_s']:>7.0f}")

    print("\nper-arm rollup:")
    print(f"{'arm':>10} {'judged':>7} {'>=1':>6} {'>=2':>6} {'=3':>5} "
          f"{'rel2/judged':>11} {'turns':>6} {'bounces':>8} {'s_tokens':>9} {'wall_s':>7}")
    for arm in {m["arm"] for m in rows}:
        a = [m for m in rows if m["arm"] == arm]
        judged = sum(m["judged"] for m in a)
        g2 = sum(m["g2"] for m in a)
        print(f"{arm:>10} {judged:>7} {sum(m['g1'] for m in a):>6} {g2:>6} "
              f"{sum(m['g3'] for m in a):>5} {g2/judged if judged else 0:>11.2f} "
              f"{sum(m['turns'] for m in a):>6} "
              f"{sum(sum(m['bounces'].values()) for m in a):>8} "
              f"{sum(m['searcher_tokens'] for m in a):>9} "
              f"{sum(m['wall_s'] for m in a):>7.0f}")


if __name__ == "__main__":
    main()
