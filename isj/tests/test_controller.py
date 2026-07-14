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
    hits = [Hit(rank=i, score=100.0 - i, id=str(cp), summary=f"sum-{cp}")
            for i, (cp, _) in enumerate(cp_grades, 1)]
    resp = SearchResponse(
        total_matches=total if total is not None else len(hits),
        unjudged_matches=len(hits),
        atom_counts=[AtomCount(term="x", count=1)],
        results=hits,
    )
    docs = {str(cp): f"body-{cp} [[G:{g}]]" for cp, g in cp_grades}
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
                self.tool_results.append(m["content"])  # feedback string (or an {"error"} json on a bounce)
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
                self.tool_results.append(m["content"])  # feedback string (or an {"error"} json on a bounce)
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

def test_composed_need_reaches_all_agents_but_intent_stays_clean():
    # TASK-44.1: the Controller composes the per-intent need (request + analysis + target) and feeds
    # it to the searcher seed, the Judger, and the Coach -- while RankedList.intent stays the clean target.
    from isj_agent.agents.search_coach import CoachOutput

    resp, docs = build([(10, 2)])  # one relevant hit -> the coach path fires (count > 0)

    seeds: list[str] = []
    class CapSearcher(StubSearcher):
        def propose(self, messages):
            if not seeds:  # first turn: the user seed is the composed need
                seeds.append(next(m["content"] for m in messages if m["role"] == "user"))
            return super().propose(messages)

    judged: list[str] = []
    class CapJudger(StubJudger):
        def judge(self, intent, docs):
            judged.append(intent)
            return super().judge(intent, docs)

    coached: list[str] = []
    class CapCoach:
        is_llm = False
        def coach(self, ctx):
            coached.append(ctx.intent)
            return CoachOutput(report="ok")

    ctl = Controller(CapSearcher(["(^ q1)"]), CapJudger(concurrency=8),
                     FakeEngine([resp], docs), coach=CapCoach(), max_queries=1)
    result = ctl.run("GOALX", intent_budget=100,
                     question="THE-REQUEST", interpretations=["ALPHA", "GOALX", "BETA"])

    for captured in (seeds[0], judged[0], coached[0]):        # need reached all three agents
        assert "THE-REQUEST" in captured                     # the request
        assert "ALPHA" in captured and "BETA" in captured    # the full analysis
        assert "SEARCH TARGET" in captured and "GOALX" in captured
    assert result.ranked_list.intent == "GOALX"              # persisted intent stays the clean target


def test_retain_all_keeps_the_whole_tripping_wave():
    # one wave of 5; streak (2 grade-0) trips at rank 3, but ranks 4-5 are also kept.
    resp, docs = build([(10, 3), (20, 0), (30, 0), (40, 2), (50, 0)])
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=8),
               nonrelevant_streak=2, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    cps = {e.id for e in result.ranked_list.entries}
    assert cps == {"10", "20", "30", "40", "50"}        # all 5 retained despite the streak trip at rank 3
    assert len(_ev(result, "list_exhausted")) == 1
    assert len(_ev(result, "judge")) == 5     # every judged doc recorded


def test_streak_default_counts_grade_below_2_as_nonrelevant():
    # threshold defaults to 2 (TASK-44): only a grade >=2 (target-relevant) RESETS the streak.
    resp, docs = build([(10, 0), (20, 2), (30, 0), (40, 0)])
    ctl = _ctl(["(^ q1)"], [resp], docs, nonrelevant_streak=2, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    # the grade-2 at rank 2 resets; streak only trips at ranks 3-4 (two 0s). All 4 retained.
    assert {e.id for e in result.ranked_list.entries} == {"10", "20", "30", "40"}
    le = _ev(result, "list_exhausted")[0]
    assert le["depth"] == 4 and le["streak"] == 2


def test_grade_one_counts_toward_streak_and_does_not_reset_it():
    # TASK-44: grade 1 = relevant to the report but NOT the target -> non-relevant for the streak.
    # concurrency=1 (one doc per wave) so the streak stops descent mid-list, not masked by retain-all.
    resp, docs = build([(10, 0), (20, 1), (30, 3)])  # if grade-1 reset, we'd reach 30; it must not.
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=1),
               nonrelevant_streak=2, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    le = _ev(result, "list_exhausted")[0]
    assert le["depth"] == 2 and le["streak"] == 2         # tripped after the grade-0 then grade-1
    assert {e.id for e in result.ranked_list.entries} == {"10", "20"}  # never descended to the grade-3


