"""TASK-28 pre-scout on the 100M burrow (Mark, 2026-07-04).

Replays the documented phrase-pathology cases from
docs/design/phrase-followedby-repro/ against the live 100M server, plain vs
materialize-wrapped (hand-wrapped quoted phrases -- the TASK-28 rewrite done
textually), plus a summary-phase penalty probe (a broad query with many
results: the CLI/server use ONE query string for both ranking and per-doc
summary re-walks, so a wrapped broad query directly measures the per-document
re-materialization cost that TASK-28's two-form design avoids).

Client timeouts are DISABLED (Mark). Sequential; JSONL + stdout capture.
Run: uv run --directory isj python scouting/multitext-dsl-2/run_materialize_100m.py
"""

import json
import re
import time
from pathlib import Path

import httpx

S = "http://127.0.0.1:8080"
HERE = Path(__file__).parent
OUT = HERE / "results" / "materialize-100m.jsonl"

A = '(+ backpack* hiker* trekker*)'
B1 = '(+ bear* "black bear*" "grizzly*")'
C1 = '(+ food* store* "food storage" "food cache*")'
D1 = '(+ canister* hanging* "campsite selection" "site selection")'
B2 = '(+ bear* "black bear*" "grizzly*" "bear-resistant")'
C2 = '(+ food* store* "food storage" "food cache*" "food protection")'
D2 = '(+ canister* hanging* "campsite selection" "site selection" "camp placement")'


def AND(*f):
    return '(^ ' + ' '.join(f) + ')'


def wrap(q: str) -> str:
    """Hand version of the TASK-28 rewrite: wrap quoted MULTI-WORD phrases
    (space inside the quotes) in (materialize ...), token-boundary safe."""
    return re.sub(r'(?<![\w*])"([^"]+ [^"]+)"', r'(materialize "\1")', q)


# The broad summary-penalty probe: plenty of matches AND a phrase, so a wrapped
# run pays the per-doc re-materialization in the summary phase (top_k=200 docs).
BROAD = '(^ bear* food* (+ canister* "food storage"))'

CASES = [
    ("tier1 plain (warmup/baseline)", AND(A, B1, C1, D1), False),
    ("+camp placement plain (documented ~650s)", AND(A, B1, C1, D2), False),
    ("+camp placement WRAPPED", wrap(AND(A, B1, C1, D2)), False),
    ("tier2 all-three WRAPPED", wrap(AND(A, B2, C2, D2)), False),
    ("reversed-phrase facet WRAPPED",
     wrap(AND(A, B1, C1, '(+ canister* "selection campsite")')), False),
    ("broad plain (summary probe)", BROAD, False),
    ("broad WRAPPED (summary probe)", wrap(BROAD), False),
    ('"camp placement" standalone plain', '"camp placement"', False),
    ('"camp placement" standalone WRAPPED', wrap('"camp placement"'), False),
]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = httpx.Client(timeout=None)
    with OUT.open("a") as f:
        for label, q, _ in CASES:
            t0 = time.time()
            rec = {"label": label, "query": q}
            try:
                r = c.post(S + "/tools/cover_search",
                           json={"query": q, "top_k": 200})
                rec["status"] = r.status_code
                if r.status_code == 200:
                    d = r.json()
                    rec["total_matches"] = d.get("total_matches")
                    rec["n_results"] = len(d.get("results", []))
                else:
                    rec["error"] = r.text[:200]
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
            rec["elapsed_s"] = round(time.time() - t0, 1)
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(f"{label:45} {rec['elapsed_s']:>8}s  matches={rec.get('total_matches')} "
                  f"results={rec.get('n_results')} status={rec.get('status')}",
                  flush=True)
    print("done ->", OUT, flush=True)


if __name__ == "__main__":
    main()
