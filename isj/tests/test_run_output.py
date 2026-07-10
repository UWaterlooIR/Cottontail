import json

import pytest

from isj_agent.protocol.intents import Intents
from isj_agent.protocol.results import RankedEntry, RankedList, SearcherResult, TraceEvent
from isj_agent.run_output import RunError, write_run


def _result(intent):
    # Docno on the wire (Option B): the id IS the docno; run_output does no mapping,
    # it only renames the in-memory key `id` -> the on-disk key `docno`.
    rl = RankedList(intent=intent, entries=[
        RankedEntry(rank=1, id="doc-A", grade=3, score=5.0, summary="s100", reason="r1", surfacing_query="(^ a*)"),
        RankedEntry(rank=2, id="doc-B", grade=1, score=2.0, summary="s200", reason="r2", surfacing_query="(^ a*)"),
    ])
    events = [
        TraceEvent(type="llm_call", ts=1.0, duration_ms=10.0, purpose="searcher_turn", turn=1, tool="search", tool_calls=1),
        TraceEvent(type="propose", ts=1.02, duration_ms=0.0, query="(^ a*)"),
        TraceEvent(type="search_request", ts=1.05, duration_ms=0.0, query="(^ a*)", top_k=10,
                   window=75, exclude=["doc-A", "doc-B"]),
        TraceEvent(type="search", ts=1.1, duration_ms=5.0, query="(^ a*)", total_matches=2,
                   unjudged_matches=2, returned=2, atom_counts=[{"term": "a*", "count": 9}],
                   results=[{"rank": 1, "score": 5.0, "id": "doc-A", "summary": "s100"},
                            {"rank": 2, "score": 2.0, "id": "doc-B", "summary": "s200"}]),
        TraceEvent(type="judge", ts=1.3, duration_ms=0.0, id="doc-A", grade=3, reason="r1"),
        TraceEvent(type="judge", ts=1.31, duration_ms=0.0, id="doc-B", grade=1, reason="r2"),
        TraceEvent(type="revisit", ts=1.32, duration_ms=0.0, id="doc-A", grade=3),
        TraceEvent(type="stop", ts=1.4, duration_ms=0.0, reason="intent_budget"),
    ]
    return SearcherResult(ranked_list=rl, events=events)


def _events(out, nn):
    return [json.loads(l) for l in (out / f"intent-{nn}.trace.jsonl").read_text().splitlines()]


def test_all_success_writes_docnos(tmp_path):
    intents = Intents(question="Q?", interpretations=["interp zero", "interp one"])
    out = tmp_path / "run"
    write_run(out, intents, [_result("interp zero"), _result("interp one")])

    assert Intents.model_validate_json((out / "intents.json").read_text()) == intents
    assert not (out / "errors.log").exists()  # absence => whole run succeeded

    for nn in ("00", "01"):
        rl = json.loads((out / f"intent-{nn}.json").read_text())
        assert [e["docno"] for e in rl["entries"]] == ["doc-A", "doc-B"]  # docno on disk
        assert all("cp" not in e and "id" not in e for e in rl["entries"])  # id -> docno
        evs = _events(out, nn)
        assert [e["type"] for e in evs] == [
            "llm_call", "propose", "search_request", "search", "judge", "judge", "revisit", "stop"
        ]
        req = next(e for e in evs if e["type"] == "search_request")
        assert req["exclude"] == ["doc-A", "doc-B"]  # exclude is already docnos
        search = next(e for e in evs if e["type"] == "search")
        assert [r["docno"] for r in search["results"]] == ["doc-A", "doc-B"]
        assert all("cp" not in r and "id" not in r for r in search["results"])
        judges = [e for e in evs if e["type"] == "judge"]
        assert [j["docno"] for j in judges] == ["doc-A", "doc-B"]
        assert all("cp" not in j and "id" not in j for j in judges)
        revisit = next(e for e in evs if e["type"] == "revisit")
        assert revisit["docno"] == "doc-A" and "id" not in revisit and "cp" not in revisit


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


