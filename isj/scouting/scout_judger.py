"""Scout the Judger's serving throughput at a fixed concurrency level.

This is a *probe*, not part of `isj_agent` and not a test: it makes live network
calls to a vLLM (OpenAI-compatible) endpoint to find how many full-document judge
calls can run at once before KV cache saturates. One document per LLM call (the
pointwise-graded design); the knob under study is how many of those calls run
concurrently.

Workflow (TASK-16 scouting): run it for ONE concurrency level, read the
CLIENT-SIDE report it prints, then capture the vLLM-side metrics for that level
(`vllm:gpu_cache_usage_perc`, `vllm:num_requests_running` vs `_waiting`,
`vllm:num_preemptions_total`, any "out of KV cache" warnings). Then bump --concurrency
and repeat. Everything but --concurrency is held fixed across the sweep.

Documents + the intent + the cover-biased summaries come from a prior run-output dir
(default isj/runs/bear-e2e3): real ClimbMix documents at realistic sizes. The full
bodies are prefetched by docno BEFORE timing, so the measured wall-clock is the LLM
calls only. Each document is capped at --max-doc-chars (the candidate cap drives KV).

Usage (from the repo root), with vLLM serving the judge model:
    uv run --directory isj python scouting/scout_judger.py --concurrency 1
    uv run --directory isj python scouting/scout_judger.py --concurrency 2
    ...
Options: --run-dir, --intent-index, --sample N, --max-doc-chars, --reasoning-effort,
--model, --base-url, --config, --burrow, --query-bin.
"""

from __future__ import annotations

import argparse
import statistics
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from isj_agent.config import build_client
from isj_agent.fetch import fetch_text

# Repo root: scouting/ -> isj/ -> <repo>.
_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- the Judger prompt + schema under study (TASK-16 drafts, embedded) -----------

JUDGE_PROMPT = """\
You are assessing how well a DOCUMENT satisfies the information need behind a search
query, on a 0-3 relevance scale:
  0 - Irrelevant: the document has nothing to do with the query.
  1 - Related: on the query's topic, but does not answer it.
  2 - Partial: some of the answer, but incomplete, unclear, or buried among unrelated material.
  3 - Perfectly relevant: dedicated to the query, with a complete and direct answer.

Reason through these steps before grading:
1. Intent - what would actually satisfy the searcher: the need behind the query, not its
   surface words.
2. Topical match - how well the content the document ACTUALLY contains meets that need
   (coverage, directness, specificity). Grade on substance, never on keyword overlap or
   topical resemblance; a document can repeat the query's terms and answer nothing.
3. Trust - whether the content is credible enough to rely on (watch for spam, fabrication,
   promotional filler, internal contradiction, unsupported claims). Untrustworthy content
   does not satisfy the need however on-topic it appears; let low trust cap the grade.
4. Scope - judge the FULL document text below (it may be truncated). The representative
   passage is cover-biased orientation only; do not let one strong passage lift the grade if
   the rest of the document is thin.

QUESTION / INTENT:
{intent}

REPRESENTATIVE PASSAGE (orientation only - judge the full document, not just this):
{summary}

DOCUMENT:
{document}
"""


class Verdict(BaseModel):
    # reason BEFORE grade: guided decoding fills properties in declaration order.
    reason: str = Field(description="One to three sentences justifying the grade; cite a span.")
    grade: Literal[0, 1, 2, 3] = Field(
        description="0 irrelevant; 1 related-no-answer; 2 partial; 3 perfectly relevant. Low trust caps it."
    )


def _fill(intent: str, summary: str, document: str) -> str:
    # str.replace, NOT str.format -- document text can contain literal braces.
    return (
        JUDGE_PROMPT.replace("{intent}", intent)
        .replace("{summary}", summary)
        .replace("{document}", document)
    )


# --- config / inputs -------------------------------------------------------------

def _load_config(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else _REPO_ROOT / path


def _load_sample(run_dir: Path, intent_index: int) -> tuple[str, list[dict]]:
    """Return (intent_text, entries) from a run-output dir."""
    import json

    intents = json.loads((run_dir / "intents.json").read_text())
    intent = intents["interpretations"][intent_index]
    rl = json.loads((run_dir / f"intent-{intent_index:02d}.json").read_text())
    return intent, rl["entries"]


def _prefetch(entries: list[dict], burrow: Path, query_bin: Path, cap: int) -> list[dict]:
    """Fetch each entry's full body by docno (capped). Done BEFORE timing."""
    out: list[dict] = []
    for e in entries:
        try:
            body = fetch_text(burrow, e["docno"], query_bin)
        except (KeyError, RuntimeError) as exc:
            print(f"  warn: skipping {e['docno']}: {exc}")
            continue
        out.append({"docno": e["docno"], "summary": e["summary"], "document": body[:cap]})
    return out


# --- one judge call --------------------------------------------------------------

def _judge_one(client, model: str, intent: str, item: dict, reasoning_effort: str | None) -> dict:
    extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _fill(intent, item["summary"], item["document"])}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "Verdict", "schema": Verdict.model_json_schema()},
            },
            temperature=0.0,
            extra_body=extra,
        )
    except Exception as exc:  # surface the failure as data, do not abort the sweep
        return {"ok": False, "latency": time.time() - t0, "error": f"{type(exc).__name__}: {exc}"}
    dt = time.time() - t0
    usage = getattr(resp, "usage", None)
    content = resp.choices[0].message.content
    try:
        v = Verdict.model_validate_json(content)
        grade: int | None = v.grade
        verr = None
    except Exception as exc:
        grade, verr = None, f"verdict parse: {type(exc).__name__}: {exc}"
    return {
        "ok": verr is None,
        "latency": dt,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "grade": grade,
        "error": verr,
    }


