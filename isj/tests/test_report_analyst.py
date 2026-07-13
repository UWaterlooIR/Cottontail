"""ReportAnalyst tests (TASK-42): a bundled report-component prompt over the Analyst contract.

The class differs from Analyst only in its bundled prompt; it must still parse into the same
`Intents{question, interpretations[]}` and be selectable via `build_analyst`.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from isj_agent.agents.analyst import Analyst
from isj_agent.agents.report_analyst import ReportAnalyst
from isj_agent.config import build_analyst, load_class
from isj_agent.protocol.intents import Intents


def test_report_analyst_is_an_analyst_subclass():
    assert issubclass(ReportAnalyst, Analyst)


def test_report_analyst_bundles_the_report_prompt():
    # distinctive phrase unique to the report prompt (prompt-report-v4.md; absent from analyst.md)
    assert "report will be built from" in ReportAnalyst.prompt
    assert ReportAnalyst.prompt != Analyst.prompt


def test_load_class_resolves_report_analyst():
    assert load_class("isj_agent.agents.report_analyst.ReportAnalyst") is ReportAnalyst


def test_analyze_parses_components_into_intents():
    client = MagicMock()
    content = json.dumps({"question": "q", "interpretations": ["c1", "c2", "c3"]})
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
    result = ReportAnalyst(client=client, model="m").analyze("q")

    assert result == Intents(question="q", interpretations=["c1", "c2", "c3"])
    # the report prompt is the system message it sent
    sent = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "report will be built from" in sent


def test_build_analyst_constructs_a_report_analyst():
    config = {
        "agents": {"analyst": {"class": "isj_agent.agents.report_analyst.ReportAnalyst", "llm": "default"}},
        "llm": {"default": {"model": "m", "base_url": "http://127.0.0.1:8000/v1"}},
    }
    clients = {"default": MagicMock()}
    analyst = build_analyst(config, clients, config["llm"])
    assert isinstance(analyst, ReportAnalyst)
    assert analyst.model == "m"
