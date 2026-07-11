"""The isj Searcher CLI (C3): one question in, a run-output directory out.

    python -m isj_agent.cli --question "<q>" --out <dir> [--overwrite] [--verbose] [--burrow <path>]

Wires the whole pipeline from config.toml: Analyst -> per-intent Searcher (over the
live engine) -> a StreamingRunWriter. A single flag-based entry, no subcommands, one
question per run.

Output is written to <out>/ INCREMENTALLY as the run proceeds (TASK-35): tail
<out>/activity.log to watch activity live (queries, searches, per-doc judgements, and
'awaiting LLM'/'awaiting judge' markers so a hung or looping call is visible instead
of silence). The absence of <out>/errors.log means the whole run succeeded; the CLI
exits non-zero if it was written. --verbose additionally mirrors activity.log to stdout.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from isj_agent.config import (
    build_client,
    build_engine,
    load_class,
)
from isj_agent.controller import Controller
from isj_agent.orchestrator import Orchestrator
from isj_agent.run_output import Outcome, RunError, StreamingRunWriter


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="isj_agent.cli",
        description="Run the ISJ Searcher pipeline on one question -> a run-output directory.",
    )
    parser.add_argument("--question", required=True, help="the question to investigate")
    parser.add_argument("--out", required=True, type=Path, help="run-output directory")
    parser.add_argument("--overwrite", action="store_true", help="overwrite a non-empty --out")
    parser.add_argument("--verbose", action="store_true", help="render each intent's events live")
    parser.add_argument("--burrow", help="override the served burrow (for the cp<->docno map)")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent.parent / "config.toml",
        help="path to config.toml (default: isj/config.toml)",
    )
    args = parser.parse_args(argv)

    if not args.config.exists():
        raise FileNotFoundError(
            f"config file not found: {args.config}\n"
            f"Copy config.example.toml to {args.config} and edit as needed."
        )
    with args.config.open("rb") as f:
        config = tomllib.load(f)

    llm_configs = config["llm"]
    agent_configs = config["agents"]
    clients = {name: build_client(cfg) for name, cfg in llm_configs.items()}

    def _build_agent(role: str, **extra):
        cfg = agent_configs[role]
        cls = load_class(cfg["class"])
        return cls(client=clients[cfg["llm"]], model=llm_configs[cfg["llm"]]["model"], **extra)

    analyst_cfg = agent_configs["analyst"]
    analyst = _build_agent(
        "analyst",
        **{k: analyst_cfg[k] for k in ("reasoning_effort", "max_tokens", "timeout_s") if k in analyst_cfg},
    )
    searcher_cfg = agent_configs["searcher"]
    judger_cfg = agent_configs["judger"]
    searcher = _build_agent(
        "searcher",
        **{k: searcher_cfg[k] for k in ("reasoning_effort", "temperature", "prompt", "max_tokens", "timeout_s") if k in searcher_cfg},
    )
    judger = _build_agent(
        "judger",
        **{k: judger_cfg[k] for k in ("concurrency", "reasoning_effort", "temperature", "max_tokens", "timeout_s") if k in judger_cfg},
    )
    engine = build_engine(config, burrow_override=args.burrow)
    loop_cfg = config.get("loop", {})
    controller = Controller(
        searcher, judger, engine,
        fetch_k=searcher_cfg.get("fetch_k", 200),
        window=searcher_cfg.get("window", 75),
        max_queries=searcher_cfg.get("max_queries", 100),
        nonrelevant_streak=loop_cfg.get("nonrelevant_streak", 5),
        relevant_grade_threshold=loop_cfg.get("relevant_grade_threshold", 1),
        max_doc_chars=loop_cfg.get("max_doc_chars", 50000),
        max_list_depth=loop_cfg.get("max_list_depth"),
        top_results_to_show=loop_cfg.get("top_results_to_show", 10),
        min_show_grade=loop_cfg.get("min_show_grade", 3),
    )

    orchestrator = Orchestrator(
        analyst, controller, max_judgments=loop_cfg.get("max_judgments", 1000)
    )
    # Open the run directory up front (created if missing; fail fast if non-empty and
    # not --overwrite) so activity streams to <out>/activity.log as the run proceeds.
    writer = StreamingRunWriter(args.out, overwrite=args.overwrite, echo=args.verbose)
    intents, outcomes, run_error = orchestrator.run_question(
        args.question,
        on_analyzed=writer.start,
        observer=writer.observe,
        on_intent=writer.finish_intent,
    )
    writer.finish(run_error=run_error)

    def _failed(o: Outcome) -> bool:
        # a per-intent RunError, or a SearcherResult that ended on a caught failure
        return isinstance(o, RunError) or getattr(o, "error", None) is not None

    n = len(intents.interpretations) if intents is not None else 0
    failed = sum(1 for o in outcomes if _failed(o)) + (1 if run_error else 0)
    succeeded = sum(1 for o in outcomes if not _failed(o))
    print(
        f"\nrun: {args.out}  interpretations={n}  succeeded={succeeded}  failed={failed}"
    )
    if failed:
        print(f"errors.log written -> {args.out / 'errors.log'}")
        sys.exit(1)


if __name__ == "__main__":
    main()