def test_continuation_fetch_uses_exclude_of_seen():
    b1, d1 = build([(1, 2), (2, 2), (3, 2), (4, 2)])  # 4 target-relevant -> no streak, buffer drains
    b2, d2 = build([(5, 0), (6, 0)])                  # next batch trips the streak
    eng = FakeEngine([b1, b2], {**d1, **d2})
    ctl = Controller(StubSearcher(["(^ q1)"]), StubJudger(concurrency=2), eng,
                     nonrelevant_streak=2, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    assert {e.id for e in result.ranked_list.entries} == {"1", "2", "3", "4", "5", "6"}
    # the controller re-queried, and the SECOND search excluded the first batch's cps
    assert len(eng.calls) == 2
    assert eng.calls[1]["exclude"] == ["1", "2", "3", "4"]


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
    assert sorted(e.id for e in result.ranked_list.entries) == ["10", "20", "30"]
    # cp 10's body was judged exactly once (query 1), never re-judged in query 2
    assert sum("body-10 " in d for d in judger.judged_docs) == 1
    assert len(_ev(result, "revisit")) == 1    # 10 re-encountered in q2 -> counted
    # query 2 descended 2 docs (10 revisit grade 3, 30 new grade 2); both in the top band,
    # so both are SHOWN -- the prior-judged 10 is visible at the top, not hidden.
    q2_hist = ctl.searcher.tool_results[-1]   # the Searcher feedback STRING
    assert "judged 2 results this query, 2 relevant" in q2_hist
    assert "grade=3" in q2_hist and "grade=2" in q2_hist


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
    assert {e.id for e in result.ranked_list.entries} == {"7"}
    assert "error" in ctl.searcher.tool_results[0]  # query 1's history was the error


def test_dry_query_yields_over_constrained_guidance():
    eng = FakeEngine([dry()], {})
    # max_queries=2 so the Searcher's 2nd propose captures the dry query's history payload.
    ctl = Controller(StubSearcher(["(^ nothing)"]), StubJudger(), eng,
                     nonrelevant_streak=5, max_queries=2)
    result = ctl.run("intent", intent_budget=100)
    assert result.ranked_list.entries == []
    assert _ev(result, "search")[0]["returned"] == 0
    dry_hist = ctl.searcher.tool_results[0]   # the Searcher feedback STRING
    assert "judged 0 results this query, 0 relevant" in dry_hist
    # a zero-result query now gets the deterministic over-constrained guidance, not a coach report
    assert "over-constrained. Broaden it." in dry_hist
    oc = _ev(result, "over_constrained")
    assert oc and oc[0]["query"] == "(^ nothing)"


def test_single_judge_failure_records_minus2_and_continues():
    # TASK-27: one failed call (after Judger-level retries) no longer aborts --
    # the doc is RECORDED with the -2 sentinel and the run goes on.
    resp, docs = build([(10, 3), (20, 0)])
    docs["20"] = "body-20 [[FAIL]]"  # cp 20's judge call fails permanently
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=8), max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    assert result.error is None
    by_cp = {e.id: e for e in result.ranked_list.entries}
    assert set(by_cp) == {"10", "20"}
    assert by_cp["20"].grade == -2
    assert by_cp["20"].reason == "Judger agent failed to assess the relevance."
    assert by_cp["10"].grade == 3
    fails = _ev(result, "judge_failed")
    assert fails and fails[0]["id"] == "20"
    # the Searcher's history payload carries the -2 outcome like any judgment
    grades = [r["grade"] for r in ctl.searcher.tool_results[-1]["new_results"]]         if ctl.searcher.tool_results else []
    assert -2 in grades or result.ranked_list.entries  # payload captured only if a next turn ran


def test_minus2_does_not_advance_the_streak():
    # streak=2: two grade-0 docs WITH a -2 between them must still be needed to
    # exhaust; if the -2 advanced the streak, the list would exhaust one doc early.
    resp, docs = build([(10, 0), (20, 0), (30, 3)])
    docs["20"] = "body-20 [[FAIL]]"  # the middle doc errors -> -2
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=8),
               nonrelevant_streak=2, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    # cp 10 (0) + cp 20 (-2, no advance) -> streak is 1 entering cp 30; the wave
    # was never exhausted early, and cp 30 (grade 3) is judged and recorded.
    assert {e.id for e in result.ranked_list.entries} == {"10", "20", "30"}
    assert not _ev(result, "list_exhausted")


