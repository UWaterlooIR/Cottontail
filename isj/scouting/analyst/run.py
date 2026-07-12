"""Scout the Analyst: run a prompt variant over the dev topics and SHOW what it generates.

Motivation: on dev topic 14 the Analyst over-decomposed (3 interpretations vs a good 2) and
emitted a source-type-framed intent ("identify books, reports, or academic papers ...") that
sent the searcher into a 100-turn dead end. This harness lets us try prompt variants and eyeball
the interpretations they produce, over the 22 RAG25 dev topics.

Needs only vLLM (the Analyst is one LLM call, no search) -- so it runs even with the shard
array down.

VERSIONING (mirrors the other scouts): never edit a prompt in place; add prompt-vN+1.md.
prompt-v1.md is a snapshot of the shipped isj_agent/agents/analyst.md. Raw Intents JSON per
(topic, repeat) is saved under captured/<prompt-stem>/ so runs never mix.

Usage (from isj/, so the venv is picked up):
    uv run python scouting/analyst/run.py [--prompt prompt-vN.md] [--only 14] [--limit N]
                                          [--repeats R] [--model gpt.oss.120b]
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import textwrap

import openai

from isj_agent.agents.analyst import Analyst

HERE = pathlib.Path(__file__).parent
CAPTURED = HERE / "captured"

# Advisory flag: interpretations framed around finding a SOURCE/CONTAINER type rather than the
# content need -- the GCL-14 anti-pattern. Not a hard rule; we eyeball what it catches.
SOURCE_TERMS = [
    "book", "report", "paper", "journal", "article", "scholarly", "academic",
    "handbook", "monograph", "publication", "peer-review", "peer review",
    "literature", "thesis", "dissertation", "white paper", "study", "studies",
]
_SRC_RE = re.compile("|".join(re.escape(t) for t in SOURCE_TERMS), re.I)


def read_topics(path: pathlib.Path) -> list[tuple[str, str]]:
    out = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) >= 2 and row[0].strip():
                out.append((row[0].strip(), row[1]))
    return out


def source_flags(interp: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _SRC_RE.finditer(interp)})


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", type=pathlib.Path, default=HERE / "prompt-v1.md",
                    help="prompt variant file (default prompt-v1.md = shipped analyst.md)")
    ap.add_argument("--topics", type=pathlib.Path, default=HERE / "dev-topics.tsv")
    ap.add_argument("--only", action="append", default=[], help="run only this topic id (repeatable)")
    ap.add_argument("--limit", type=int, help="run only the first N topics")
    ap.add_argument("--repeats", type=int, default=1, help="runs per topic (temp-0 stability probe)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="gpt.oss.120b")
    ap.add_argument("--reasoning", default="medium")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--no-save", action="store_true", help="don't write captured/ transcripts")
    args = ap.parse_args(argv)

    prompt_text = args.prompt.read_text(encoding="utf-8")
    stem = args.prompt.stem
    outdir = CAPTURED / stem
    if not args.no_save:
        outdir.mkdir(parents=True, exist_ok=True)

    topics = read_topics(args.topics)
    if args.only:
        topics = [(i, q) for i, q in topics if i in set(args.only)]
    if args.limit is not None:
        topics = topics[: args.limit]

    client = openai.OpenAI(base_url=args.base_url, api_key="EMPTY")
    analyst = Analyst(client, args.model, reasoning_effort=args.reasoning, temperature=args.temperature)
    analyst.prompt = prompt_text  # override the bundled analyst.md with this variant

    print(f"# analyst scout — prompt={args.prompt.name}  model={args.model}  "
          f"reasoning={args.reasoning}  temp={args.temperature}  topics={len(topics)}  repeats={args.repeats}\n")

    counts: dict[str, list[int]] = {}   # topic -> [interp count per repeat]
    n_source = 0
    n_interps = 0
    for tid, question in topics:
        counts[tid] = []
        for r in range(args.repeats):
            intents = analyst.analyze(question)
            interps = intents.interpretations
            counts[tid].append(len(interps))
            tag = f"  (repeat {r + 1})" if args.repeats > 1 else ""
            print(f"── topic {tid}{tag}  [{len(interps)} interpretation(s)]")
            print(textwrap.indent(textwrap.fill(question, 96), "   Q: ").replace("   Q: ", "   Q: ", 1))
            for k, s in enumerate(interps, 1):
                flags = source_flags(s)
                n_interps += 1
                mark = f"   ⚑ source-type: {', '.join(flags)}" if flags else ""
                if flags:
                    n_source += 1
                print(textwrap.indent(textwrap.fill(s, 92), f"   [{k}] ").replace(f"   [{k}] ", f"   [{k}] ", 1))
                if mark:
                    print(mark)
            print()
            if not args.no_save:
                name = f"{tid}.json" if args.repeats == 1 else f"{tid}-r{r + 1}.json"
                (outdir / name).write_text(intents.model_dump_json(indent=2), encoding="utf-8")

    # summary
    from collections import Counter
    dist = Counter(n for cs in counts.values() for n in cs)
    print("=" * 70)
    print("SUMMARY")
    print(f"  interpretation-count distribution: "
          + ", ".join(f"{k}→{v}" for k, v in sorted(dist.items())))
    print(f"  source-type-flagged interpretations: {n_source}/{n_interps}")
    if args.repeats > 1:
        unstable = {t: cs for t, cs in counts.items() if len(set(cs)) > 1}
        print(f"  topics whose interp COUNT varied across repeats: {len(unstable)}/{len(counts)}"
              + (f"  -> {', '.join(f'{t}:{cs}' for t, cs in unstable.items())}" if unstable else ""))
    if not args.no_save:
        print(f"  transcripts: {outdir}")


if __name__ == "__main__":
    main()
