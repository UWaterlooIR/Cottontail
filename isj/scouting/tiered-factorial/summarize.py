"""Summarize results/records.jsonl: the 8-cell table + the marginal effect of each
factor on the headline bloat metric (max_terms_per_facet), plus validity/entity-drop
rollups. Run: uv run --directory isj python scouting/tiered-factorial/summarize.py
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
KEY = "max_terms_per_facet"


def load(path):
    return [json.loads(l) for l in Path(path).open() if l.strip()]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "results" / "records.jsonl")
    recs = [r for r in load(path) if "metrics" in r]
    errs = [r for r in load(path) if "error" in r]
    if not recs:
        print("no records with metrics in", path)
        if errs:
            print(f"({len(errs)} errored records)")
        return

    print(f"\n=== per-cell mean {KEY} (averaged over needs) -- lower is more disciplined ===")
    cell = defaultdict(list)
    for r in recs:
        cell[(r["prompt"], r["query"], r["tool"])].append(r["metrics"][KEY])
    print(f"{'prompt':7} {'query':8} {'tool':8} {'mean':>6} {'max':>5} {'n':>3}")
    for k in sorted(cell):
        xs = cell[k]
        print(f"{k[0]:7} {k[1]:8} {k[2]:8} {sum(xs) / len(xs):6.1f} {max(xs):5} {len(xs):>3}")

    print(f"\n=== marginal mean {KEY} per factor level (averaged over the other two) ===")
    for factor in ("prompt", "query", "tool"):
        by = defaultdict(list)
        for r in recs:
            by[r[factor]].append(r["metrics"][KEY])
        print(f"  {factor}:")
        for lvl in sorted(by):
            xs = by[lvl]
            print(f"     {lvl:9} mean={sum(xs) / len(xs):6.1f}  (n={len(xs)})")

    val = [r["validation"]["status"] for r in recs if "validation" in r]
    if val:
        print(f"\n=== live validation status counts ===\n  {dict(Counter(val))}")

    ent = [r for r in recs if r.get("entity")]
    if ent:
        drops = sum(1 for r in ent if r.get("entity_dropped"))
        print(f"\n=== entity-drop: {drops}/{len(ent)} entity-anchored runs produced a transferable tier ===")

    if errs:
        print(f"\n=== {len(errs)} errored records ===")
        for r in errs[:8]:
            print(f"  {r['prompt']}/{r['query']}/{r['tool']}/{r['need']}: {r['error']}")


if __name__ == "__main__":
    main()
