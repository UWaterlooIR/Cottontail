"""Summarize prompt_type x tool_type: per-cell done/timeout + mean/max terms; marginals.
Run: uv run --directory isj python scouting/tool-variants/summarize.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
KEY = "max_terms_per_facet"


def load(p):
    return [json.loads(l) for l in Path(p).open() if l.strip()]


def st(r):
    return "done" if "metrics" in r else "timeout"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "results" / "records.jsonl")
    recs = load(path)
    if not recs:
        print("no records in", path)
        return

    print("=== per (prompt, tool): done/total, timeouts, mean & max terms among completed ===")
    cell = defaultdict(list)
    for r in recs:
        cell[(r["prompt"], r["tool"])].append(r)
    print(f"{'prompt':7}{'tool':16}{'done/tot':>9}{'timeout':>9}{'meanT':>7}{'maxT':>6}")
    for k in sorted(cell):
        rs = cell[k]
        d = [r for r in rs if st(r) == "done"]
        to = [r for r in rs if st(r) == "timeout"]
        mt = [r["metrics"][KEY] for r in d]
        print(f"{k[0]:7}{k[1]:16}{str(len(d)) + '/' + str(len(rs)):>9}{len(to):>9}"
              f"{(round(sum(mt) / len(mt), 1) if mt else 0):>7}{(max(mt) if mt else 0):>6}")

    print("\n=== marginals ===")
    for factor in ("prompt", "tool"):
        by = defaultdict(list)
        for r in recs:
            by[r[factor]].append(r)
        print(f"  {factor}:")
        for lvl in sorted(by):
            rs = by[lvl]
            d = [r for r in rs if st(r) == "done"]
            to = [r for r in rs if st(r) == "timeout"]
            mt = [r["metrics"][KEY] for r in d]
            print(f"     {lvl:16} done {len(d)}/{len(rs)}  timeouts {len(to)}  "
                  f"mean {round(sum(mt) / len(mt), 1) if mt else 0}  max {max(mt) if mt else 0}")

    ent = [r for r in recs if r.get("entity") and st(r) == "done"]
    if ent:
        drops = sum(1 for r in ent if r.get("entity_dropped"))
        print(f"\n=== entity-drop: {drops}/{len(ent)} completed anchored runs dropped the entity ===")


if __name__ == "__main__":
    main()