# --- sweep one concurrency level -------------------------------------------------

def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    i = min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))
    return s[i]


def _report(concurrency: int, cap: int, model: str, reasoning: str | None,
            items: list[dict], results: list[dict], wall: float) -> None:
    ok = [r for r in results if r["ok"]]
    errs = [r for r in results if not r["ok"]]
    lat = [r["latency"] for r in results]
    busy = sum(lat)
    doc_chars = [len(it["document"]) for it in items]
    ptok = [r["prompt_tokens"] for r in ok if r.get("prompt_tokens")]
    ctok = [r["completion_tokens"] for r in ok if r.get("completion_tokens")]
    grades = [r["grade"] for r in ok if r["grade"] is not None]

    print("\n" + "=" * 70)
    print(f"JUDGER SCOUT  concurrency={concurrency}  model={model}"
          f"  reasoning_effort={reasoning or '(default)'}")
    print(f"sample={len(results)} docs  max_doc_chars={cap}")
    print("-" * 70)
    print(f"doc chars (after cap):  min {min(doc_chars)}  median {int(statistics.median(doc_chars))}"
          f"  max {max(doc_chars)}")
    if ptok:
        print(f"prompt tokens:          min {min(ptok)}  median {int(statistics.median(ptok))}"
              f"  max {max(ptok)}")
    if ctok:
        print(f"completion tokens:      min {min(ctok)}  median {int(statistics.median(ctok))}"
              f"  max {max(ctok)}")
    print("-" * 70)
    print(f"wall clock:             {wall:.2f}s   throughput: {len(results)/wall:.2f} docs/s")
    print(f"per-call latency (s):   min {min(lat):.2f}  p50 {_pct(lat,50):.2f}"
          f"  p95 {_pct(lat,95):.2f}  max {max(lat):.2f}")
    print(f"effective concurrency:  {busy/wall:.2f}   (target {concurrency}; "
          f"<< target => vLLM queued/serialized)")
    print(f"ok: {len(ok)}   errors: {len(errs)}")
    if errs:
        print(f"  first error: {errs[0]['error']}")
    if grades:
        dist = {g: grades.count(g) for g in sorted(set(grades))}
        print(f"grade distribution (sanity): {dist}")
    print("=" * 70)
    print(f">>> Now capture vLLM metrics for concurrency={concurrency} and paste them back:")
    print("    vllm:gpu_cache_usage_perc, num_requests_running vs _waiting,")
    print("    num_preemptions_total, and any 'out of KV cache' / OOM warnings.")
    print("=" * 70)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Scout Judger serving throughput at one concurrency level.")
    ap.add_argument("--concurrency", type=int, required=True, help="number of judge calls in flight")
    ap.add_argument("--run-dir", default="runs/bear-e2e3", help="run-output dir for docs+summaries")
    ap.add_argument("--intent-index", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0,
                    help="docs to judge (0 = auto = max(3*concurrency, 8), clamped to available)")
    ap.add_argument("--max-doc-chars", type=int, default=8000, help="candidate document cap (drives KV)")
    ap.add_argument("--reasoning-effort", default=None, help="gpt-oss reasoning effort (low/medium/high)")
    ap.add_argument("--model", default=None, help="override the [llm] model name")
    ap.add_argument("--base-url", default=None, help="override the [llm] base_url")
    ap.add_argument("--config", type=Path, default=_REPO_ROOT / "isj" / "config.toml")
    ap.add_argument("--burrow", default=None, help="override the served burrow")
    ap.add_argument("--query-bin", default=None, help="override the cottontail-jsonl-query path")
    args = ap.parse_args(argv)

    cfg = _load_config(args.config)
    llm = cfg["llm"]["default"]
    model = args.model or llm["model"]
    if args.base_url:
        llm = {**llm, "base_url": args.base_url}
    client = build_client(llm)

    burrow = _resolve(args.burrow or cfg["cottontail_http_json_server"]["burrow"])
    query_bin = _resolve(args.query_bin or cfg["query"]["binary"])
    run_dir = _resolve(args.run_dir) if not Path(args.run_dir).is_absolute() else Path(args.run_dir)
    if not run_dir.exists():  # also try relative to isj/
        run_dir = _REPO_ROOT / "isj" / args.run_dir

    intent, entries = _load_sample(run_dir, args.intent_index)
    n = args.sample or max(3 * args.concurrency, 8)
    n = min(n, len(entries))
    print(f"prefetching {n} documents by docno (capped at {args.max_doc_chars} chars)...")
    items = _prefetch(entries[:n], burrow, query_bin, args.max_doc_chars)
    if not items:
        raise SystemExit("no documents fetched -- check --burrow / --query-bin / the run dir")
    print(f"prefetched {len(items)} docs. intent: {intent[:80]}...")
    print(f"running {len(items)} judge calls at concurrency {args.concurrency}...")

    start = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(
            lambda it: _judge_one(client, model, intent, it, args.reasoning_effort), items
        ))
    wall = time.time() - start
    _report(args.concurrency, args.max_doc_chars, model, args.reasoning_effort, items, results, wall)


if __name__ == "__main__":
    main()
