"""MultiTextTieredSearcher (TASK-22): the DSL-program searcher over the
unchanged BaseSearcher/Controller, incl. the compile-error bounce e2e."""

import json
from types import SimpleNamespace

from isj_agent.agents.judger import JudgeCall
from isj_agent.agents.mt_tiered_searcher import MultiTextTieredSearcher
from isj_agent.agents.searcher import ProposeResult
from isj_agent.config import load_class
from isj_agent.controller import Controller
from isj_agent.engine.base import EngineError
from isj_agent.engine.fake import FakeEngine
from isj_agent.protocol.queryable import MultiTextProgram
from isj_agent.protocol.search import AtomCount, Hit, SearchResponse, Verdict

PROGRAM = 'b0 = "black" <> "bear*"\nb1 = "bear*"\nq0 = b0 ^ b1\n@rank q0 b1\n'


def _tool_call(program, cid="c1"):
    return SimpleNamespace(
        id=cid, type="function",
        function=SimpleNamespace(name="submit_tiered_query",
                                 arguments=json.dumps({"program": program})),
    )


def _response(message):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message,
                                 finish_reason=("tool_calls" if message.tool_calls else "stop"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


class StubClient:
    def __init__(self, messages):
        self._messages = list(messages)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _response(self._messages.pop(0) if len(self._messages) > 1
                         else self._messages[0])


def _searcher(*messages):
    return MultiTextTieredSearcher(StubClient(messages), "stub-model")


def test_propose_returns_program_and_appendable_assistant_message():
    msg = SimpleNamespace(content="ladder", tool_calls=[_tool_call(PROGRAM)])
    r = _searcher(msg).propose([{"role": "user", "content": "Question: bears"}])
    assert isinstance(r, ProposeResult)
    assert r.queryable == MultiTextProgram(PROGRAM)
    assert r.queryable.query_string() == PROGRAM
    assert r.assistant_message["tool_calls"][0]["function"]["name"] == "submit_tiered_query"


def test_propose_forces_only_the_program_tool():
    s = _searcher(SimpleNamespace(content="", tool_calls=[_tool_call(PROGRAM)]))
    s.propose([{"role": "user", "content": "q"}])
    kwargs = s.client.calls[0]
    assert kwargs["tool_choice"] == "required"
    assert [t["function"]["name"] for t in kwargs["tools"]] == ["submit_tiered_query"]


def test_malformed_program_yields_none_query():
    bad = SimpleNamespace(id="c", type="function",
                          function=SimpleNamespace(name="submit_tiered_query",
                                                   arguments=json.dumps({"program": ""})))
    r = _searcher(SimpleNamespace(content="", tool_calls=[bad])).propose(
        [{"role": "user", "content": "q"}])
    assert r.queryable is None


def test_prompt_is_the_validated_multiturn_librarian():
    p = MultiTextTieredSearcher.prompt
    assert "@rank" in p
    assert "NO underscores" in p                    # the S1 macro-name rule
    assert '"word*"' in p                           # the S2 stem rule
    assert "Do NOT write" in p and "< [N]" in p     # the proximity-join idiom
    assert "<top>" not in p                         # no TREC markup (anti-loop)


def test_selectable_via_load_class_and_constructs():
    cls = load_class("isj_agent.agents.mt_tiered_searcher.MultiTextTieredSearcher")
    assert cls is MultiTextTieredSearcher
    agent = cls(client=StubClient([SimpleNamespace(content="", tool_calls=None)]),
                model="stub-model")
    assert agent.query_types == [MultiTextProgram]


class _StubJudger:
    concurrency = 8

    def judge(self, intent, docs):
        return [
            JudgeCall(verdict=Verdict(reason="ok", grade=3),
                      request=[{"role": "user", "content": document}],
                      content=json.dumps({"reason": "ok", "grade": 3}), reasoning="r")
            for _summary, document in docs
        ]


def test_real_searcher_runs_end_to_end_through_controller():
    client = StubClient([SimpleNamespace(content="", tool_calls=[_tool_call(PROGRAM)])])
    searcher = MultiTextTieredSearcher(client, "stub-model")
    resp = SearchResponse(
        total_matches=2, unjudged_matches=2,
        atom_counts=[AtomCount(term="bear*", count=9)],
        results=[Hit(rank=1, score=3.0, cp=10, summary="s10"),
                 Hit(rank=2, score=2.0, cp=20, summary="s20")],
    )
    engine = FakeEngine([resp], {10: "body-10", 20: "body-20"})
    ctl = Controller(searcher, _StubJudger(), engine, nonrelevant_streak=9, max_queries=1)
    result = ctl.run("black bear safety", intent_budget=100)
    assert {e.cp for e in result.ranked_list.entries} == {10, 20}
    # the controller drove multitext_search (its call carries a `program` key)
    assert engine.calls[0]["program"] == PROGRAM
    assert result.ranked_list.entries[0].surfacing_query == PROGRAM


def test_compile_error_bounces_diagnostics_to_the_next_turn():
    # Turn 1: a program the "server" rejects (scripted EngineError standing in for
    # the compiler diagnostics). Turn 2: a fixed program that runs. The controller
    # must feed the diagnostics back as the tool result and continue -- no
    # controller/base changes.
    diagnostics = "DEF ERR q_0 = \"bear\": Undefined symbol. [mt.cc:736]"
    bad_call = SimpleNamespace(content="", tool_calls=[_tool_call('q_0 = "bear"\n@rank q_0\n', "c1")])
    good_call = SimpleNamespace(content="", tool_calls=[_tool_call(PROGRAM, "c2")])
    client = StubClient([bad_call, good_call])
    searcher = MultiTextTieredSearcher(client, "stub-model")
    ok = SearchResponse(total_matches=1, unjudged_matches=1,
                        atom_counts=[AtomCount(term="bear*", count=9)],
                        results=[Hit(rank=1, score=1.0, cp=10, summary="s10")])
    engine = FakeEngine([EngineError(diagnostics), ok], {10: "body-10"})
    ctl = Controller(searcher, _StubJudger(), engine, nonrelevant_streak=9, max_queries=2)
    result = ctl.run("black bear safety", intent_budget=100)
    # the bounce surfaced the diagnostics as the tool result of turn 1
    tool_results = [m for m in client.calls[1]["messages"] if m.get("role") == "tool"]

    def carries_diagnostics(content):
        try:
            return json.loads(content).get("error") == diagnostics
        except (json.JSONDecodeError, AttributeError):
            return diagnostics in content
    assert any(carries_diagnostics(m["content"]) for m in tool_results)
    # and the run recovered: turn 2's program produced the judged doc
    assert {e.cp for e in result.ranked_list.entries} == {10}
