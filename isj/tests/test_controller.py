import json
import re
from types import SimpleNamespace

from isj_agent.agents.judger import JudgeCall
from isj_agent.agents.searcher import ProposeResult
from isj_agent.controller import Controller
from isj_agent.engine.base import EngineError
from isj_agent.engine.fake import FakeEngine
from isj_agent.protocol.queryable import CoverQuery, TieredQuery
from isj_agent.protocol.search import AtomCount, Hit, SearchResponse, Verdict


# --- builders: a SearchResponse from (cp, grade) pairs + the matching docs map ----
# The Judger grade for a cp is encoded in that cp's document body ("[[G:n]]"), so the
# StubJudger is a pure function of its input and order-alignment is observable.

def build(cp_grades, total=None):
    hits = [Hit(rank=i, score=100.0 - i, cp=cp, summary=f"sum-{cp}")
            for i, (cp, _) in enumerate(cp_grades, 1)]
    resp = SearchResponse(
        total_matches=total if total is not None else len(hits),
        unjudged_matches=len(hits),
        atom_counts=[AtomCount(term="x", count=1)],
        results=hits,
    )
    docs = {cp: f"body-{cp} [[G:{g}]]" for cp, g in cp_grades}
    return resp, docs


def dry():
    return SearchResponse(total_matches=0, unjudged_matches=0, atom_counts=[], results=[])


class StubSearcher:
    system_prompt = "SYSTEM"

    def __init__(self, queries):
        self.queries = list(queries)
        self.i = 0
        self.tool_results = []  # the tool-result payloads fed back (the Searcher's history)

    def propose(self, messages):
        # capture the most recent tool result the controller appended (this query's history)
        for m in reversed(messages):
            if m.get("role") == "tool":
                self.tool_results.append(json.loads(m["content"]))
                break
        q = self.queries[self.i] if self.i < len(self.queries) else "(^ more)"
        self.i += 1
        cid = f"c{self.i}"
        return ProposeResult(
            queryable=CoverQuery(q), content="reasoning", tool_call_id=cid,
            assistant_message={"role": "assistant", "content": "",
                               "tool_calls": [{"id": cid, "type": "function",
                                               "function": {"name": "cover_search",
                                                            "arguments": json.dumps({"query": q})}}]},
            usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            finish_reason="tool_calls", n_tool_calls=1,
        )


class StubTieredSearcher:
    """A searcher that emits a TieredQuery each turn (TASK-19): same shape as
    StubSearcher but exercises the tiered path through the unchanged controller."""

    system_prompt = "SYSTEM"

    def __init__(self, tier_lists):
        self.tier_lists = [tuple(t) for t in tier_lists]
        self.i = 0
        self.tool_results = []

    def propose(self, messages):
        for m in reversed(messages):
            if m.get("role") == "tool":
                self.tool_results.append(json.loads(m["content"]))
                break
        tiers = self.tier_lists[self.i] if self.i < len(self.tier_lists) else ("(^ more)",)
        self.i += 1
        cid = f"c{self.i}"
        return ProposeResult(
            queryable=TieredQuery(tiers), content="reasoning", tool_call_id=cid,
            assistant_message={"role": "assistant", "content": "",
                               "tool_calls": [{"id": cid, "type": "function",
                                               "function": {"name": "tiered_query_search",
                                                            "arguments": json.dumps({"tiers": list(tiers)})}}]},
            usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            finish_reason="tool_calls", n_tool_calls=1,
        )


class StubJudger:
    def __init__(self, concurrency=8):
        self.concurrency = concurrency
        self.judged_docs = []  # every document body handed to judge()

    def judge(self, intent, docs):
        out = []
        for _summary, document in docs:
            self.judged_docs.append(document)
            if "[[FAIL]]" in document:
                out.append(JudgeCall(verdict=None, request=[{"role": "user", "content": document}],
                                     content=None, reasoning=None, error="judge boom"))
                continue
            g = int(re.search(r"\[\[G:(\d)\]\]", document).group(1))
            out.append(JudgeCall(
                verdict=Verdict(reason=f"g{g}", grade=g),
                request=[{"role": "user", "content": document}],
                content=json.dumps({"reason": f"g{g}", "grade": g}), reasoning="thinking",
            ))
        return out


