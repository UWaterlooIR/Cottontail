"""Scout the SearchCoach (see docs/design/search-coach.md).

Reconstructs each query's FAITHFUL top-25-by-rank slice from the run's TRACE (not the
compiled intent-NN.json), so it includes the already-judged docs a query re-surfaces
("revisits") with their cached grades -- exactly what the real coach would see
("always judged this query or cached as previously judged"). It then feeds that slice to
gpt.oss.120b with a versioned prompt (+ optional guided-output schema) and SAVES the full
transcript -- input passages, the model's reasoning, and its raw output -- to
captured/<prompt>/, so the raw LLM behavior can be read, not just summaries.

VERSIONING: a version = a (prompt-vN.md, schema-vN.json) PAIR when guided decoding is
used -- BOTH affect the model: the JSON schema's field names + `description` text are
sent to vLLM for guided decoding and steer behavior just like the prompt does. From v3 a
version may be prompt-ONLY (free-text report, no guided decoding): if no schema file
exists for the prompt (and none is given), the coach runs unguided and the transcript's
"parsed" section is computed from the [Rn] handles the report CITES. Never edit a
version in place; add vN+1. Results go to captured/<prompt-stem>/ so versions never mix.

Usage (from isj/, so the venv is picked up):
    uv run python scouting/search-coach/run.py <intent-NN.json> [--prompt prompt-vN.md]
                                               [--schema schema-vN.json] [--queries N] [--max-str N]
By default --schema is derived from --prompt (prompt-vN.md -> schema-vN.json); if that
file does not exist, the run is free-text (no response_format).
"""
import argparse
import collections
import json
import pathlib
import re

import openai

HERE = pathlib.Path(__file__).parent
CAPTURED = HERE / "captured"
INPUT_TOP_K, INPUT_MIN_GRADE = 25, 3
HANDLE_RE = re.compile(r"\[(R\d+)\]")


def slices_from_trace(trace_path):
    """Yield (query, slice, novelty) per proposed query. `slice` = the top INPUT_TOP_K judged
    docs by true rank (new OR revisit) + any deeper doc graded >= INPUT_MIN_GRADE. Each item:
    {docno, rank, score, summary, grade, reason, revisit}. `novelty` = this query's descent-wide
    counts {new, seen, total_matches} -- what the production coach's RESULT NOVELTY line reports."""
    rows = [json.loads(l) for l in open(trace_path, encoding="utf-8") if l.strip()]
    judged = {}                       # docno -> (grade, reason) from every judge event (intent-global)
    for d in rows:
        if d["type"] == "judge":
            judged[d["docno"]] = (d["grade"], d.get("reason", ""))

    out = []
    cur = None
    results = []                      # this query's search hits, in rank order (across refills)
    revisited = set()                 # docnos re-encountered (already judged) under the current query
    new_count = 0                     # NEW judgments made under the current query
    tmatches = None                   # total corpus matches reported for the current query

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
        out.append((cur, top + deep,
                    {"new": new_count, "seen": len(revisited), "total_matches": tmatches}))

    for d in rows:
        t = d["type"]
        if t == "propose":
            flush(); cur = d["query"]; results = []; revisited = set(); new_count = 0; tmatches = None
        elif t == "search" and cur is not None:
            results.extend(d.get("results", []))
            if d.get("total_matches") is not None:
                tmatches = d["total_matches"]
        elif t == "judge" and cur is not None:
            new_count += 1
        elif t == "revisit" and cur is not None:
            revisited.add(d["docno"])
    flush()
    return out


def novelty_line(nov):
    """Reproduce the production coach's RESULT NOVELTY line (see search_coach._novelty_line)."""
    total = nov["new"] + nov["seen"]
    if total == 0:
        return "This query surfaced no results."
    line = (f"This query judged {total} result(s): {nov['new']} newly surfaced and "
            f"{nov['seen']} already judged on earlier queries (revisits).")
    if nov["total_matches"] is not None:
        line += f" The collection holds {nov['total_matches']} document(s) matching this query."
    return line


