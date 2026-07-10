"""Orchestrator tests (C3): Analyst -> per-intent Searcher, no network.

Stubs stand in for both agents; the contract under test is run_question's
ordering, per-intent error isolation, run-level failure, the on_intent callback,
and that its (intents, outcomes, run_error) plug straight into write_run.
"""

import json

from isj_agent.orchestrator import Orchestrator
from isj_agent.protocol.intents import Intents
from isj_agent.protocol.results import RankedEntry, RankedList, SearcherResult
from isj_agent.run_output import RunError, write_run


def _result(intent):
    rl = RankedList(intent=intent, entries=[
        RankedEntry(rank=1, id="100", grade=3, score=5.0, summary="s", reason="r", surfacing_query="(^ a*)"),
    ])
    return SearcherResult(ranked_list=rl, events=[])


class StubAnalyst:
    def __init__(self, intents=None, raises=None):
        self._intents = intents
        self._raises = raises

    def analyze(self, question):
        if self._raises is not None:
            raise self._raises
        return self._intents


class StubController:
    def __init__(self, behavior):
        self.behavior = behavior  # interp -> SearcherResult | Exception
        self.calls = []
        self.budgets = []

    def run(self, interp, intent_budget):
        self.calls.append(interp)
        self.budgets.append(intent_budget)
        b = self.behavior[interp]
        if isinstance(b, Exception):
            raise b
        return b


def test_one_outcome_per_interp_in_order():
    intents = Intents(question="Q?", interpretations=["alpha", "beta"])
    controller = StubController({"alpha": _result("alpha"), "beta": _result("beta")})
    orch = Orchestrator(analyst=StubAnalyst(intents=intents), controller=controller)

    got_intents, outcomes, run_error = orch.run_question("Q?")
    assert got_intents is intents
    assert run_error is None
    assert controller.calls == ["alpha", "beta"]  # in order
    assert [o.ranked_list.intent for o in outcomes] == ["alpha", "beta"]


def test_failed_intent_becomes_runerror_and_continues():
    intents = Intents(question="Q?", interpretations=["good", "bad", "good2"])
    controller = StubController({
        "good": _result("good"),
        "bad": RuntimeError("engine exploded"),
        "good2": _result("good2"),
    })
    orch = Orchestrator(analyst=StubAnalyst(intents=intents), controller=controller)

    _, outcomes, run_error = orch.run_question("Q?")
    assert run_error is None
    assert controller.calls == ["good", "bad", "good2"]  # one failure didn't abort the rest
    assert isinstance(outcomes[0], SearcherResult)
    assert isinstance(outcomes[1], RunError)
    assert "engine exploded" in outcomes[1].message
    assert isinstance(outcomes[2], SearcherResult)


def test_run_total_budget_split_evenly_across_intents():
    intents = Intents(question="Q?", interpretations=["a", "b"])
    controller = StubController({"a": _result("a"), "b": _result("b")})
    orch = Orchestrator(analyst=StubAnalyst(intents=intents), controller=controller, max_judgments=1000)
    orch.run_question("Q?")
    assert controller.budgets == [500, 500]  # 1000 // 2


def test_budget_floor_division_and_min_one():
    intents = Intents(question="Q?", interpretations=["a", "b", "c"])
    controller = StubController({"a": _result("a"), "b": _result("b"), "c": _result("c")})
    orch = Orchestrator(analyst=StubAnalyst(intents=intents), controller=controller, max_judgments=1000)
    orch.run_question("Q?")
    assert controller.budgets == [333, 333, 333]  # floor(1000/3); remainder not reallocated


def test_analysis_failure_returns_none():
    orch = Orchestrator(
        analyst=StubAnalyst(raises=ValueError("bad question")),
        controller=StubController({}),
    )
    intents, outcomes, run_error = orch.run_question("Q?")
    assert intents is None
    assert outcomes == []
    assert "bad question" in run_error


def test_on_intent_called_per_interp():
    intents = Intents(question="Q?", interpretations=["alpha", "beta"])
    controller = StubController({"alpha": _result("alpha"), "beta": RuntimeError("x")})
    orch = Orchestrator(analyst=StubAnalyst(intents=intents), controller=controller)

    seen = []
    orch.run_question("Q?", on_intent=lambda i, interp, outcome: seen.append((i, interp, type(outcome).__name__)))
    assert seen == [(0, "alpha", "SearcherResult"), (1, "beta", "RunError")]


def test_outputs_plug_into_write_run(tmp_path):
    intents = Intents(question="Q?", interpretations=["good", "bad"])
    controller = StubController({"good": _result("good"), "bad": RuntimeError("boom")})
    orch = Orchestrator(analyst=StubAnalyst(intents=intents), controller=controller)

    got_intents, outcomes, run_error = orch.run_question("Q?")
    out = tmp_path / "run"
    write_run(out, got_intents, outcomes, run_error=run_error)

    assert (out / "intent-00.json").exists()
    assert not (out / "intent-01.json").exists()  # the failed intent has no ranked list
    assert "intent 01 (bad): RuntimeError: boom" in (out / "errors.log").read_text()
    rl = json.loads((out / "intent-00.json").read_text())
    assert rl["entries"][0]["docno"] == "100"  # id is the docno; written under `docno`


def test_analysis_failure_plugs_into_write_run(tmp_path):
    orch = Orchestrator(
        analyst=StubAnalyst(raises=ValueError("nope")),
        controller=StubController({}),
    )
    intents, outcomes, run_error = orch.run_question("Q?")
    out = tmp_path / "run"
    write_run(out, intents, outcomes, run_error=run_error)
    assert not (out / "intents.json").exists()
    assert "run-level error:" in (out / "errors.log").read_text()
