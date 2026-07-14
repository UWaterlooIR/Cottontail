"""isj analyze: run a configured Analyst over a topics TSV -> one artifact per topic (TASK-41).

    python -m isj_agent.analyze --topics <tsv> --out <dir> [--config config.toml]
        [--overwrite] [--only ID ...] [--limit N]

Produces a reusable analysis directory: <out>/<topic_id>.json per topic (the shape in
isj_agent.analysis) plus <out>/analysis.meta.json (provenance). The isj CLI then consumes a
topic's artifact via --analysis-file, so ONE analysis drives many searcher configs and analyst
variation is factored out of cross-searcher comparisons.

The analyst is [agents.analyst] from the config (Analyst, ReportAnalyst, ...). Needs only the
vLLM endpoint (no search engine / shards). RESUMABLE: a topic whose <id>.json already exists is
skipped unless --overwrite.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tomllib
from pathlib import Path

from isj_agent.analysis import write_report
from isj_agent.config import analyst_meta, build_analyst, build_client


def read_topics(path: Path) -> list[tuple[str, str]]:
    """Read a 2-col (topic_id, question) TSV. Skips blank lines / short rows."""
    out: list[tuple[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) >= 2 and row[0].strip():
                out.append((row[0].strip(), row[1]))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="isj_agent.analyze",
        description="Run the configured Analyst over a topics TSV -> one analysis artifact per topic.",
    )
    ap.add_argument("--topics", required=True, type=Path, help="2-col topics TSV (id\\tquestion)")
    ap.add_argument("--out", required=True, type=Path, help="output analysis directory")
    ap.add_argument("--config", type=Path, default=Path(__file__).parent.parent / "config.toml",
                    help="path to config.toml (default: isj/config.toml)")
    ap.add_argument("--only", action="append", default=[], help="analyze only this topic id (repeatable)")
    ap.add_argument("--limit", type=int, help="analyze only the first N topics")
    ap.add_argument("--overwrite", action="store_true", help="re-analyze topics whose <id>.json exists")
    args = ap.parse_args(argv)

    if not args.config.exists():
        raise FileNotFoundError(
            f"config file not found: {args.config}\n"
            f"Copy config.example.toml to {args.config} and edit as needed."
        )
    with args.config.open("rb") as f:
        config = tomllib.load(f)
    llm_configs = config["llm"]
    clients = {name: build_client(cfg) for name, cfg in llm_configs.items()}

    analyst = build_analyst(config, clients, llm_configs)
    meta = analyst_meta(config, llm_configs)

    topics = read_topics(args.topics)
    if args.only:
        topics = [(i, q) for i, q in topics if i in set(args.only)]
    if args.limit is not None:
        topics = topics[: args.limit]
    if not topics:
        sys.exit("no topics selected")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "analysis.meta.json").write_text(
        json.dumps({"analyst": meta, "topics_file": str(args.topics), "config": str(args.config)},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"{len(topics)} topic(s) -> {args.out}  (analyst: {meta['class']})")

    done = skipped = failed = 0
    for n, (tid, question) in enumerate(topics, 1):
        dest = args.out / f"{tid}.json"
        if dest.exists() and not args.overwrite:
            print(f"[{n}/{len(topics)}] {tid}: SKIP (exists)")
            skipped += 1
            continue
        try:
            intents = analyst.analyze(question)
        except Exception as exc:
            print(f"[{n}/{len(topics)}] {tid}: FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
            failed += 1
            continue
        write_report(args.out, tid, intents, meta)
        print(f"[{n}/{len(topics)}] {tid}: ok ({len(intents.interpretations)} interpretation(s))")
        done += 1

    print(f"\ndone: analyzed={done} skipped={skipped} failed={failed}  -> {args.out}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