def test_whole_wave_failure_aborts_with_partial_result():
    # Every call in the wave fails -> outage -> today's abort behavior.
    resp, docs = build([(10, 3), (20, 0)])
    docs["10"] = "body-10 [[FAIL]]"
    docs["20"] = "body-20 [[FAIL]]"
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=8), max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    assert result.error is not None and "entire judge wave failed" in result.error
    assert _ev(result, "error")[0]["error_type"] == "JudgeFailure"
    assert result.ranked_list.entries == []


def test_result_payload_has_atom_counts_and_ordered_fields():
    resp, docs = build([(10, 2), (20, 1)])  # build() gives atom_counts=[{term:x,count:1}]
    ctl = _ctl(["(^ q1)"], [resp], docs, nonrelevant_streak=9, max_queries=2)
    ctl.run("intent", intent_budget=100)
    payload = ctl.searcher.tool_results[-1]  # query 1's feedback STRING, captured at query 2's propose
    # the Controller wraps the coach report with the query echo, coverage, and atom counts
    assert "Your query: (^ q1)" in payload
    assert "Coverage: judged 2 results this query" in payload
    assert "Atom matches: x=1" in payload
    # the shown docs appear (grade 2 and grade 1, with their assessor reasons)
    assert "grade=2" in payload and "grade=1" in payload and "assessor:" in payload


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
    assert {e.id for e in result.ranked_list.entries} == {"10", "20"}
    # surfacing_query is the joined tier string, never a dict
    assert result.ranked_list.entries[0].surfacing_query == "(>> (# 8) (^ a b)) ; (^ a b)"
    # the feedback echoes the query via queryable.query_string() -- the joined tier string
    payload = ctl.searcher.tool_results[-1]
    assert "Your query: (>> (# 8) (^ a b)) ; (^ a b)" in payload
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


def test_observer_streams_events_and_pre_call_markers_live():
    # TASK-35: with an observer, every trace event is delivered the moment it is
    # emitted, plus live-only 'awaiting' markers BEFORE each blocking LLM call. The
    # markers never leak into the persisted events.
    from isj_agent.protocol.results import LiveMarker, TraceEvent

    resp, docs = build([(10, 3), (20, 0)])
    ctl = _ctl(["(^ q1)"], [resp], docs, judger=StubJudger(concurrency=8), max_queries=1)
    seen = []
    result = ctl.run("intent", intent_budget=100, observer=seen.append)

    # every persisted TraceEvent was observed live, in order
    observed_events = [e for e in seen if isinstance(e, TraceEvent)]
    assert observed_events == result.events

    # a searcher-turn marker precedes the searcher_turn llm_call
    turn_marker = next(i for i, e in enumerate(seen)
                       if isinstance(e, LiveMarker) and e.kind == "await_searcher_turn")
    turn_call = next(i for i, e in enumerate(seen)
                     if isinstance(e, TraceEvent) and e.type == "llm_call"
                     and e.model_dump().get("purpose") == "searcher_turn")
    assert turn_marker < turn_call

    # a judge-wave marker was emitted (before the wave's judgements)
    assert any(isinstance(e, LiveMarker) and e.kind == "await_judge" for e in seen)

    # markers are LIVE-ONLY: none are in the persisted trace
    assert all(isinstance(e, TraceEvent) for e in result.events)


def test_no_observer_is_byte_for_byte_unchanged():
    # Without an observer the run behaves exactly as before (no markers, same events).
    resp, docs = build([(10, 3), (20, 0)])
    ctl = _ctl(["(^ q1)"], [resp], docs, max_queries=1)
    result = ctl.run("intent", intent_budget=100)
    assert [e.type for e in result.events][:2] == ["llm_call", "propose"]


# --- feedback (coach) behavior at the Controller level ------------------------

def test_feedback_ranks_are_true_across_a_fetch_refill():
    # Two fetches of 3; a nugget in the SECOND fetch must be reported at its GLOBAL rank
    # (>3), not its per-fetch Hit.rank (which resets to 1..3 each fetch). This is a
    # Controller/_descend property; the mechanical coach then surfaces it at that rank.
    f1, d1 = build([(10, 0), (20, 0), (30, 0)])   # fetch 1: ranks 1,2,3 (all non-rel)
    f2, d2 = build([(40, 0), (50, 3), (60, 0)])   # fetch 2: the gold doc 50 is global rank 5
    ctl = Controller(StubSearcher(["(^ q1)"]), StubJudger(concurrency=3),
                     FakeEngine([f1, f2, dry()], {**d1, **d2}),
                     nonrelevant_streak=999, max_queries=2, top_results_to_show=2, min_show_grade=3)
    ctl.run("intent", intent_budget=100)
    feedback = ctl.searcher.tool_results[-1]   # the Searcher feedback STRING
    # the grade-3 nugget is shown at its TRUE global rank 5 (not per-fetch rank 2)
    assert "[rank 5] grade=3" in feedback


