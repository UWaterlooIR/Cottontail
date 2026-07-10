import json
import os

import httpx
import pytest

from isj_agent.engine.base import EngineError, SearchEngine
from isj_agent.engine.http import HttpSearchEngine
from isj_agent.protocol.search import SearchResponse

_COVER_JSON = {
    "total_matches": 3,
    "unjudged_matches": 3,
    "atom_counts": [{"term": "bear*", "count": 9}],
    "results": [
        {"rank": 1, "score": 12.3, "cp": 100, "summary": "black bear attacks are rare"},
    ],
}


def _engine(handler, token=None):
    """An HttpSearchEngine whose default client routes through a MockTransport."""
    return HttpSearchEngine(
        base_url="http://server.test", token=token,
        transport=httpx.MockTransport(handler),
    )


# --- search ----------------------------------------------------------------

def test_search_posts_body_and_auth_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_COVER_JSON)

    eng = _engine(handler, token="secret")
    resp = eng.search("(^ black bear*)", top_k=5, exclude=["100", "200"], window=50)

    assert seen["path"] == "/tools/cover_search"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"] == {
        "query": "(^ black bear*)", "top_k": 5, "exclude": [100, 200], "window": 50,
    }
    assert isinstance(resp, SearchResponse)
    assert resp.total_matches == 3 and resp.results[0].id == "100"


def test_no_auth_header_without_token():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_COVER_JSON)

    _engine(handler).search("(^ bear*)")
    assert seen["auth"] is None


def test_search_non_2xx_raises_engine_error_with_server_message():
    def handler(request):
        return httpx.Response(400, json={"error": "invalid GCL: unbalanced", "where": "cover_search"})

    with pytest.raises(EngineError, match="invalid GCL"):
        _engine(handler).search("(^ bad")


def test_search_transport_error_raises_engine_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(EngineError, match="transport error"):
        _engine(handler).search("(^ bear*)")


# --- tiered_search (TASK-19) -----------------------------------------------

def test_tiered_search_posts_tiers_body_and_auth_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_COVER_JSON)

    eng = _engine(handler, token="secret")
    resp = eng.tiered_search(["(>> (# 8) (^ black bear*))", "(^ black bear*)"],
                             top_k=5, exclude=["100", "200"], window=50)

    assert seen["path"] == "/tools/tiered_query_search"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"] == {
        "tiers": ["(>> (# 8) (^ black bear*))", "(^ black bear*)"],
        "top_k": 5, "exclude": [100, 200], "window": 50,
    }
    # the response is the SAME cover_search shape (reused CoverResponse/SearchResponse)
    assert isinstance(resp, SearchResponse)
    assert resp.total_matches == 3 and resp.results[0].id == "100"


def test_tiered_search_non_2xx_raises_engine_error_with_server_message():
    # a malformed tier fails the whole request -> the server's message bounces back.
    def handler(request):
        return httpx.Response(400, json={"error": "tier 0 ((^ bad): unbalanced", "where": "tiered_query_search"})

    with pytest.raises(EngineError, match="tier 0"):
        _engine(handler).tiered_search(["(^ bad"])


# --- read ------------------------------------------------------------------

def test_read_returns_text_when_found():
    def handler(request):
        assert request.url.path == "/tools/get_document"
        assert json.loads(request.content) == {"cp": 42}
        return httpx.Response(200, json={"cp": 42, "found": True, "text": "the body"})

    assert _engine(handler).read(42) == "the body"


def test_read_returns_none_when_not_found():
    def handler(request):
        return httpx.Response(200, json={"cp": 99, "found": False, "text": ""})

    assert _engine(handler).read(99) is None


def test_read_non_2xx_raises_engine_error():
    def handler(request):
        return httpx.Response(400, json={"error": "missing/invalid 'cp'"})

    with pytest.raises(EngineError, match="missing/invalid"):
        _engine(handler).read(1)


# --- Protocol conformance --------------------------------------------------

def test_satisfies_search_engine_protocol():
    eng = _engine(lambda r: httpx.Response(200, json=_COVER_JSON))
    assert isinstance(eng, SearchEngine)


# --- live connectivity check (skipped unless a server URL is provided) ------

_LIVE_URL = os.environ.get("COTTONTAIL_SERVER_URL")


@pytest.mark.skipif(not _LIVE_URL, reason="set COTTONTAIL_SERVER_URL to a running cottontail-jsonl-server")
def test_live_cover_search_round_trip():
    token = os.environ.get("COTTONTAIL_API_TOKEN")
    eng = HttpSearchEngine(base_url=_LIVE_URL, token=token)
    # A word* cover query needs a --stem porter burrow.
    resp = eng.search("(^ machine* learning*)", top_k=5)
    assert isinstance(resp, SearchResponse)
    assert resp.total_matches >= 0
    if resp.results:
        body = eng.read(resp.results[0].id)
        assert body is None or isinstance(body, str)
    # A malformed query is rejected by the engine -> EngineError.
    with pytest.raises(EngineError):
        eng.search("(^ unbalanced")


def test_default_timeout_is_one_hour_with_fast_connect():
    # TASK-29: read/query timeout 3600s (a client timeout is not a cancel);
    # connection establishment still fails fast.
    eng = HttpSearchEngine(base_url="http://127.0.0.1:9")
    t = eng._client.timeout
    assert t.read == 3600.0 and t.write == 3600.0 and t.pool == 3600.0
    assert t.connect == 10.0


def test_config_timeout_s_overrides(monkeypatch):
    from isj_agent.config import build_search_engine
    eng = build_search_engine({"base_url": "http://127.0.0.1:9", "timeout_s": 45})
    assert eng._client.timeout.read == 45.0
    assert eng._client.timeout.connect == 10.0
