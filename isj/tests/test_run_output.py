import json

import pytest

from isj_agent.docno_map import DocnoMap
from isj_agent.index import build_sqlite_map
from isj_agent.protocol.intents import Intents
from isj_agent.protocol.results import RankedEntry, RankedList, SearcherResult, TraceEvent
from isj_agent.run_output import RunError, write_run


def _docno_map(tmp_path, rows):
    flat = tmp_path / "docno-cp.tsv"
    flat.write_text("".join(f"{d}\t{cp}\n" for d, cp in rows), encoding="utf-8")
    sqlite_path = tmp_path / "docno-cp.sqlite"
    build_sqlite_map(flat, sqlite_path)
    return DocnoMap(sqlite_path)


def _result(intent):
    rl = RankedList(intent=intent, entries=[
        RankedEntry(rank=1, cp=100, grade=3, score=5.0, summary="s100", reason="r1", surfacing_query="(^ a*)"),
        RankedEntry(rank=2, cp=200, grade=1, score=2.0, summary="s200", reason="r2", surfacing_query="(^ a*)"),
    ])
    events = [
        TraceEvent(type="llm_turn", ts=1.0, duration_ms=10.0, turn=1, tool="search", tool_calls=1, stopped=False),
        TraceEvent(type="search", ts=1.1, duration_ms=5.0, query="(^ a*)", top_k=10, window=75,
                   exclude=[], total_matches=2, unjudged_matches=2,
                   atom_counts=[{"term": "a*", "count": 9}],
                   results=[{"rank": 1, "score": 5.0, "cp": 100, "summary": "s100"},
                            {"rank": 2, "score": 2.0, "cp": 200, "summary": "s200"}]),
        TraceEvent(type="bounce", ts=1.2, duration_ms=0.0, kind="judge_before_search",
                   cps=[100, 200], message="search refused: judge the surfaced passages first"),
        TraceEvent(type="judge", ts=1.3, duration_ms=0.0, recorded=2,
                   judgements=[{"cp": 100, "grade": 3, "reason": "r1"},
                               {"cp": 200, "grade": 1, "reason": "r2"}]),
        TraceEvent(type="stop", ts=1.4, duration_ms=0.0, reason="no_tool_call"),
    ]
    return SearcherResult(ranked_list=rl, events=events)


def _events(out, nn):
    return [json.loads(l) for l in (out / f"intent-{nn}.trace.jsonl").read_text().splitlines()]


def test_all_success_writes_layout_with_docnos(tmp_path):
    intents = Intents(question="Q?", interpretations=["interp zero", "interp one"])
    dm = _docno_map(tmp_path, [("doc-A", 100), ("doc-B", 200)])
    out = tmp_path / "run"
    write_run(out, intents, [_result("interp zero"), _result("interp one")], docno_map=dm)

    assert Intents.model_validate_json((out / "intents.json").read_text()) == intents
    assert not (out / "errors.log").exists()  # absence => whole run succeeded

    for nn in ("00", "01"):
        rl = json.loads((out / f"intent-{nn}.json").read_text())
        assert [e["docno"] for e in rl["entries"]] == ["doc-A", "doc-B"]  # docno on disk
        assert all("cp" not in e for e in rl["entries"])  # never a raw cp
        evs = _events(out, nn)
        assert [e["type"] for e in evs] == ["llm_turn", "search", "bounce", "judge", "stop"]
        search = next(e for e in evs if e["type"] == "search")
        assert [r["docno"] for r in search["results"]] == ["doc-A", "doc-B"]
        assert all("cp" not in r for r in search["results"])
        bounce = next(e for e in evs if e["type"] == "bounce")
        assert bounce["cps"] == ["doc-A", "doc-B"]  # the structured pending cps -> docnos
        judge = next(e for e in evs if e["type"] == "judge")
        assert [j["docno"] for j in judge["judgements"]] == ["doc-A", "doc-B"]


def test_empty_trace_writes_empty_file(tmp_path):
    intents = Intents(question="Q?", interpretations=["a"])
    res = SearcherResult(ranked_list=RankedList(intent="a", entries=[]), events=[])
    out = tmp_path / "run"
    write_run(out, intents, [res])
    assert (out / "intent-00.trace.jsonl").read_text() == ""


def test_failure_writes_errors_log_and_skips_intent(tmp_path):
    intents = Intents(question="Q?", interpretations=["good", "bad"])
    out = tmp_path / "run"
    write_run(out, intents, [_result("good"), RunError(message="boom")])
    assert (out / "intent-00.json").exists()
    assert not (out / "intent-01.json").exists()
    assert not (out / "intent-01.trace.jsonl").exists()
    assert "intent 01 (bad): boom" in (out / "errors.log").read_text()


def test_run_level_error_writes_errors_log(tmp_path):
    intents = Intents(question="Q?", interpretations=["a"])
    out = tmp_path / "run"
    write_run(out, intents, [_result("a")], run_error="analyst failed")
    assert "run-level error: analyst failed" in (out / "errors.log").read_text()


def test_count_mismatch_raises(tmp_path):
    intents = Intents(question="Q?", interpretations=["a", "b"])
    with pytest.raises(ValueError):
        write_run(tmp_path / "run", intents, [_result("a")])


def test_overwrite_guard_and_clears_stale(tmp_path):
    out = tmp_path / "run"
    two = Intents(question="Q?", interpretations=["a", "b"])
    write_run(out, two, [_result("a"), RunError(message="x")])  # leaves intent-00 + errors.log
    assert (out / "errors.log").exists()
    with pytest.raises(FileExistsError):
        write_run(out, two, [_result("a"), _result("b")])
    # overwrite with an all-success single-intent run: stale intent-01-absent, errors.log cleared
    one = Intents(question="Q?", interpretations=["a"])
    write_run(out, one, [_result("a")], overwrite=True)
    assert (out / "intent-00.json").exists()
    assert not (out / "errors.log").exists()  # stale errors.log cleared


def test_docnoless_corpus_persists_cps(tmp_path):
    intents = Intents(question="Q?", interpretations=["a"])
    out = tmp_path / "run"
    write_run(out, intents, [_result("a")], docno_map=None)
    rl = json.loads((out / "intent-00.json").read_text())
    assert [e["cp"] for e in rl["entries"]] == [100, 200]  # cps kept, no map
    assert all("docno" not in e for e in rl["entries"])
    search = next(e for e in _events(out, "00") if e["type"] == "search")
    assert [r["cp"] for r in search["results"]] == [100, 200]
