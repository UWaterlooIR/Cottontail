import json
from types import SimpleNamespace

from isj_agent.agents.judger import JudgeCall
from isj_agent.agents.searcher import ProposeResult
from isj_agent.agents.tiered_searcher import TieredSearcher
from isj_agent.config import load_class
from isj_agent.controller import Controller
from isj_agent.engine.fake import FakeEngine
from isj_agent.protocol.queryable import TieredQuery
from isj_agent.protocol.search import AtomCount, Hit, SearchResponse, Verdict


# --- a stub OpenAI client returning one scripted assistant message ---------

def _tool_call(tiers, cid="c1"):
    return SimpleNamespace(
        id=cid, type="function",
        function=SimpleNamespace(name="tiered_query_search",
                                 arguments=json.dumps({"tiers": tiers})),
    )


def _response(message, ptok=140, ctok=9):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=("tool_calls" if message.tool_calls else "stop"))],
        usage=SimpleNamespace(prompt_tokens=ptok, completion_tokens=ctok, total_tokens=ptok + ctok),
    )


class StubClient:
    def __init__(self, message):
        self._message = message
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _response(self._message)


def _searcher(message):
    return TieredSearcher(StubClient(message), "stub-model")


# --- propose -----------------------------------------------------------------

def test_propose_returns_tiered_query_and_appendable_assistant_message():
    tiers = ["(>> (# 8) (^ a b))", "(^ a b)"]
    msg = SimpleNamespace(content="build a ladder", tool_calls=[_tool_call(tiers)])
    r = _searcher(msg).propose([{"role": "user", "content": "Question: bears"}])
    assert isinstance(r, ProposeResult)
    assert r.queryable == TieredQuery(tuple(tiers))
    assert r.queryable.query_string() == "(>> (# 8) (^ a b)) ; (^ a b)"
    assert r.content == "build a ladder"
    assert r.tool_call_id == "c1" and r.n_tool_calls == 1
    assert r.assistant_message["role"] == "assistant"
    assert r.assistant_message["tool_calls"][0]["function"]["name"] == "tiered_query_search"


def test_propose_forces_only_the_tiered_tool():
    s = _searcher(SimpleNamespace(content="", tool_calls=[_tool_call(["(^ a b)"])]))
    s.propose([{"role": "user", "content": "q"}])
    kwargs = s.client.calls[0]
    assert kwargs["tool_choice"] == "required"
    names = [t["function"]["name"] for t in kwargs["tools"]]
    assert names == ["tiered_query_search"]  # ONLY the tiered tool; no cover_search, no judge


def test_propose_forwards_reasoning_effort_and_usage():
    s = TieredSearcher(StubClient(SimpleNamespace(content="", tool_calls=[_tool_call(["(^ a)"])])),
                       "stub-model", reasoning_effort="high")
    r = s.propose([{"role": "user", "content": "q"}])
    assert s.client.calls[0]["extra_body"] == {"reasoning_effort": "high"}
    assert r.usage == {"prompt_tokens": 140, "completion_tokens": 9, "total_tokens": 149}


def test_malformed_tiers_yields_none_query():
    # known tool but bad arguments (a bare string, not a list) -> ValueError -> bounce
    bad = SimpleNamespace(id="c", type="function",
                          function=SimpleNamespace(name="tiered_query_search",
                                                   arguments=json.dumps({"tiers": "not a list"})))
    r = _searcher(SimpleNamespace(content="", tool_calls=[bad])).propose([{"role": "user", "content": "q"}])
    assert r.queryable is None


def test_unknown_tool_name_yields_none_query():
    # a call for a tool this searcher does not offer (cover_search) -> bounce
    other = SimpleNamespace(id="c", type="function",
                            function=SimpleNamespace(name="cover_search",
                                                     arguments=json.dumps({"query": "(^ a)"})))
    r = _searcher(SimpleNamespace(content="", tool_calls=[other])).propose([{"role": "user", "content": "q"}])
    assert r.queryable is None


def test_prompt_teaches_gcl_and_tiers_without_judging():
    p = TieredSearcher.prompt
    assert "GCL" in p
    assert "tier" in p.lower() and "cascade" in p.lower()
    assert "(+" in p  # the OR-group facet syntax
    assert "do not judge" in p.lower() or "you do not judge" in p.lower()


# --- config selectability (AC#1) --------------------------------------------

def test_selectable_via_load_class_and_constructs():
    # [agents.searcher].class resolves to TieredSearcher and constructs the same way
    # _build_agent does (client=, model=, plus optional kwargs) with no base changes.
    cls = load_class("isj_agent.agents.tiered_searcher.TieredSearcher")
    assert cls is TieredSearcher
    agent = cls(client=StubClient(SimpleNamespace(content="", tool_calls=None)),
                model="stub-model", reasoning_effort="high")
    assert isinstance(agent, TieredSearcher)
    assert agent.query_types == [TieredQuery]


# --- end-to-end: the REAL TieredSearcher through the UNCHANGED controller ----

class _StubJudger:
    concurrency = 8

    def judge(self, intent, docs):
        return [
            JudgeCall(verdict=Verdict(reason="ok", grade=3),
                      request=[{"role": "user", "content": document}],
                      content=json.dumps({"reason": "ok", "grade": 3}), reasoning="thinking")
            for _summary, document in docs
        ]


def test_real_tiered_searcher_runs_end_to_end_through_controller():
    # the model emits ONE tiered query; the controller executes it via the engine's
    # tiered_search and judges the merged results -- no controller/base change.
    tiers = ["(>> (# 8) (^ black bear*))", "(^ black bear*)"]
    client = StubClient(SimpleNamespace(content="", tool_calls=[_tool_call(tiers)]))
    searcher = TieredSearcher(client, "stub-model")
    resp = SearchResponse(
        total_matches=2, unjudged_matches=2,
        atom_counts=[AtomCount(term="bear*", count=9)],
        results=[Hit(rank=1, score=3000000.0, id="10", summary="s10"),
                 Hit(rank=2, score=2000000.0, id="20", summary="s20")],
    )
    engine = FakeEngine([resp], {"10": "body-10", "20": "body-20"})
    ctl = Controller(searcher, _StubJudger(), engine, nonrelevant_streak=9, max_queries=1)
    result = ctl.run("black bear safety", intent_budget=100)
    assert {e.id for e in result.ranked_list.entries} == {"10", "20"}
    # the controller drove tiered_search (its call carries a `tiers` key) with these tiers
    assert engine.calls[0]["tiers"] == tiers
    # surfacing_query is the joined tier string
    assert result.ranked_list.entries[0].surfacing_query == " ; ".join(tiers)
