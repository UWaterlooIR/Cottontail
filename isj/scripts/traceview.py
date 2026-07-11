#!/usr/bin/env python3
"""Human-readable viewer for isj run traces (``intent-NN.trace.jsonl``).

The controller writes one JSON object per line, and those objects carry huge
embedded strings -- full system prompts, judged document text, model reasoning.
``jq`` pretty-prints the structure but leaves those strings as one-line,
``\\n``-escaped blobs. This tool renders embedded newlines as real newlines and
word-wraps long strings so a trace is actually readable.

Stdlib only -- runs under any ``python3`` (no venv needed).

Usage:
    python isj/scripts/traceview.py FILE [--list-types] [--width N] [--type T[,T...]]
                                    [--purpose P[,P...]] [--max-str N] [--no-request]

Examples:
    # what event types are in this file?
    python isj/scripts/traceview.py intent-00.trace.jsonl --list-types

    # everything, wrapped, in a pager
    python isj/scripts/traceview.py intent-00.trace.jsonl | less -R

    # just the judge verdicts, without the bulky request field
    python isj/scripts/traceview.py intent-00.trace.jsonl --type judge --no-request

    # ALL the searcher's calls (llm_call with purpose=searcher_turn)
    python isj/scripts/traceview.py intent-00.trace.jsonl --purpose searcher_turn --no-request

The bulkiest field is ``request`` (it re-embeds the whole system prompt plus the
accumulated conversation on every turn); ``--no-request`` drops it. Tip: the live
``activity.log`` next to the trace is already human-readable for a quick overview --
reach for this when you need the full structured detail of a specific event.
"""

from __future__ import annotations  # keep type hints lazy so it runs on older python3

import argparse
import collections
import json
import signal
import textwrap

# Behave like a normal Unix filter when piped into head/less and the reader closes
# the pipe early: die on SIGPIPE instead of dumping a BrokenPipeError traceback.
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError):  # SIGPIPE is POSIX-only; ignore elsewhere
    pass

# A string is treated as a "text block" (rendered multi-line + wrapped) when it is
# long or contains newlines; shorter scalars print inline.
_BLOCK_MIN = 72

# The event types the controller emits, for --help and --list-types. Keep in sync with
# isj_agent/controller.py (emit(...) calls). llm_call carries a `purpose`.
_TYPE_DOC = {
    "llm_call": "an LLM round-trip (purpose=searcher_turn: query authoring; purpose=judge: one document's grading)",
    "propose": "the query the searcher proposed this turn",
    "search_request": "a fetch about to be sent to the engine (query, top_k, exclude)",
    "search": "the engine's response (results, total_matches, atom_counts, latency)",
    "judge": "a NEW document's grade + reason",
    "revisit": "a previously-judged doc re-encountered (grade only, not re-judged)",
    "judge_failed": "a judge call that failed after retries (recorded as grade -2)",
    "list_exhausted": "the non-relevant streak tripped; descent of this query stopped",
    "bounce": "a self-correction bounce (kind=engine_error: bad GCL; kind=no_query: no usable query)",
    "stop": "the intent ended (reason=intent_budget | max_queries)",
    "error": "a caught failure (searcher LLM error / JudgeFailure)",
}


def _list_types(path: str) -> None:
    """Print the event types present in the file, with counts (and purpose breakdown
    for llm_call), so a reader knows what to pass to --type."""
    counts: collections.Counter = collections.Counter()
    purposes: collections.Counter = collections.Counter()
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        t = d.get("type", "?")
        counts[t] += 1
        if t == "llm_call":
            purposes[d.get("purpose", "?")] += 1
    print(f"event types in {path}:\n")
    for t, n in counts.most_common():
        print(f"  {t:<15} {n:>6}   {_TYPE_DOC.get(t, '')}")
        if t == "llm_call":
            for p, pn in purposes.most_common():
                print(f"    {'purpose='+p:<13} {pn:>6}")
    print('\nfilter with:  --type ' + ",".join(sorted(counts)))
    if purposes:
        print('the llm_call events split by --purpose ' + ",".join(sorted(purposes))
              + '   (e.g. searcher calls: --purpose searcher_turn)')


