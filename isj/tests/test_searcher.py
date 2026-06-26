import json
from types import SimpleNamespace

from isj_agent.agents.searcher import Searcher
from isj_agent.engine.base import EngineError
from isj_agent.engine.fake import FakeEngine
from isj_agent.protocol.search import AtomCount, Hit, SearchResponse


# --- a stub OpenAI client: chat.completions.create returns scripted turns ----

def _tool_call(name, args, cid="c"):
    return SimpleNamespace(
        id=cid, type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _msg(content="", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def search_turn(query, cid="c"):
    return _msg(tool_calls=[_tool_call("search", {"query": query}, cid)])


def judge_turn(judgements, cid="c"):
    return _msg(tool_calls=[_tool_call("judge", {"judgements": judgements}, cid)])


def stop_turn(content="done"):
    return _msg(content=content, tool_calls=None)


class StubLLM:
    def __init__(self, turns):
        self._turns = list(turns)
        self._i = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        if self._i < len(self._turns):
            msg = self._turns[self._i]
            self._i += 1
        else:
            msg = stop_turn()
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _resp(hits, total=None, unjudged=None):
    """hits: list of (cp, score, summary)."""
    results = [Hit(rank=i, score=s, cp=cp, summary=sm) for i, (cp, s, sm) in enumerate(hits, 1)]
    return SearchResponse(
        total_matches=total if total is not None else len(hits),
        unjudged_matches=unjudged if unjudged is not None else len(hits),
        atom_counts=[AtomCount(term="bear*", count=9)],
        results=results,
    )


def _searcher(turns, script, docs=None, **kw):
    return Searcher(StubLLM(turns), "stub-model", FakeEngine(script, docs), **kw)


# --- tests -----------------------------------------------------------------

def test_happy_path_ranked_list_and_events():
    turns = [
        search_turn("(^ black bear*)"),
        judge_turn([
            {"cp": 10, "grade": 3, "reason": "directly answers"},
            {"cp": 20, "grade": 0, "reason": "off topic"},
        ]),
        stop_turn(),
    ]
    script = [_resp([(10, 5.0, "bear attack risk is low"), (20, 9.0, "unrelated")])]
    result = _searcher(turns, script).run("black bear attacks while hiking")

    entries = result.ranked_list.entries
    assert [e.cp for e in entries] == [10, 20]  # grade desc beats score desc
    assert [e.rank for e in entries] == [1, 2]
    assert entries[0].grade == 3 and entries[1].grade == 0  # grade 0 retained
    assert entries[0].score == 5.0
    assert entries[0].surfacing_query == "(^ black bear*)"
    assert entries[0].summary == "bear attack risk is low"

    types = [e.type for e in result.events]
    assert types == ["llm_turn", "search", "llm_turn", "judge", "llm_turn", "stop"]
    assert result.events[-1].reason == "no_tool_call"
    assert all(hasattr(e, "duration_ms") for e in result.events)
    # the search event is the heavy, reconstructable kind (AC#8)
    sev = next(e for e in result.events if e.type == "search")
    assert sev.exclude == [] and sev.total_matches == 2
    assert len(sev.results) == 2 and sev.results[0]["cp"] == 10
    assert sev.atom_counts[0]["term"] == "bear*"
    jev = next(e for e in result.events if e.type == "judge")
    assert jev.judgements == [
        {"cp": 10, "grade": 3, "reason": "directly answers"},
        {"cp": 20, "grade": 0, "reason": "off topic"},
    ]


def test_judge_before_search_bounce_and_recovery():
    turns = [
        search_turn("(^ bear*)"),    # surfaces cp 10
        search_turn("(^ attack*)"),  # BOUNCE: must judge first (no engine call)
        judge_turn([{"cp": 10, "grade": 2, "reason": "ok"}]),
        stop_turn(),
    ]
    script = [_resp([(10, 5.0, "s")]), _resp([(11, 4.0, "t")])]
    s = _searcher(turns, script)
    result = s.run("intent")
    bounce = next(
        e for e in result.events if e.type == "bounce" and e.kind == "judge_before_search"
    )
    assert bounce.cps == [10]  # structured pending cps (for C2's cp->docno rewrite)
    assert "10" not in bounce.message  # the persisted message carries no raw cps
    assert len(s.engine.calls) == 1  # the bounce did not call the engine
    assert [e.cp for e in result.ranked_list.entries] == [10]


def test_engine_error_bounce_and_recovery():
    turns = [
        search_turn("(^ bad"),     # engine raises
        search_turn("(^ bear*)"),  # recover
        judge_turn([{"cp": 10, "grade": 4, "reason": "great"}]),
        stop_turn(),
    ]
    script = [EngineError("invalid GCL: unbalanced"), _resp([(10, 5.0, "s")])]
    s = _searcher(turns, script)
    result = s.run("intent")
    assert any(
        e.type == "bounce" and e.kind == "engine_error" and "invalid GCL" in e.message
        for e in result.events
    )
    assert len(s.engine.calls) == 2  # both searches reached the engine
    assert [e.cp for e in result.ranked_list.entries] == [10]


def test_stop_on_three_dry():
    turns = [search_turn(f"(^ x{i})") for i in range(3)] + [stop_turn()]
    script = [_resp([], total=0, unjudged=0) for _ in range(3)]
    result = _searcher(turns, script, dry_threshold=3).run("intent")
    assert result.events[-1].type == "stop" and result.events[-1].reason == "dry"


def test_stop_on_no_progress():
    turns = [
        search_turn("(^ bear*)"),  # surfaces cp 10
        judge_turn([]),            # empty -> no progress 1
        judge_turn([]),            # 2
        judge_turn([]),            # 3 -> stop
        stop_turn(),
    ]
    script = [_resp([(10, 5.0, "s")])]
    result = _searcher(turns, script, no_progress_threshold=3).run("intent")
    assert result.events[-1].type == "stop" and result.events[-1].reason == "no_progress"


def test_turn_cap_stops_a_bounce_loop():
    turns = [search_turn("(^ bad")] * 10  # the model never recovers
    script = [EngineError("bad")] * 10
    s = _searcher(turns, script, max_turns=4)
    result = s.run("intent")
    assert result.events[-1].type == "stop" and result.events[-1].reason == "turn_cap"
    assert sum(1 for e in result.events if e.type == "llm_turn") == 4
    assert len(s.engine.calls) == 4


def test_exclude_accumulates_and_config_defaults():
    turns = [
        search_turn("(^ bear*)"),
        judge_turn([{"cp": 10, "grade": 3, "reason": "r"}]),
        search_turn("(^ attack*)"),
        judge_turn([{"cp": 20, "grade": 2, "reason": "r"}]),
        stop_turn(),
    ]
    script = [_resp([(10, 5.0, "a")]), _resp([(20, 4.0, "b")])]
    s = _searcher(turns, script)
    s.run("intent")
    assert s.engine.calls[0]["exclude"] == []
    assert s.engine.calls[1]["exclude"] == [10]  # judged cp injected by the controller
    assert s.engine.calls[0]["top_k"] == 10 and s.engine.calls[0]["window"] == 75


def test_hallucinated_cp_is_ignored():
    turns = [
        search_turn("(^ bear*)"),
        judge_turn([
            {"cp": 10, "grade": 3, "reason": "real"},
            {"cp": 999, "grade": 4, "reason": "never surfaced"},
        ]),
        stop_turn(),
    ]
    script = [_resp([(10, 5.0, "s")])]
    result = _searcher(turns, script).run("intent")
    assert [e.cp for e in result.ranked_list.entries] == [10]  # 999 ignored


def test_judge_invalid_grade_bounce_and_recovery():
    turns = [
        search_turn("(^ bear*)"),
        judge_turn([{"cp": 10, "grade": 5, "reason": "out of range"}]),  # -> ValidationError
        judge_turn([{"cp": 10, "grade": 4, "reason": "fixed"}]),
        stop_turn(),
    ]
    script = [_resp([(10, 5.0, "s")])]
    result = _searcher(turns, script).run("intent")
    assert any(e.type == "bounce" and e.kind == "judge_invalid" for e in result.events)
    entries = result.ranked_list.entries
    assert [e.cp for e in entries] == [10] and entries[0].grade == 4


def test_multi_tool_call_turn_processes_first_only():
    two = _msg(tool_calls=[
        _tool_call("search", {"query": "(^ bear*)"}, "c1"),
        _tool_call("search", {"query": "(^ extra)"}, "c2"),
    ])
    turns = [two, judge_turn([{"cp": 10, "grade": 3, "reason": "r"}]), stop_turn()]
    script = [_resp([(10, 5.0, "s")]), _resp([(99, 1.0, "t")])]
    s = _searcher(turns, script)
    result = s.run("intent")
    llm0 = next(e for e in result.events if e.type == "llm_turn")
    assert llm0.tool_calls == 2  # emitted count recorded
    assert len(s.engine.calls) == 1  # only the first tool call ran
    assert [e.cp for e in result.ranked_list.entries] == [10]
