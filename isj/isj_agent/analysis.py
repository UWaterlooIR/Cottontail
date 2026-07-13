"""Analyst-output artifact: a reusable per-topic analysis report (TASK-41).

An artifact decouples the Analyst from the searcher run, so ONE analysis per topic can drive
many searcher-agent runs -- factoring analyst variation out of cross-searcher comparisons. Any
Analyst (today's `Analyst`, the `ReportAnalyst`, future ones) produces the same shape; the isj
CLI consumes it via --analysis-file and skips its own Analyst. One JSON file per topic:

    {"topic_id": "14",
     "question": "...",
     "interpretations": ["...", "..."],
     "analyst": {"class": "...", "model": "...", "reasoning_effort": "medium", "temperature": 0.0}}

`interpretations` is the same list the Controller consumes, whether the entries are
disambiguations (Analyst) or report components (ReportAnalyst) -- nothing downstream changes.
"""
from __future__ import annotations

import json
from pathlib import Path

from isj_agent.protocol.intents import Intents


def write_report(out_dir: Path, topic_id: str, intents: Intents, analyst_meta: dict) -> Path:
    """Write one topic's analysis artifact to <out_dir>/<topic_id>.json; return the path."""
    data = {
        "topic_id": topic_id,
        "question": intents.question,
        "interpretations": intents.interpretations,
        "analyst": analyst_meta,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{topic_id}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_report(path: Path) -> tuple[str, Intents]:
    """Read an analysis artifact -> (topic_id, Intents). Intents validates the non-empty list."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d["topic_id"], Intents(question=d["question"], interpretations=d["interpretations"])