def _wrap(s: str, width: int, pad: str) -> list[str]:
    out: list[str] = []
    for para in s.split("\n"):
        out += textwrap.wrap(para, max(1, width - len(pad))) or [""]
    return out


def _show(v, width: int, ind: int, maxstr: int) -> None:
    pad = "  " * ind
    if isinstance(v, dict):
        for k, val in v.items():
            head = f"{pad}{k}:"
            if isinstance(val, (dict, list)) and val:
                print(head)
                _show(val, width, ind + 1, maxstr)
            elif isinstance(val, str) and (len(val) > _BLOCK_MIN or "\n" in val):
                shown = val if len(val) <= maxstr else val[:maxstr] + f" …[+{len(val) - maxstr} chars]"
                print(head)
                for ln in _wrap(shown, width, pad + "    "):
                    print(f"{pad}    {ln}")
            else:
                print(f"{head} {val!r}" if isinstance(val, str) else f"{head} {val}")
    elif isinstance(v, list):
        for i, val in enumerate(v):
            if isinstance(val, (dict, list)):
                print(f"{pad}[{i}]")
                _show(val, width, ind + 1, maxstr)
            else:
                print(f"{pad}[{i}] {val!r}" if isinstance(val, str) else f"{pad}[{i}] {val}")


def main(argv: list[str] | None = None) -> None:
    epilog = "event types (pass to --type; run --list-types to see which are in YOUR file):\n"
    epilog += "\n".join(f"  {t:<15} {doc}" for t, doc in _TYPE_DOC.items())
    ap = argparse.ArgumentParser(
        description="Pretty-print an isj *.trace.jsonl for human reading (newlines + word wrap).",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("file", help="path to an intent-NN.trace.jsonl")
    ap.add_argument("--list-types", action="store_true",
                    help="print the event types (with counts) present in FILE, then exit")
    ap.add_argument("--width", type=int, default=100, help="wrap width (default 100)")
    ap.add_argument("--type", default=None,
                    help="only show these event types, comma-separated (e.g. search,judge)")
    ap.add_argument("--purpose", default=None,
                    help="only show llm_call events with these purposes, comma-separated "
                         "(searcher_turn = the searcher's calls; judge = the judger's)")
    ap.add_argument("--max-str", type=int, default=100_000,
                    help="truncate any string longer than this many chars")
    ap.add_argument("--no-request", action="store_true",
                    help="drop the bulky `request` field (the re-embedded prompt/history)")
    a = ap.parse_args(argv)

    if a.list_types:
        _list_types(a.file)
        return

    types = set(a.type.split(",")) if a.type else None
    purposes = set(a.purpose.split(",")) if a.purpose else None
    if types or purposes:  # warn on a typo so a silent empty result isn't mistaken for "none"
        seen_t: set = set()
        seen_p: set = set()
        for line in open(a.file, encoding="utf-8"):
            if not line.strip():
                continue
            o = json.loads(line)
            seen_t.add(o.get("type"))
            if o.get("purpose"):
                seen_p.add(o.get("purpose"))
        if types and types - seen_t:
            print(f"# note: no events of type {sorted(types - seen_t)} in this file; "
                  f"present: {sorted(seen_t)}")
        if purposes and purposes - seen_p:
            print(f"# note: no llm_call with purpose {sorted(purposes - seen_p)} in this file; "
                  f"present: {sorted(seen_p)}")
    with open(a.file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if types and d.get("type") not in types:
                continue
            if purposes and d.get("purpose") not in purposes:
                continue
            if a.no_request:
                d.pop("request", None)
            # a compact one-line header for the event, then the full record
            head = f'━━ {d.get("type", "?")}'
            for k in ("purpose", "turn", "query", "grade", "docno"):
                if k in d and not isinstance(d[k], (dict, list)):
                    head += f"  {k}={d[k]!r}"
            print("\n" + head[: a.width])
            _show(d, a.width, 1, a.max_str)


if __name__ == "__main__":
    main()
