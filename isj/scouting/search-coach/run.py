"""Scout the SearchCoach (see docs/design/search-coach.md).

Reconstructs each query's FAITHFUL top-25-by-rank slice from the run's TRACE (not the
compiled intent-NN.json), so it includes the already-judged docs a query re-surfaces
("revisits") with their cached grades -- exactly what the real coach would see
("always judged this query or cached as previously judged"). It then feeds that slice to
gpt.oss.120b with a versioned prompt + guided-output schema and SAVES the full transcript
-- input passages, the model's reasoning, and its raw output -- to captured/<prompt>/, so
the raw LLM behavior can be read, not just summaries.

VERSIONING: a version = a (prompt-vN.md, schema-vN.json) PAIR. BOTH affect the model --
the JSON schema's field names + `description` text are sent to vLLM for guided decoding
and steer behavior just like the prompt does. Never edit a version in place; add vN+1.
Results go to captured/<prompt-stem>/ so versions never mix.

Usage (from isj/, so the venv is picked up):
    uv run python scouting/search-coach/run.py <intent-NN.json> [--prompt prompt-vN.md]
                                               [--schema schema-vN.json] [--queries N] [--max-str N]
By default --schema is derived from --prompt (prompt-vN.md -> schema-vN.json).
"""
import argparse
import collections
import json
import pathlib

import openai

HERE = pathlib.Path(__file__).parent
CAPTURED = HERE / "captured"
INPUT_TOP_K, INPUT_MIN_GRADE = 25, 3


def slices_from_trace(trace_path):
    """Yield (query, slice) per proposed query. `slice` = the top INPUT_TOP_K judged docs
    by true rank (new OR revisit) + any deeper doc graded >= INPUT_MIN_GRADE. Each item:
    {docno, rank, score, summary, grade, reason, revisit}."""
    rows = [json.loads(l) for l in open(trace_path, encoding="utf-8") if l.strip()]
    judged = {}                       # docno -> (grade, reason) from every judge event (intent-global)
    for d in rows:
        if d["type"] == "judge":
            judged[d["docno"]] = (d["grade"], d.get("reason", ""))

    out = []
    cur = None
    results = []                      # this query's search hits, in rank order (across refills)
    revisited = set()                 # docnos re-encountered (already judged) under the current query

    def flush():
        if cur is None:
            return
        ranked, seen = [], set()
        for r in results:             # hits already come rank-ordered; dedupe, keep judged only
            dn = r["docno"]
            if dn in seen or dn not in judged:
                continue
            seen.add(dn)
            g, reason = judged[dn]
            ranked.append({"docno": dn, "rank": len(ranked) + 1, "score": r["score"],
                           "summary": r.get("summary", ""), "grade": g, "reason": reason,
                           "revisit": dn in revisited})
        top = ranked[:INPUT_TOP_K]
        deep = [x for x in ranked[INPUT_TOP_K:] if x["grade"] >= INPUT_MIN_GRADE]
        out.append((cur, top + deep))

    for d in rows:
        t = d["type"]
        if t == "propose":
            flush(); cur = d["query"]; results = []; revisited = set()
        elif t == "search" and cur is not None:
            results.extend(d.get("results", []))
        elif t == "revisit" and cur is not None:
            revisited.add(d["docno"])
    flush()
    return out


def run_one(client, prompt, schema, intent, sel, max_str):
    handles = {f"R{i + 1}": e for i, e in enumerate(sel)}
    # the coach is NOT told new-vs-revisit -- just judged passages with grades (per the design)
    passages = "\n".join(
        f"[{h}] grade={e['grade']}\n  reason: {e['reason'][:max_str]}\n  summary: {e['summary'][:max_str]}"
        for h, e in handles.items())
    resp = client.chat.completions.create(
        model="gpt.oss.120b",
        messages=[{"role": "user", "content": prompt.format(intent=intent, passages=passages)}],
        response_format={"type": "json_schema", "json_schema": {"name": "coach", "schema": schema}},
        temperature=0.0, max_tokens=8000, extra_body={"reasoning_effort": "medium"},
    )
    msg = resp.choices[0].message
    return handles, passages, msg.content, getattr(msg, "reasoning_content", None), resp.usage


