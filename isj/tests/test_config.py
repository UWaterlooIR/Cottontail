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


# --- MultiShardSearchEngine selection (TASK-34) ----------------------------

def test_engine_section_selects_multishard_and_fails_fast_when_a_shard_is_down():
    cfg = {"engine": {
        "class": "isj_agent.engine.multishard.MultiShardSearchEngine",
        "shards": [
            {"base_url": "http://127.0.0.1:1", "burrow": "/nonexistent-a"},
            {"base_url": "http://127.0.0.1:2", "burrow": "/nonexistent-b"},
        ],
    }}
    with pytest.raises(EngineError):  # healthz on build -> dead ports -> fail fast
        build_engine(cfg)


def test_multishard_requires_a_nonempty_shards_list():
    cfg = {"engine": {"class": "isj_agent.engine.multishard.MultiShardSearchEngine", "shards": []}}
    with pytest.raises(SystemExit):
        build_engine(cfg)


def test_multishard_shard_requires_base_url_and_burrow():
    cfg = {"engine": {
        "class": "isj_agent.engine.multishard.MultiShardSearchEngine",
        "shards": [{"base_url": "http://127.0.0.1:7000"}],  # missing burrow
    }}
    with pytest.raises(SystemExit):
        build_engine(cfg)