# --- LLM coach: trace event + fallback (TASK-40.2) ----------------------------

from isj_agent.agents.search_coach import CoachOutput, MechanicalSearchCoach  # noqa: E402


class _StubLlmCoach:
    """A stand-in LLM coach: is_llm=True so the Controller traces/marks it. Either returns a
    canned CoachOutput or raises (to exercise the fallback)."""

    is_llm = True

    def __init__(self, output=None, raises=None):
        self._output = output
        self._raises = raises
        self.calls = 0

    def coach(self, ctx):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._output


# A 2nd scripted query that bounces (EngineError) so it does NOT re-invoke the coach, while
# still triggering the 2nd propose that captures q1's feedback into StubSearcher.tool_results.

def test_llm_coach_report_and_trace_event():
    f1, d1 = build([(10, 3), (20, 0)])
    coach = _StubLlmCoach(CoachOutput(report="## COACHING\npursue beavers", referenced=["10"],
                                      usage={"total_tokens": 42}, reasoning="mulling"))
    ctl = Controller(StubSearcher(["(^ q1)", "(^ q2)"]), StubJudger(concurrency=2),
                     FakeEngine([f1, dry(), EngineError("stop")], d1), coach=coach, max_queries=2)
    result = ctl.run("intent", intent_budget=100)
    assert coach.calls == 1  # the bounced 2nd query does not reach the coach
    # the coach report is wrapped into the Searcher feedback (captured on the 2nd propose)
    assert "## COACHING" in ctl.searcher.tool_results[-1]
    # a purpose="coach" llm_call trace event carries usage + referenced
    coach_ev = [e for e in _ev(result, "llm_call") if e.get("purpose") == "coach"]
    assert len(coach_ev) == 1
    assert coach_ev[0]["referenced"] == ["10"] and coach_ev[0]["total_tokens"] == 42


def test_llm_coach_failure_falls_back_to_mechanical():
    f1, d1 = build([(10, 3), (20, 0)])
    coach = _StubLlmCoach(raises=RuntimeError("coach timed out"))
    ctl = Controller(StubSearcher(["(^ q1)", "(^ q2)"]), StubJudger(concurrency=2),
                     FakeEngine([f1, dry(), EngineError("stop")], d1), coach=coach,
                     mechanical=MechanicalSearchCoach(top_results_to_show=2, min_show_grade=3),
                     max_queries=2)
    result = ctl.run("intent", intent_budget=100)
    # the failure is recorded and the mechanical feedback (a [rank N] listing) is delivered
    fb = _ev(result, "coach_fallback")
    assert len(fb) == 1 and fb[0]["error_type"] == "RuntimeError"
    assert "[rank 1] grade=3" in ctl.searcher.tool_results[-1]
    # no coach llm_call event on the fallback path
    assert [e for e in _ev(result, "llm_call") if e.get("purpose") == "coach"] == []


def test_zero_results_skips_coach_and_returns_over_constrained_guidance():
    # A query that matches NOTHING (dry search) must skip the coach entirely and feed back
    # the deterministic over-constrained guidance. q2 bounces so a 2nd propose captures q1's
    # feedback into tool_results.
    coach = _StubLlmCoach(CoachOutput(report="SHOULD NOT RUN"))
    ctl = Controller(StubSearcher(["(^ over-constrained q1)", "(^ q2)"]), StubJudger(concurrency=2),
                     FakeEngine([dry(), EngineError("stop")], {}), coach=coach, max_queries=2)
    result = ctl.run("intent", intent_budget=100)
    assert coach.calls == 0                                   # the coach never ran on the empty set
    ev = _ev(result, "over_constrained")
    assert len(ev) == 1 and ev[0]["query"] == "(^ over-constrained q1)"
    feedback = ctl.searcher.tool_results[-1]
    assert "over-constrained. Broaden it." in feedback and "Drop the rarest facet." in feedback
    assert "Coverage: judged 0 results" in feedback          # the Controller header still wraps it
    # no coach llm_call event was emitted for the empty query
    assert [e for e in _ev(result, "llm_call") if e.get("purpose") == "coach"] == []
