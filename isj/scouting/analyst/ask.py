#!/usr/bin/env python3
"""Run an Analyst prompt on ONE question from the command line (gpt.oss.120b on vLLM).

Usage (from isj/, so the venv is picked up):
    uv run python scouting/analyst/ask.py "<your question>" [--prompt prompt-report-v1.md]
        [--model gpt.oss.120b] [--base-url http://127.0.0.1:8000/v1] [--reasoning medium]
        [--temperature 0.0] [--json]

Defaults to prompt-report-v1.md. Prints the numbered components; --json dumps the raw
Intents object. Needs only the vLLM endpoint (no search engine / shards).
"""
from __future__ import annotations

import argparse
import pathlib
import textwrap

import openai

from isj_agent.agents.analyst import Analyst

HERE = pathlib.Path(__file__).parent


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question", help="the information need to analyze (quote it)")
    ap.add_argument("--prompt", type=pathlib.Path, default=HERE / "prompt-report-v1.md",
                    help="prompt file (default prompt-report-v1.md)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="gpt.oss.120b")
    ap.add_argument("--reasoning", default="medium")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--json", action="store_true", help="print the raw Intents JSON instead")
    args = ap.parse_args(argv)

    prompt = args.prompt.read_text(encoding="utf-8") if args.prompt.is_absolute() \
        else (HERE / args.prompt).read_text(encoding="utf-8")

    client = openai.OpenAI(base_url=args.base_url, api_key="EMPTY")
    analyst = Analyst(client, args.model, reasoning_effort=args.reasoning, temperature=args.temperature)
    analyst.prompt = prompt  # override the bundled analyst.md with this variant

    intents = analyst.analyze(args.question)

    if args.json:
        print(intents.model_dump_json(indent=2))
        return

    comps = intents.interpretations
    print(f"# prompt={args.prompt.name}  model={args.model}  reasoning={args.reasoning}  "
          f"temp={args.temperature}  -> {len(comps)} component(s)\n")
    print(textwrap.fill(f"need: {args.question}", 96) + "\n")
    for i, c in enumerate(comps, 1):
        print(textwrap.indent(textwrap.fill(c, 92), f"  {i:2d}. ").replace(f"  {i:2d}. ", f"  {i:2d}. ", 1))


if __name__ == "__main__":
    main()
