import json

import httpx
import pytest

from isj_agent.engine.base import EngineError, SearchEngine
from isj_agent.engine.lucindri import LucindriSearchEngine


def _engine(handler):
    return LucindriSearchEngine(
        base_url="http://lucindri.test", transport=httpx.MockTransport(handler)
    )


# --- search ----------------------------------------------------------------

def test_search_posts_contract_and_drops_excluded():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"results": [
            {"docno": "d1", "score": -4.0, "summary": "s1"},
            {"docno": "d2", "score": -5.0, "summary": "s2"},  # excluded
            {"docno": "d3", "score": -6.0, "summary": "s3"},
        ]})

    resp = _engine(handler).search('#combine("a")', top_k=2, exclude=["d2"], window=75)
    assert seen["path"] == "/search"
    # count = |exclude|(1) + top_k(2); summaries requested; window is NOT sent
    assert seen["body"] == {"query": '#combine("a")', "count": 3, "summaries": True}
    assert [h.id for h in resp.results] == ["d1", "d3"]  # d2 dropped client-side
    assert [h.rank for h in resp.results] == [1, 2]      # re-ranked over survivors
    assert resp.results[0].score == -4.0                 # negative LM score preserved
    assert resp.total_matches is None and resp.atom_counts is None  # omitted, not faked


def test_malformed_query_400_raises_engine_error():
    def handler(req):
        return httpx.Response(400, json={"error": "Syntax Error: unbalanced parentheses"})
    with pytest.raises(EngineError, match="unbalanced"):
        _engine(handler).search('#combine("a"', top_k=5)


def test_degenerate_parse_is_empty_not_error():
    # A null/degenerate parse is 200 {results:[]}: a VALID empty result, not an error.
    def handler(req):
        return httpx.Response(200, json={"results": []})
    resp = _engine(handler).search('#combine("the")', top_k=5)
    assert resp.results == []


# --- read ------------------------------------------------------------------

def test_read_returns_fulltext_or_none_on_404():
    def handler(req):
        docno = json.loads(req.content)["docno"]
        if docno == "known":
            return httpx.Response(200, json={"docno": "known", "fulltext": "the body"})
        return httpx.Response(404, json={"error": "unknown docno"})
    eng = _engine(handler)
    assert eng.read("known") == "the body"
    assert eng.read("missing") is None  # 404 -> None, per the contract


def test_read_non_404_error_raises():
    def handler(req):
        return httpx.Response(500, json={"error": "boom"})
    with pytest.raises(EngineError, match="boom"):
        _engine(handler).read("x")


# --- healthz ---------------------------------------------------------------

def test_healthz_ok_and_fails_fast():
    _engine(lambda r: httpx.Response(200, json={"ok": True})).healthz()  # no raise
    with pytest.raises(EngineError):
        _engine(lambda r: httpx.Response(503, json={"error": "starting"})).healthz()


# --- Protocol conformance --------------------------------------------------

def test_satisfies_search_engine_protocol():
    eng = _engine(lambda r: httpx.Response(200, json={"results": []}))
    assert isinstance(eng, SearchEngine)