def _parse(content):
    try:
        return json.loads(content or ""), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def transcript(intent, query, handles, passages, content, reasoning, usage):
    gd = dict(sorted(collections.Counter(e["grade"] for e in handles.values()).items()))
    nrev = sum(1 for e in handles.values() if e["revisit"])
    lines = ["# search-coach scout transcript (trace-reconstructed)", "",
             f"passages fed: {len(handles)}   grade dist: {gd}   revisits: {nrev}",
             f"coach tokens: {usage.prompt_tokens}+{usage.completion_tokens}", "",
             "## information need", intent, "",
             "## query that produced these results (NOT shown to the coach)", query, "",
             "## input passages fed to the coach  (rev = already-judged revisit)",
             "\n".join(f"[{h}] rank={e['rank']} grade={e['grade']}{' rev' if e['revisit'] else ''} {e['docno']}"
                       for h, e in handles.items()), "",
             "## input passages (verbatim, as sent)", passages, "",
             "## coach REASONING (raw reasoning_content)", (reasoning or "(none exposed)"), "",
             "## coach OUTPUT (raw JSON content)", (content or "(empty)"), ""]
    out, err = _parse(content)
    if err is not None:
        lines += ["## parsed", f"PARSE FAILED: {err}"]
        return "\n".join(lines) + "\n"
    sel = out.get("selected", []) if isinstance(out, dict) else []
    terms = out.get("recommended_terms", []) if isinstance(out, dict) else []
    obs = out.get("observations", "") if isinstance(out, dict) else ""
    picks = [f"{h}(r{handles[h]['rank']},g{handles[h]['grade']}{',rev' if handles[h]['revisit'] else ''})"
             for h in sel if h in handles]
    bad = [h for h in sel if h not in handles]
    gp = [handles[h]["grade"] for h in sel if h in handles]
    gmax = max((e["grade"] for e in handles.values()), default=None)
    lines += ["## parsed",
              f"selected {len(sel)}/{len(handles)}: " + ", ".join(picks),
              f"invalid handles: {bad if bad else 'none'}",
              f"grades of picks: {sorted(gp, reverse=True)}",
              f"max grade available: {gmax}; kept a top-grade doc? {'YES' if gp and max(gp) == gmax else 'NO'}",
              f"kept R1 or R2 (top-2 by rank)? {'YES' if ('R1' in sel or 'R2' in sel) else 'NO'}",
              "", "observations:", obs, "",
              f"recommended_terms ({len(terms)}):", ", ".join(terms)]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="path to a Searcher run's intent-NN.json (its .trace.jsonl is read alongside)")
    ap.add_argument("--prompt", default="prompt-v1.md",
                    help="prompt file (relative to this dir). Results go to captured/<prompt-stem>/.")
    ap.add_argument("--schema", default=None,
                    help="guided-output JSON schema file; default derives from --prompt (prompt-vN.md -> schema-vN.json)")
    ap.add_argument("--queries", type=int, default=99)
    ap.add_argument("--max-str", type=int, default=600)
    a = ap.parse_args()

    def _resolve(p):
        p = pathlib.Path(p)
        return p if p.is_absolute() else HERE / p

    prompt_path = _resolve(a.prompt)
    prompt = prompt_path.read_text(encoding="utf-8")
    schema_path = _resolve(a.schema) if a.schema else _resolve(a.prompt.replace("prompt-", "schema-").replace(".md", ".json"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    outdir = CAPTURED / prompt_path.stem            # one results dir PER PROMPT (never mixed)
    outdir.mkdir(parents=True, exist_ok=True)

    run = pathlib.Path(a.run)
    intent = json.load(open(run))["intent"]
    trace = run.parent / (run.stem + ".trace.jsonl")
    stem = run.parent.name + "-" + run.stem
    client = openai.OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="EMPTY")

    print(f"prompt: {prompt_path.name}   schema: {schema_path.name}   ->  captured/{outdir.name}/")
    print(f"intent: {intent}\ntrace: {trace}\n")
    for i, (q, sel) in enumerate(slices_from_trace(trace)):
        if i >= a.queries:
            break
        if not sel:
            print(f"q{i:02d}: (no judged results)   {q[:60]}"); continue
        handles, passages, content, reasoning, usage = run_one(client, prompt, schema, intent, sel, a.max_str)
        out_md = outdir / f"{stem}-q{i:02d}.md"
        out_md.write_text(transcript(intent, q, handles, passages, content, reasoning, usage), encoding="utf-8")
        nrev = sum(1 for e in sel if e["revisit"])
        gmax = max(e["grade"] for e in sel)
        parsed, err = _parse(content)
        if err is not None or not isinstance(parsed, dict):
            print(f"q{i:02d}: PARSE FAILED   [{out_md.name}]"); continue
        selh = parsed.get("selected", [])
        gp = [handles[h]["grade"] for h in selh if h in handles]
        kept_top = bool(gp) and max(gp) == gmax
        whiff = "  <-- WHIFF: dropped the top-grade doc" if not kept_top else ""
        print(f"q{i:02d}: fed {len(handles):2d} (rev {nrev:2d}, gmax {gmax}) -> selected {len(selh):2d} "
              f"grades={sorted(gp, reverse=True)} kept_top={kept_top} terms={len(parsed.get('recommended_terms', []))}"
              f"{whiff}   [{out_md.name}]")


if __name__ == "__main__":
    main()