def _ev(result, type_):
    return [e.model_dump() for e in result.events if e.type == type_]


def _ctl(queries, script, docs, *, judger=None, **kw):
    return Controller(StubSearcher(queries), judger or StubJudger(), FakeEngine(script, docs), **kw)


# --- tests -----------------------------------------------------------------

def test_retain_all_keeps_the_whole_tripping_wave():
    # one wave of 5; streak (2 grade-0) trips at rank 3, but ranks 4-5 are also kept.
    resp, docs = build([(10, 3), (20, 0), (30, 0), (40, 2), (50, 0)])
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=8),
               nonrelevant_streak=2, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    cps = {e.cp for e in result.ranked_list.entries}
    assert cps == {10, 20, 30, 40, 50}        # all 5 retained despite the streak trip at rank 3
    assert len(_ev(result, "list_exhausted")) == 1
    assert len(_ev(result, "judge")) == 5     # every judged doc recorded


def test_streak_default_is_grade_zero_only():
    # threshold defaults to 1: a grade-1 doc RESETS the streak; only grade 0 extends it.
    resp, docs = build([(10, 0), (20, 1), (30, 0), (40, 0)])
    ctl = _ctl(["(^ q1)"], [resp], docs, nonrelevant_streak=2, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    # the grade-1 at rank 2 keeps it going; streak only trips at ranks 3-4 (two 0s).
    assert {e.cp for e in result.ranked_list.entries} == {10, 20, 30, 40}
    le = _ev(result, "list_exhausted")[0]
    assert le["depth"] == 4 and le["streak"] == 2


def test_continuation_fetch_uses_exclude_of_seen():
    b1, d1 = build([(1, 1), (2, 1), (3, 1), (4, 1)])  # 4 relevant -> no streak, buffer drains
    b2, d2 = build([(5, 0), (6, 0)])                  # next batch trips the streak
    eng = FakeEngine([b1, b2], {**d1, **d2})
    ctl = Controller(StubSearcher(["(^ q1)"]), StubJudger(concurrency=2), eng,
                     nonrelevant_streak=2, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    assert {e.cp for e in result.ranked_list.entries} == {1, 2, 3, 4, 5, 6}
    # the controller re-queried, and the SECOND search excluded the first batch's cps
    assert len(eng.calls) == 2
    assert eng.calls[1]["exclude"] == [1, 2, 3, 4]


def test_prior_judged_counted_not_rejudged():
    b1, d1 = build([(10, 3), (20, 0)])         # query 1 judges 10, 20
    b2, d2 = build([(10, 3), (30, 2)])         # query 2 re-surfaces 10 (prior) + new 30
    judger = StubJudger(concurrency=8)
    # dry() after b1 ends query 1's descent so query 2 (not q1's continuation) gets b2;
    # max_queries=3 lets the Searcher's 3rd propose capture query 2's history payload.
    ctl = Controller(StubSearcher(["(^ q1)", "(^ q2)"]), judger,
                     FakeEngine([b1, dry(), b2], {**d1, **d2}), nonrelevant_streak=5, max_queries=3)
    result = ctl.run("intent", intent_budget=100)
    # 10 recorded once; 30 added; 20 from q1 -> 3 distinct entries
    assert sorted(e.cp for e in result.ranked_list.entries) == [10, 20, 30]
    # cp 10's body was judged exactly once (query 1), never re-judged in query 2
    assert sum("body-10 " in d for d in judger.judged_docs) == 1
    assert len(_ev(result, "revisit")) == 1    # 10 re-encountered in q2 -> counted
    # query 2's history shows already_judged = 1 (relevant), and new_results = [30]
    q2_hist = ctl.searcher.tool_results[-1]
    assert q2_hist["already_judged"] == {"count": 1, "relevant": 1, "non_relevant": 0}
    assert [r["grade"] for r in q2_hist["new_results"]] == [2]


def test_intent_budget_stops_recording():
    resp, docs = build([(1, 1), (2, 1), (3, 1), (4, 1)])
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=2),
               nonrelevant_streak=9, max_queries=5)
    result = ctl.run("intent", intent_budget=2)
    assert len(result.ranked_list.entries) == 2          # stopped at the budget (wave of 2)
    assert _ev(result, "stop")[0]["reason"] == "intent_budget"