def test_partial_result_writes_trace_and_errors_log(tmp_path):
    # A SearcherResult with .error set (a caught mid-loop failure) keeps its json +
    # trace AND is surfaced in errors.log (not silently counted a clean success).
    intents = Intents(question="Q?", interpretations=["a"])
    out = tmp_path / "run"
    res = _result("a").model_copy(update={"error": "RuntimeError: context blew"})
    write_run(out, intents, [res])
    assert (out / "intent-00.json").exists()
    assert (out / "intent-00.trace.jsonl").read_text() != ""
    assert "intent 00 (a): RuntimeError: context blew" in (out / "errors.log").read_text()


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


def test_intents_none_writes_only_errors_log(tmp_path):
    # Analyst-level failure: no interpretations, so only errors.log is written.
    out = tmp_path / "run"
    write_run(out, None, [], run_error="analysis failed: boom")
    assert not (out / "intents.json").exists()
    assert "run-level error: analysis failed: boom" in (out / "errors.log").read_text()


# --- StreamingRunWriter (TASK-35) ------------------------------------------

from isj_agent.protocol.results import LiveMarker  # noqa: E402
from isj_agent.run_output import StreamingRunWriter  # noqa: E402


def test_streaming_writer_matches_write_run_byte_for_byte(tmp_path):
    # The incremental writer must produce, for a completed run, the SAME
    # intents.json / intent-NN.json / intent-NN.trace.jsonl as the one-shot write_run.
    intents = Intents(question="Q?", interpretations=["interp zero", "interp one"])
    outcomes = [_result("interp zero"), _result("interp one")]

    a = tmp_path / "oneshot"
    write_run(a, intents, outcomes)

    b = tmp_path / "streamed"
    w = StreamingRunWriter(b)
    w.start(intents)
    for i, (interp, oc) in enumerate(zip(intents.interpretations, outcomes)):
        for ev in oc.events:
            w.observe(i, ev)
        w.finish_intent(i, interp, oc)
    w.finish()

    for name in ("intents.json", "intent-00.json", "intent-01.json",
                 "intent-00.trace.jsonl", "intent-01.trace.jsonl"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    assert not (a / "errors.log").exists() and not (b / "errors.log").exists()
    # the new observable artifact
    assert (b / "activity.log").read_text().strip()


def test_streaming_out_dir_created_if_missing(tmp_path):
    run = tmp_path / "deep" / "nested" / "run"   # does not exist
    w = StreamingRunWriter(run)
    w.start(Intents(question="Q?", interpretations=["a"]))
    w.finish()
    assert (run / "activity.log").exists() and (run / "intents.json").exists()


def test_streaming_markers_go_to_activity_log_not_trace(tmp_path):
    run = tmp_path / "run"
    w = StreamingRunWriter(run)
    w.start(Intents(question="Q?", interpretations=["only"]))
    w.observe(0, LiveMarker(kind="await_searcher_turn", ts=1.0, turn=1))
    w.observe(0, TraceEvent(type="llm_call", ts=1.1, duration_ms=5.0, purpose="searcher_turn", turn=1))
    w.observe(0, LiveMarker(kind="await_judge", ts=1.2, count=3))
    w.finish_intent(0, "only", _result("only"))
    w.finish()

    trace = (run / "intent-00.trace.jsonl").read_text()
    assert trace.count("\n") == 1              # only the one real TraceEvent persisted
    assert "await" not in trace                # no marker leaked into the trace
    act = (run / "activity.log").read_text()
    assert "awaiting LLM" in act and "judge call" in act   # markers ARE in the activity log


def test_streaming_partial_run_leaves_inspectable_output(tmp_path):
    # Simulate a kill: start + stream a couple events, but never finish_intent/finish.
    run = tmp_path / "run"
    w = StreamingRunWriter(run)
    w.start(Intents(question="Q?", interpretations=["a", "b"]))
    w.observe(0, TraceEvent(type="propose", ts=1.0, duration_ms=0.0, query="(^ a)"))
    w.observe(0, TraceEvent(type="search", ts=1.1, duration_ms=5.0, query="(^ a)", returned=0, results=[]))
    # no finish_intent / finish -> mimic a crash mid-intent

    assert (run / "intents.json").exists()               # written up front
    assert (run / "activity.log").read_text().strip()    # partial activity survives
    trace = (run / "intent-00.trace.jsonl").read_text().splitlines()
    assert len(trace) == 2                               # flushed per line -> survives a kill
    assert not (run / "errors.log").exists()             # never reached finish()
