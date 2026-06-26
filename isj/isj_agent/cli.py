"""The isj Searcher CLI (C3): one question in, a run-output directory out.

    python -m isj_agent.cli --question "<q>" --out <dir> [--overwrite] [--verbose] [--burrow <path>]

Wires the whole pipeline from config.toml: Analyst -> per-intent Searcher (over the
live HttpSearchEngine) -> write_run. A single flag-based entry, no subcommands, one
question per run. The absence of <out>/errors.log means the whole run succeeded;
the CLI exits non-zero if it was written.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from isj_agent.config import (
    build_client,
    build_docno_map,
    build_search_engine,
    load_class,
)
from isj_agent.orchestrator import Orchestrator
from isj_agent.run_output import Outcome, RunError, write_run


def _render_event(ev) -> None:
    d = ev.model_dump()
    t = d.get("type")
    if t == "llm_call":
        pt, ct = d.get("prompt_tokens"), d.get("completion_tokens")
        toks = f" tokens={pt}+{ct}" if pt is not None else ""
        print(
            f"    turn {d['turn']}: tool={d['tool']} finish={d.get('finish_reason')}"
            f"{toks} ({d['duration_ms']:.0f} ms)"
        )
        if d.get("content") and d["content"].strip():
            print(f"      reasoning: {d['content'].strip()}")
        for c in d.get("calls", []):
            print(f"      -> {c['name']}({c['arguments']})")
    elif t == "error":
        pt = d.get("prompt_tokens")
        size = f" (prompt_tokens={pt})" if pt is not None else ""
        print(f"    ERROR turn {d.get('turn')}: {d.get('error_type')}: {d.get('message')}{size}")
    elif t == "search_request":
        print(f"    -> request: {d['query']!r} (exclude={len(d.get('exclude', []))})")
    elif t == "search":
        print(
            f"    search {d['query']!r}: total={d['total_matches']} "
            f"returned={len(d.get('results', []))} exclude={len(d.get('exclude', []))} "
            f"({d['duration_ms']:.0f} ms)"
        )
    elif t == "judge":
        print(f"    judge: recorded={d['recorded']} grades={[j['grade'] for j in d.get('judgements', [])]}")
    elif t == "bounce":
        print(f"    bounce[{d['kind']}]: {d['message']}")
    elif t == "stop":
        print(f"    stop: {d['reason']}")


def _make_on_intent(verbose: bool):
    if not verbose:
        return None

    def on_intent(i: int, interp: str, outcome: Outcome) -> None:
        print(f"\n[intent {i:02d}] {interp}")
        if isinstance(outcome, RunError):
            print(f"    FAILED: {outcome.message}")
        else:
            for ev in outcome.events:
                _render_event(ev)
            note = f" (PARTIAL: {outcome.error})" if outcome.error else ""
            print(f"    -> {len(outcome.ranked_list.entries)} judged passages{note}")

    return on_intent


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

    analyst = _build_agent("analyst")
    engine = build_search_engine(config["cottontail_http_json_server"])
    searcher_cfg = agent_configs["searcher"]
    knobs = {k: searcher_cfg[k] for k in ("top_k", "window", "max_turns") if k in searcher_cfg}
    searcher = _build_agent("searcher", engine=engine, **knobs)

    docno_map = build_docno_map(
        config["cottontail_http_json_server"], burrow_override=args.burrow
    )

    orchestrator = Orchestrator(analyst=analyst, searcher=searcher)
    intents, outcomes, run_error = orchestrator.run_question(
        args.question, on_intent=_make_on_intent(args.verbose)
    )
    write_run(
        args.out, intents, outcomes,
        docno_map=docno_map, run_error=run_error, overwrite=args.overwrite,
    )

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
