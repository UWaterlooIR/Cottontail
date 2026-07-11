#!/usr/bin/env python3
"""Human-readable viewer for isj run traces (``intent-NN.trace.jsonl``).

The controller writes one JSON object per line, and those objects carry huge
embedded strings -- full system prompts, judged document text, model reasoning.
``jq`` pretty-prints the structure but leaves those strings as one-line,
``\\n``-escaped blobs. This tool renders embedded newlines as real newlines and
word-wraps long strings so a trace is actually readable.

Stdlib only -- runs under any ``python3`` (no venv needed).

Usage:
    python isj/scripts/traceview.py FILE [--width N] [--type T[,T...]]
                                    [--max-str N] [--no-request]

Examples:
    # everything, wrapped, in a pager
    python isj/scripts/traceview.py intent-00.trace.jsonl | less -R

    # just the judge verdicts, without the bulky request field
    python isj/scripts/traceview.py intent-00.trace.jsonl --type judge --no-request

    # searcher turns, truncating any string over 800 chars
    python isj/scripts/traceview.py intent-00.trace.jsonl --type llm_call --max-str 800

The bulkiest field is ``request`` (it re-embeds the whole system prompt plus the
accumulated conversation on every turn); ``--no-request`` drops it. Tip: the live
``activity.log`` next to the trace is already human-readable for a quick overview --
reach for this when you need the full structured detail of a specific event.
"""

from __future__ import annotations  # keep type hints lazy so it runs on older python3

import argparse
import json
import signal
import sys
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
    ap = argparse.ArgumentParser(
        description="Pretty-print an isj *.trace.jsonl for human reading (newlines + word wrap).",
    )
    ap.add_argument("file", help="path to an intent-NN.trace.jsonl")
    ap.add_argument("--width", type=int, default=100, help="wrap width (default 100)")
    ap.add_argument("--type", default=None,
                    help="only show these event types, comma-separated (e.g. search,judge)")
    ap.add_argument("--max-str", type=int, default=100_000,
                    help="truncate any string longer than this many chars")
    ap.add_argument("--no-request", action="store_true",
                    help="drop the bulky `request` field (the re-embedded prompt/history)")
    a = ap.parse_args(argv)

    types = set(a.type.split(",")) if a.type else None
    with open(a.file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if types and d.get("type") not in types:
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
