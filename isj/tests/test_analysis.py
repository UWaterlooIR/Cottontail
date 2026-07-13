"""Analysis-artifact round-trip tests (TASK-41): write_report / load_report.

The artifact is the decoupling contract -- one Analyst output per topic, reused across searcher
runs -- so the shape and the round-trip must stay stable.
"""

import json

import pytest
from pydantic import ValidationError

from isj_agent.analysis import load_report, write_report
from isj_agent.protocol.intents import Intents

_META = {"class": "isj_agent.agents.analyst.Analyst", "model": "gpt.oss.120b",
         "reasoning_effort": "medium", "temperature": 0.0}


def test_write_then_load_round_trips(tmp_path):
    intents = Intents(question="What is X?", interpretations=["reading one", "reading two"])
    path = write_report(tmp_path, "14", intents, _META)
    assert path == tmp_path / "14.json"

    topic_id, loaded = load_report(path)
    assert topic_id == "14"
    assert loaded.question == "What is X?"
    assert loaded.interpretations == ["reading one", "reading two"]


def test_written_file_has_the_documented_shape(tmp_path):
    intents = Intents(question="q", interpretations=["a"])
    path = write_report(tmp_path, "rag2026-0", intents, _META)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"topic_id": "rag2026-0", "question": "q",
                    "interpretations": ["a"], "analyst": _META}


def test_write_creates_the_out_dir(tmp_path):
    out = tmp_path / "nested" / "analysis"
    write_report(out, "1", Intents(question="q", interpretations=["a"]), _META)
    assert (out / "1.json").exists()


def test_non_ascii_survives_the_round_trip(tmp_path):
    intents = Intents(question="Qué es el café?", interpretations=["el café ☕"])
    _, loaded = load_report(write_report(tmp_path, "7", intents, _META))
    assert loaded.question == "Qué es el café?"
    assert loaded.interpretations == ["el café ☕"]


def test_load_rejects_an_empty_interpretations_list(tmp_path):
    # Intents enforces a non-empty list; a corrupt artifact must fail loudly, not silently pass.
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"topic_id": "1", "question": "q", "interpretations": []}),
                   encoding="utf-8")
    with pytest.raises(ValidationError):
        load_report(bad)
