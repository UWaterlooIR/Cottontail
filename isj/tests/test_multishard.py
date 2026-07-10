import pytest

from isj_agent.engine.base import EngineError, SearchEngine
from isj_agent.engine.fake import FakeEngine
from isj_agent.engine.multishard import MultiShardSearchEngine
from isj_agent.protocol.search import AtomCount, Hit, SearchResponse


def _resp(hits, total=None, unjudged=None, atoms=None):
    return SearchResponse(
        total_matches=total, unjudged_matches=unjudged, atom_counts=atoms,
        results=[Hit(rank=i, score=s, id=d, summary=f"sum-{d}")
                 for i, (d, s) in enumerate(hits, 1)],
    )


# --- fan-out + score merge -------------------------------------------------

def test_search_merges_shards_by_score_into_global_topk():
    s0 = FakeEngine([_resp([("d0a", 5.0), ("d0b", 2.0)])])
    s1 = FakeEngine([_resp([("d1a", 4.0), ("d1b", 1.0)])])
    eng = MultiShardSearchEngine([s0, s1])
    resp = eng.search("(^ a)", top_k=3)
    # global top-3 by score, re-ranked 1..3
    assert [h.id for h in resp.results] == ["d0a", "d1a", "d0b"]
    assert [h.rank for h in resp.results] == [1, 2, 3]
    assert [h.score for h in resp.results] == [5.0, 4.0, 2.0]


def test_counts_summed_across_shards():
    s0 = FakeEngine([_resp([("d0", 5.0)], total=10, unjudged=8,
                           atoms=[AtomCount(term="a", count=3), AtomCount(term="b", count=2)])])
    s1 = FakeEngine([_resp([("d1", 4.0)], total=20, unjudged=15,
                           atoms=[AtomCount(term="a", count=5), AtomCount(term="c", count=1)])])
    resp = MultiShardSearchEngine([s0, s1]).search("(^ a)", top_k=10)
    assert resp.total_matches == 30 and resp.unjudged_matches == 23
    assert {a.term: a.count for a in resp.atom_counts} == {"a": 8, "b": 2, "c": 1}


def test_absent_counts_stay_none():
    s0 = FakeEngine([_resp([("d0", 5.0)])])  # no counts (Lucindri-style / Q3)
    s1 = FakeEngine([_resp([("d1", 4.0)])])
    resp = MultiShardSearchEngine([s0, s1]).search("(^ a)", top_k=10)
    assert resp.total_matches is None and resp.atom_counts is None


def test_same_exclude_fanned_to_every_shard():
    s0 = FakeEngine([_resp([("d0", 5.0)])])
    s1 = FakeEngine([_resp([("d1", 4.0)])])
    MultiShardSearchEngine([s0, s1]).search("(^ a)", top_k=5, exclude=["x", "y"], window=42)
    for s in (s0, s1):
        assert s.calls[0]["exclude"] == ["x", "y"] and s.calls[0]["window"] == 42


# --- read routing ----------------------------------------------------------

def test_read_routes_to_the_owning_shard():
    s0 = FakeEngine([_resp([("d0", 5.0)])], docs={"d0": "body-0"})
    s1 = FakeEngine([_resp([("d1", 4.0)])], docs={"d1": "body-1"})
    eng = MultiShardSearchEngine([s0, s1])
    eng.search("(^ a)", top_k=5)  # populates the docno->shard memo
    assert eng.read("d0") == "body-0"
    assert eng.read("d1") == "body-1"


def test_read_cold_miss_tries_all_shards():
    s0 = FakeEngine([], docs={})
    s1 = FakeEngine([], docs={"dz": "found-in-1"})
    eng = MultiShardSearchEngine([s0, s1])
    assert eng.read("dz") == "found-in-1"   # not memoized -> found by trying shards
    assert eng.read("nope") is None


# --- fail-fast -------------------------------------------------------------

def test_any_shard_error_fails_the_whole_search():
    ok = FakeEngine([_resp([("d0", 5.0)])])
    bad = FakeEngine([EngineError("Syntax Error: unbalanced parentheses")])
    with pytest.raises(EngineError, match="unbalanced"):
        MultiShardSearchEngine([ok, bad]).search("(^ a", top_k=5)


# --- healthz + protocol ----------------------------------------------------

class _Health:
    def __init__(self, ok):
        self._ok = ok

    def healthz(self):
        if not self._ok:
            raise EngineError("server down")


def test_healthz_passes_when_all_up_and_fails_fast_on_a_down_shard():
    MultiShardSearchEngine([_Health(True), _Health(True)]).healthz()  # no raise
    with pytest.raises(EngineError, match="shard 1"):
        MultiShardSearchEngine([_Health(True), _Health(False)]).healthz()


def test_satisfies_search_engine_protocol():
    assert isinstance(MultiShardSearchEngine([FakeEngine([])]), SearchEngine)


def test_empty_shard_list_is_rejected():
    with pytest.raises(ValueError):
        MultiShardSearchEngine([])