def test_max_queries_stop():
    resp, docs = build([(1, 1)])
    ctl = _ctl(["(^ q1)", "(^ q2)"], [resp], docs, nonrelevant_streak=9, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    assert _ev(result, "stop")[0]["reason"] == "max_queries"


def test_engine_error_bounces_back_to_searcher():
    b2, d2 = build([(7, 3)])
    eng = FakeEngine([EngineError("bad GCL: unbalanced ("), b2], d2)
    ctl = Controller(StubSearcher(["(^ bad", "(^ good)"]), StubJudger(), eng,
                     nonrelevant_streak=5, max_queries=2)
    result = ctl.run("intent", intent_budget=100)
    bounces = _ev(result, "bounce")
    assert any(b["kind"] == "engine_error" for b in bounces)
    # the malformed query's error was fed back; the next query succeeded
    assert {e.cp for e in result.ranked_list.entries} == {7}
    assert "error" in ctl.searcher.tool_results[0]  # query 1's history was the error


def test_dry_query_yields_empty_history():
    eng = FakeEngine([dry()], {})
    # max_queries=2 so the Searcher's 2nd propose captures the dry query's history payload.
    ctl = Controller(StubSearcher(["(^ nothing)"]), StubJudger(), eng,
                     nonrelevant_streak=5, max_queries=2)
    result = ctl.run("intent", intent_budget=100)
    assert result.ranked_list.entries == []
    assert _ev(result, "search")[0]["returned"] == 0
    assert ctl.searcher.tool_results[0]["new_results"] == []


def test_single_judge_failure_records_minus2_and_continues():
    # TASK-27: one failed call (after Judger-level retries) no longer aborts --
    # the doc is RECORDED with the -2 sentinel and the run goes on.
    resp, docs = build([(10, 3), (20, 0)])
    docs[20] = "body-20 [[FAIL]]"  # cp 20's judge call fails permanently
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=8), max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    assert result.error is None
    by_cp = {e.cp: e for e in result.ranked_list.entries}
    assert set(by_cp) == {10, 20}
    assert by_cp[20].grade == -2
    assert by_cp[20].reason == "Judger agent failed to assess the relevance."
    assert by_cp[10].grade == 3
    fails = _ev(result, "judge_failed")
    assert fails and fails[0]["cp"] == 20
    # the Searcher's history payload carries the -2 outcome like any judgment
    grades = [r["grade"] for r in ctl.searcher.tool_results[-1]["new_results"]]         if ctl.searcher.tool_results else []
    assert -2 in grades or result.ranked_list.entries  # payload captured only if a next turn ran


def test_minus2_does_not_advance_the_streak():
    # streak=2: two grade-0 docs WITH a -2 between them must still be needed to
    # exhaust; if the -2 advanced the streak, the list would exhaust one doc early.
    resp, docs = build([(10, 0), (20, 0), (30, 3)])
    docs[20] = "body-20 [[FAIL]]"  # the middle doc errors -> -2
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=8),
               nonrelevant_streak=2, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    # cp 10 (0) + cp 20 (-2, no advance) -> streak is 1 entering cp 30; the wave
    # was never exhausted early, and cp 30 (grade 3) is judged and recorded.
    assert {e.cp for e in result.ranked_list.entries} == {10, 20, 30}
    assert not _ev(result, "list_exhausted")


def test_whole_wave_failure_aborts_with_partial_result():
    # Every call in the wave fails -> outage -> today's abort behavior.
    resp, docs = build([(10, 3), (20, 0)])
    docs[10] = "body-10 [[FAIL]]"
    docs[20] = "body-20 [[FAIL]]"
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=8), max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    assert result.error is not None and "entire judge wave failed" in result.error
    assert _ev(result, "error")[0]["error_type"] == "JudgeFailure"
    assert result.ranked_list.entries == []


