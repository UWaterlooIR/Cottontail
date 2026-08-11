import pytest
from pydantic import ValidationError

from isj_agent.engine.base import EngineError, SearchEngine
from isj_agent.engine.fake import FakeEngine
from isj_agent.protocol.search import Hit, SearchResponse, Verdict


def _resp(cps):
    results = [
        Hit(rank=i, score=10.0 - i, id=str(cp), summary=f"summary-{cp}")
        for i, cp in enumerate(cps, 1)
    ]
    return SearchResponse(results=results)


# --- type validation -------------------------------------------------------

def test_verdict_grade_bounds():
    # Verdict carries NO cp (the controller owns it) and uses the 0-3 scale.
    assert Verdict(reason="ok", grade=0).grade == 0
    assert Verdict(reason="ok", grade=3).grade == 3
    with pytest.raises(ValidationError):
        Verdict(reason="too high", grade=4)
    with pytest.raises(ValidationError):
        Verdict(reason="too low", grade=-1)


def test_search_response_round_trips():
    x = _resp([0, 9, 16])
    assert SearchResponse.model_validate(x.model_dump()) == x
    assert SearchResponse.model_validate_json(x.model_dump_json()) == x


def test_search_response_extra_forbid():
    good = _resp([0]).model_dump()
    SearchResponse.model_validate(good)  # ok
    bad = {**good, "unexpected": 1}
    with pytest.raises(ValidationError):
        SearchResponse.model_validate(bad)


def test_hit_id_is_str():
    h = Hit(rank=1, score=1.0, id="12345", summary="s")
    assert h.id == "12345" and isinstance(h.id, str)


# --- FakeEngine ------------------------------------------------------------

def test_batches_in_order_then_dry():
    eng = FakeEngine([_resp([1, 2]), _resp([3])])
    assert [h.id for h in eng.search("q1").results] == ["1", "2"]
    assert [h.id for h in eng.search("q2").results] == ["3"]
    dry = eng.search("q3")
    assert dry.results == []


def test_scripted_engine_error_raises_and_records():
    eng = FakeEngine([EngineError("invalid GCL")])
    with pytest.raises(EngineError, match="invalid GCL"):
        eng.search("(^ bad", top_k=5)
    assert len(eng.calls) == 1  # the raising call is still recorded
    assert eng.calls[0]["query"] == "(^ bad"


def test_exclude_drops_and_reranks():
    eng = FakeEngine([_resp([10, 20, 30])])
    resp = eng.search("q", exclude=["20"])
    assert [h.id for h in resp.results] == ["10", "30"]
    assert [h.rank for h in resp.results] == [1, 2]  # re-ranked 1..N


def test_records_each_call_args():
    eng = FakeEngine([_resp([1])])
    eng.search("blackbear", top_k=7, exclude=["1", "2"], window=50)
    assert eng.calls[-1] == {
        "query": "blackbear",
        "top_k": 7,
        "exclude": ["1", "2"],
        "window": 50,
    }


def test_read_returns_text_or_none():
    eng = FakeEngine([], docs={"42": "the body"})
    assert eng.read("42") == "the body"
    assert eng.read("99") is None


# --- Protocol conformance --------------------------------------------------

def test_fake_engine_satisfies_protocol():
    assert isinstance(FakeEngine([]), SearchEngine)
