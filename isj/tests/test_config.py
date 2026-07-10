import pytest

from isj_agent.config import build_engine
from isj_agent.engine.base import EngineError
from isj_agent.engine.http import HttpSearchEngine


def test_engine_section_selects_the_cottontail_http_engine():
    cfg = {"engine": {
        "class": "isj_agent.engine.http.HttpSearchEngine",
        "base_url": "http://server.test",
    }}
    assert isinstance(build_engine(cfg), HttpSearchEngine)


def test_legacy_section_still_builds_the_cottontail_engine():
    # Backward-compat: a config with only the old [cottontail_http_json_server] works.
    cfg = {"cottontail_http_json_server": {"base_url": "http://server.test"}}
    assert isinstance(build_engine(cfg), HttpSearchEngine)


def test_engine_section_selects_lucindri_and_fails_fast_when_down():
    # Dispatches to the LucindriSearchEngine, which health-checks on build (Q6): a dead
    # port -> EngineError (fail fast), not a silently-broken engine.
    cfg = {"engine": {
        "class": "isj_agent.engine.lucindri.LucindriSearchEngine",
        "base_url": "http://127.0.0.1:1",  # nothing listening
    }}
    with pytest.raises(EngineError):
        build_engine(cfg)