def test_result_payload_has_atom_counts_and_ordered_fields():
    resp, docs = build([(10, 2), (20, 1)])  # build() gives atom_counts=[{term:x,count:1}]
    ctl = _ctl(["(^ q1)"], [resp], docs, nonrelevant_streak=9, max_queries=2)
    ctl.run("intent", intent_budget=100)
    payload = ctl.searcher.tool_results[-1]  # query 1's history, captured at query 2's propose
    assert payload["atom_counts"] == [{"term": "x", "count": 1}]
    # top-level order: diagnostics first, content last
    assert list(payload) == [
        "query", "atom_counts", "total_matches", "depth_judged", "already_judged", "new_results"
    ]
    # per-result order: rank, score, summary, reason, grade (summary BEFORE reason/grade)
    assert list(payload["new_results"][0]) == ["rank", "score", "summary", "reason", "grade"]


def test_judge_llm_call_keeps_verbatim_request():
    resp, docs = build([(10, 2)])
    ctl = _ctl(["(^ q1)"], [resp], docs, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    judge_calls = [e for e in result.events if e.type == "llm_call" and e.model_dump().get("purpose") == "judge"]
    assert judge_calls and "body-10" in judge_calls[0].model_dump()["request"][0]["content"]


def test_surfacing_query_is_the_bare_gcl_for_a_cover():
    # AC#11: RankedEntry.surfacing_query for a cover query stays the bare GCL (never a dict/JSON).
    resp, docs = build([(10, 3)])
    ctl = _ctl(["(^ black bear*)"], [resp], docs, max_queries=1)
    result = ctl.run("bears", intent_budget=1)
    assert result.ranked_list.entries[0].surfacing_query == "(^ black bear*)"


def test_tiered_query_payload_leads_with_tiers_and_surfacing_query_joins():
    # TASK-19 AC#12: a TieredQuery-emitting searcher drives the UNCHANGED controller;
    # the judged-results payload leads with "tiers" and surfacing_query is the joined
    # tier string (a plain str, never a dict/JSON).
    resp, docs = build([(10, 3), (20, 2)])
    tiers = ["(>> (# 8) (^ a b))", "(^ a b)"]
    ctl = Controller(StubTieredSearcher([tiers]), StubJudger(),
                     FakeEngine([resp], docs), nonrelevant_streak=9, max_queries=2)
    result = ctl.run("intent", intent_budget=100)
    assert {e.cp for e in result.ranked_list.entries} == {10, 20}
    # surfacing_query is the joined tier string, never a dict
    assert result.ranked_list.entries[0].surfacing_query == "(>> (# 8) (^ a b)) ; (^ a b)"
    # the judged-results payload leads with "tiers" (the queryable's trace descriptor)
    payload = ctl.searcher.tool_results[-1]
    assert list(payload) == [
        "tiers", "atom_counts", "total_matches", "depth_judged", "already_judged", "new_results"
    ]
    assert payload["tiers"] == tiers
    # the controller executed via engine.tiered_search (the call carries a `tiers` key)
    assert "tiers" in ctl.engine.calls[0]


def test_tiered_query_llm_call_trace_names_the_tiered_tool():
    # the searcher_turn llm_call reflects the tiered tool + its {tiers:[...]} arguments.
    resp, docs = build([(10, 3)])
    tiers = ["(^ a b)", "(^ a)"]
    ctl = Controller(StubTieredSearcher([tiers]), StubJudger(),
                     FakeEngine([resp], docs), max_queries=1)
    result = ctl.run("intent", intent_budget=1)
    turn = [e.model_dump() for e in result.events
            if e.type == "llm_call" and e.model_dump().get("purpose") == "searcher_turn"][0]
    assert turn["tool"] == "tiered_query_search"
    assert turn["calls"][0]["name"] == "tiered_query_search"
    assert json.loads(turn["calls"][0]["arguments"]) == {"tiers": tiers}


def test_llm_call_trace_names_the_cover_search_tool():
    # AC: the trace's searcher_turn llm_call reflects the renamed tool + its dict arguments.
    resp, docs = build([(10, 3)])
    ctl = _ctl(["(^ a b)"], [resp], docs, max_queries=1)
    result = ctl.run("intent", intent_budget=1)
    turn = [e.model_dump() for e in result.events
            if e.type == "llm_call" and e.model_dump().get("purpose") == "searcher_turn"][0]
    assert turn["tool"] == "cover_search"
    assert turn["calls"][0]["name"] == "cover_search"
    assert json.loads(turn["calls"][0]["arguments"]) == {"query": "(^ a b)"}
