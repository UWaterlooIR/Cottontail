import pytest

from isj_agent.engine.fake import FakeEngine
from isj_agent.protocol.queryable import CoverQuery, MultiTextProgram, Queryable, TieredQuery
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
        results=[Hit(rank=1, score=1.0, id="10", summary="s")],
    )
    eng = FakeEngine([resp])
    out = CoverQuery("(^ a b)").execute(eng, top_k=7, exclude=[], window=50)
    # execute() passes (gcl, top_k, exclude, window) straight through to engine.search
    assert eng.calls[0] == {"query": "(^ a b)", "top_k": 7, "exclude": [], "window": 50}
    assert out.total_matches == 3 and out.results[0].id == "10"


# --- TieredQuery (TASK-19) -------------------------------------------------

def test_tiered_is_a_queryable():
    assert issubclass(TieredQuery, Queryable)


def test_tiered_tool_schema_named_tiered_query_search():
    schema = TieredQuery.tool_schema()
    assert schema["function"]["name"] == "tiered_query_search"
    assert TieredQuery.tool_name == "tiered_query_search"
    params = schema["function"]["parameters"]
    assert params["required"] == ["tiers"]
    assert params["properties"]["tiers"]["type"] == "array"
    assert params["properties"]["tiers"]["items"]["type"] == "string"


def test_tiered_from_tool_arguments_roundtrip():
    q = TieredQuery.from_tool_arguments({"tiers": ["(^ a b)", "(^ a)"]})
    assert q == TieredQuery(("(^ a b)", "(^ a)"))
    assert q.tiers == ("(^ a b)", "(^ a)")


def test_tiered_from_tool_arguments_missing_key_raises():
    # BaseSearcher relies on this raising so it can bounce a malformed-shape call.
    with pytest.raises(KeyError):
        TieredQuery.from_tool_arguments({"not_tiers": 1})


@pytest.mark.parametrize("bad", [{"tiers": "just a string"}, {"tiers": []}, {"tiers": ["ok", 7]}])
def test_tiered_from_tool_arguments_invalid_shape_raises(bad):
    # non-list, empty, or non-string element -> ValueError (BaseSearcher bounces).
    with pytest.raises(ValueError):
        TieredQuery.from_tool_arguments(bad)


def test_tiered_trace_and_string_forms_are_distinct():
    q = TieredQuery(("(>> (# 8) (^ a b))", "(^ a b)"))
    # dict (a LIST under "tiers") for the LLM-facing sinks
    assert q.trace_arguments() == {"tiers": ["(>> (# 8) (^ a b))", "(^ a b)"]}
    # a bare joined STRING (never a dict/JSON) for the display/persisted sinks
    assert q.query_string() == "(>> (# 8) (^ a b)) ; (^ a b)"
    assert isinstance(q.query_string(), str)


def test_tiered_execute_forwards_tiers_to_engine_tiered_search():
    resp = SearchResponse(
        total_matches=4, unjudged_matches=4,
        atom_counts=[AtomCount(term="a", count=5)],
        results=[Hit(rank=1, score=2.0, id="11", summary="s")],
    )
    eng = FakeEngine([resp])
    out = TieredQuery(("(^ a b)", "(^ a)")).execute(eng, top_k=7, exclude=["1"], window=50)
    # execute() forwards the tiers (as a list) + paging args to engine.tiered_search;
    # the recorded call carries a `tiers` key (not `query`), proving the tiered path.
    assert eng.calls[0] == {"tiers": ["(^ a b)", "(^ a)"], "top_k": 7, "exclude": ["1"], "window": 50}
    assert out.total_matches == 4 and out.results[0].id == "11"


def test_tiered_single_tier_execute_still_uses_tiered_search():
    # a single-tier TieredQuery is the base case; it still routes through tiered_search
    # (the C++ handler makes it behave like cover_search; the Python side stays uniform).
    resp = SearchResponse(total_matches=1, unjudged_matches=1, atom_counts=[], results=[])
    eng = FakeEngine([resp])
    TieredQuery(("(^ a b)",)).execute(eng, top_k=3, exclude=[], window=75)
    assert eng.calls[0] == {"tiers": ["(^ a b)"], "top_k": 3, "exclude": [], "window": 75}


# --- MultiTextProgram (TASK-22) ---------------------------------------------

PROGRAM = 'b0 = "black" <> "bear*"\nq0 = b0\n@rank q0 b0\n'


def test_multitext_is_a_queryable():
    assert issubclass(MultiTextProgram, Queryable)


def test_multitext_tool_schema_named_submit_tiered_query():
    s = MultiTextProgram.tool_schema()
    assert s["function"]["name"] == "submit_tiered_query"
    assert MultiTextProgram.tool_name == "submit_tiered_query"
    assert s["function"]["parameters"]["required"] == ["program"]
    assert s["function"]["parameters"]["properties"]["program"]["type"] == "string"


def test_multitext_from_tool_arguments_roundtrip():
    q = MultiTextProgram.from_tool_arguments({"program": PROGRAM})
    assert q == MultiTextProgram(PROGRAM)


def test_multitext_from_tool_arguments_missing_key_raises():
    with pytest.raises(KeyError):
        MultiTextProgram.from_tool_arguments({"tiers": ["(^ a)"]})


@pytest.mark.parametrize("bad", [{"program": ""}, {"program": "   \n"}, {"program": 7}])
def test_multitext_from_tool_arguments_invalid_shape_raises(bad):
    with pytest.raises((ValueError, TypeError)):
        MultiTextProgram.from_tool_arguments(bad)


def test_multitext_trace_and_string_forms():
    q = MultiTextProgram(PROGRAM)
    assert q.trace_arguments() == {"program": PROGRAM}
    assert q.query_string() == PROGRAM  # heavy traces: the program verbatim


def test_multitext_execute_forwards_program_to_engine_multitext_search():
    resp = SearchResponse(
        total_matches=2, unjudged_matches=2,
        atom_counts=[AtomCount(term="bear*", count=9)],
        results=[Hit(rank=1, score=1.0, id="10", summary="s")],
    )
    eng = FakeEngine([resp])
    out = MultiTextProgram(PROGRAM).execute(eng, top_k=5, exclude=["3"], window=60)
    assert eng.calls[0] == {"program": PROGRAM, "top_k": 5, "exclude": ["3"], "window": 60}
    assert out.results[0].id == "10"
