import pytest

from isj_agent.engine.fake import FakeEngine
from isj_agent.protocol.queryable import CoverQuery, Queryable
from isj_agent.protocol.search import AtomCount, Hit, SearchResponse


def test_cover_is_a_queryable():
    assert issubclass(CoverQuery, Queryable)


def test_cover_tool_schema_named_cover_search():
    schema = CoverQuery.tool_schema()
    assert schema["function"]["name"] == "cover_search"
    assert schema["function"]["parameters"]["required"] == ["query"]
    assert CoverQuery.tool_name == "cover_search"


def test_cover_from_tool_arguments_roundtrip():
    q = CoverQuery.from_tool_arguments({"query": "(^ a b)"})
    assert q == CoverQuery("(^ a b)")
    assert q.gcl == "(^ a b)"


def test_cover_from_tool_arguments_missing_key_raises():
    # BaseSearcher relies on this raising so it can bounce a malformed-shape call.
    with pytest.raises(KeyError):
        CoverQuery.from_tool_arguments({"not_query": 1})


def test_cover_trace_and_string_forms_are_distinct():
    q = CoverQuery("(^ a b)")
    assert q.trace_arguments() == {"query": "(^ a b)"}  # dict for the LLM-facing sinks
    assert q.query_string() == "(^ a b)"                # bare string for display/persisted sinks


def test_cover_execute_forwards_args_and_returns_engine_response():
    resp = SearchResponse(
        total_matches=3, unjudged_matches=3,
        atom_counts=[AtomCount(term="a", count=5)],
        results=[Hit(rank=1, score=1.0, cp=10, summary="s")],
    )
    eng = FakeEngine([resp])
    out = CoverQuery("(^ a b)").execute(eng, top_k=7, exclude=[], window=50)
    # execute() passes (gcl, top_k, exclude, window) straight through to engine.search
    assert eng.calls[0] == {"query": "(^ a b)", "top_k": 7, "exclude": [], "window": 50}
    assert out.total_matches == 3 and out.results[0].cp == 10