def run_one(client, prompt, schema, intent, sel, nov, max_str, hide_revisit_text=False):
    handles = {f"R{i + 1}": e for i, e in enumerate(sel)}
    # Novelty-aware ONLY if the prompt asks for it (has a {novelty} placeholder, i.e. v7+). This
    # keeps a v6 run byte-identical to before -- fair v6-vs-v7 comparison -- while v7 gets the
    # revisit markers + RESULT NOVELTY line exactly as production (search_coach.SearchCoachAgent).
    novelty_aware = "{novelty}" in prompt

    def render(h, e):
        rev = novelty_aware and e["revisit"]
        # v8 philosophy (--revisit-text hide): withhold the TEXT of an already-judged doc entirely,
        # so the coach can't keep re-analyzing content it has already seen -- only the grade + a
        # "resurfaced" marker, steering it harder toward NEW ground.
        if rev and hide_revisit_text:
            return f"[{h}] grade={e['grade']}  (resurfaced document: already judged on an earlier query)"
        mark = "  (already judged on an earlier query)" if rev else ""
        return (f"[{h}] grade={e['grade']}{mark}"
                f"\n  reason: {e['reason'][:max_str]}\n  summary: {e['summary'][:max_str]}")

    passages = "\n".join(render(h, e) for h, e in handles.items())
    novelty_shown = novelty_line(nov) if novelty_aware else None
    content = (prompt.replace("{intent}", intent).replace("{passages}", passages))
    if novelty_aware:
        content = content.replace("{novelty}", novelty_shown)
    kwargs = {}
    if schema is not None:            # guided decoding (v1/v2); v3+ free-text runs without it
        kwargs["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "coach", "schema": schema}}
    resp = client.chat.completions.create(
        model="gpt.oss.120b",
        messages=[{"role": "user", "content": content}],
        temperature=0.0, max_tokens=8000, extra_body={"reasoning_effort": "medium"},
        **kwargs,
    )
    msg = resp.choices[0].message
    return handles, passages, novelty_shown, msg.content, getattr(msg, "reasoning_content", None), resp.usage


def _parse(content):
    try:
        return json.loads(content or ""), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _cited(content, handles):
    """Handles cited in a free-text report, in first-mention order, deduped; plus any
    bracketed handle-like tokens that do not exist in the input (hallucinated)."""
    seen, cited, bad = set(), [], []
    for h in HANDLE_RE.findall(content or ""):
        if h in seen:
            continue
        seen.add(h)
        (cited if h in handles else bad).append(h)
    return cited, bad


def _pick_stats(lines, handles, sel, bad):
    """Shared 'parsed' diagnostics over a list of selected/cited handles."""
    picks = [f"{h}(r{handles[h]['rank']},g{handles[h]['grade']}{',rev' if handles[h]['revisit'] else ''})"
             for h in sel]
    gp = [handles[h]["grade"] for h in sel]
    gmax = max((e["grade"] for e in handles.values()), default=None)
    lines += [f"selected {len(sel)}/{len(handles)}: " + ", ".join(picks),
              f"invalid handles: {bad if bad else 'none'}",
              f"grades of picks: {sorted(gp, reverse=True)}",
              f"max grade available: {gmax}; kept a top-grade doc? {'YES' if gp and max(gp) == gmax else 'NO'}",
              f"kept R1 or R2 (top-2 by rank)? {'YES' if ('R1' in sel or 'R2' in sel) else 'NO'}"]
    return gp, gmax


def transcript(intent, query, handles, passages, novelty_shown, content, reasoning, usage, guided):
    gd = dict(sorted(collections.Counter(e["grade"] for e in handles.values()).items()))
    nrev = sum(1 for e in handles.values() if e["revisit"])
    lines = ["# search-coach scout transcript (trace-reconstructed)", "",
             f"passages fed: {len(handles)}   grade dist: {gd}   revisits: {nrev}",
             f"coach tokens: {usage.prompt_tokens}+{usage.completion_tokens}   mode: {'guided-json' if guided else 'free-text'}", "",
             "## RESULT NOVELTY line shown to the coach", (novelty_shown or "(not shown -- prompt is not novelty-aware)"), "",
             "## information need", intent, "",
             "## query that produced these results (NOT shown to the coach)", query, "",
             "## input passages fed to the coach  (rev = already-judged revisit)",
             "\n".join(f"[{h}] rank={e['rank']} grade={e['grade']}{' rev' if e['revisit'] else ''} {e['docno']}"
                       for h, e in handles.items()), "",
             "## input passages (verbatim, as sent)", passages, "",
             "## coach REASONING (raw reasoning_content)", (reasoning or "(none exposed)"), "",
             "## coach OUTPUT (raw)", (content or "(empty)"), ""]
    if not guided:                    # free-text report: selection = the handles the report cites
        cited, bad = _cited(content, handles)
        lines += ["## parsed (from citations in the report)"]
        _pick_stats(lines, handles, cited, bad)
        lines += [f"report words: {len((content or '').split())}"]
        return "\n".join(lines) + "\n"
    out, err = _parse(content)
    if err is not None:
        lines += ["## parsed", f"PARSE FAILED: {err}"]
        return "\n".join(lines) + "\n"
    sel = out.get("selected", []) if isinstance(out, dict) else []
    terms = out.get("recommended_terms", []) if isinstance(out, dict) else []
    obs = out.get("observations", "") if isinstance(out, dict) else ""
    lines += ["## parsed"]
    _pick_stats(lines, handles, [h for h in sel if h in handles], [h for h in sel if h not in handles])
    lines += ["", "observations:", obs, "",
              f"recommended_terms ({len(terms)}):", ", ".join(terms)]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="path to a Searcher run's intent-NN.json (its .trace.jsonl is read alongside)")
    ap.add_argument("--prompt", default="prompt-v1.md",
                    help="prompt file (relative to this dir). Results go to captured/<prompt-stem>/.")
    ap.add_argument("--schema", default=None,
                    help="guided-output JSON schema file; default derives from --prompt (prompt-vN.md -> "
                         "schema-vN.json). If the derived file does not exist, runs free-text (no guided decoding).")
    ap.add_argument("--queries", type=int, default=99)
    ap.add_argument("--query", type=int, default=None, help="run ONLY this slice index (0-based)")
    ap.add_argument("--revisit-text", choices=("show", "hide"), default="show",
                    help="hide = withhold the reason/summary TEXT of already-judged revisits (v8 philosophy)")
    ap.add_argument("--max-str", type=int, default=600)
    a = ap.parse_args()

    def _resolve(p):
        p = pathlib.Path(p)
        return p if p.is_absolute() else HERE / p

    prompt_path = _resolve(a.prompt)
    prompt = prompt_path.read_text(encoding="utf-8")
    if a.schema:                      # explicit schema: must exist
        schema_path = _resolve(a.schema)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    else:                             # derived schema: guided iff the file exists
        schema_path = _resolve(a.prompt.replace("prompt-", "schema-").replace(".md", ".json"))
        schema = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.exists() else None
    guided = schema is not None
    outdir = CAPTURED / prompt_path.stem            # one results dir PER PROMPT (never mixed)
    outdir.mkdir(parents=True, exist_ok=True)

    run = pathlib.Path(a.run)
    intent = json.load(open(run))["intent"]
    trace = run.parent / (run.stem + ".trace.jsonl")
    # method-topic-intent, so e.g. gcl-cover/14 and multitext/14 never collide
    stem = f"{run.parent.parent.name}-{run.parent.name}-{run.stem}"
    client = openai.OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="EMPTY")

    print(f"prompt: {prompt_path.name}   schema: {schema_path.name if guided else '(none -- free-text report)'}"
          f"   ->  captured/{outdir.name}/")
    print(f"intent: {intent}\ntrace: {trace}\n")
    for i, (q, sel, nov) in enumerate(slices_from_trace(trace)):
        if a.query is not None and i != a.query:
            continue
        if a.query is None and i >= a.queries:
            break
        if not sel:
            print(f"q{i:02d}: (no judged results)   {q[:60]}"); continue
        handles, passages, novelty_shown, content, reasoning, usage = run_one(
            client, prompt, schema, intent, sel, nov, a.max_str, hide_revisit_text=(a.revisit_text == "hide"))
        out_md = outdir / f"{stem}-q{i:02d}.md"
        out_md.write_text(transcript(intent, q, handles, passages, novelty_shown, content, reasoning, usage, guided),
                          encoding="utf-8")
        nrev = sum(1 for e in sel if e["revisit"])
        gmax = max(e["grade"] for e in sel)
        if not guided:
            cited, bad = _cited(content, handles)
            gp = [handles[h]["grade"] for h in cited]
            kept_top = bool(gp) and max(gp) == gmax
            whiff = "  <-- WHIFF: report never cites a top-grade doc" if not kept_top else ""
            print(f"q{i:02d}: fed {len(handles):2d} (rev {nrev:2d}, gmax {gmax}) -> cited {len(cited):2d} "
                  f"grades={sorted(gp, reverse=True)} kept_top={kept_top} words={len((content or '').split())}"
                  f"{' bad_handles=' + str(bad) if bad else ''}{whiff}   [{out_md.name}]")
            continue
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
