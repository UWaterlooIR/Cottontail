"""SearchCoach protocol + MechanicalSearchCoach + select() + SearchCoachAgent (TASK-40)."""

from types import SimpleNamespace

from isj_agent.agents.search_coach import (
    CoachContext,
    MechanicalSearchCoach,
    SearchCoachAgent,
    select,
)


def _results(grades):
    """A rank-ordered descended list (as the Controller builds it) from a grade sequence."""
    return [{"rank": i + 1, "id": f"d{i}", "score": 100.0 - i, "grade": g,
             "summary": f"sum-{i}", "reason": f"why-{i}", "is_new": True}
            for i, g in enumerate(grades)]


# --- select(): top band (any grade) + deeper high-grade nuggets ----------------

def test_select_worked_example_top5_min3():
    # grades by rank 0 0 1 0 2 0 3 1 2 0 0 1 2 0 1 2 3 0 0 3 0 0 1, top=5, min=3
    # -> shown grades 0 0 1 0 2 3 3 3 at TRUE ranks 1,2,3,4,5,7,17,20 (skips not renumbered).
    grades = [0, 0, 1, 0, 2, 0, 3, 1, 2, 0, 0, 1, 2, 0, 1, 2, 3, 0, 0, 3, 0, 0, 1]
    shown = select(_results(grades), top_k=5, min_grade=3)
    assert [d["grade"] for d in shown] == [0, 0, 1, 0, 2, 3, 3, 3]
    assert [d["rank"] for d in shown] == [1, 2, 3, 4, 5, 7, 17, 20]


def test_select_default_top10_min3():
    grades = [0, 1, 0, 2, 0, 1, 0, 2, 0, 1, 0, 3]   # a grade-3 at rank 12
    shown = select(_results(grades), top_k=10, min_grade=3)
    assert [d["rank"] for d in shown] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12]  # top 10 + the rank-12 nugget


def test_select_shows_prior_judged_doc_in_top_band():
    # a revisit (is_new=False) in the top band is shown like any other doc.
    res = [{"rank": 1, "id": "a", "score": 9.0, "grade": 3, "summary": "s", "reason": "r", "is_new": False},
           {"rank": 2, "id": "b", "score": 8.0, "grade": 1, "summary": "s", "reason": "r", "is_new": True}]
    shown = select(res, top_k=10, min_grade=3)
    assert [(d["rank"], d["grade"]) for d in shown] == [(1, 3), (2, 1)]


# --- MechanicalSearchCoach -----------------------------------------------------

def test_mechanical_coach_defaults():
    c = MechanicalSearchCoach()
    assert c.top_results_to_show == 10 and c.min_show_grade == 3


def test_mechanical_coach_report_and_referenced():
    res = _results([3, 0, 2])   # default top=10 -> all three shown, in rank order
    out = MechanicalSearchCoach().coach(CoachContext(intent="q", stats={}, results=res))
    assert out.referenced == ["d0", "d1", "d2"]
    assert "[rank 1] grade=3" in out.report and "sum-0" in out.report and "why-2" in out.report


def test_mechanical_coach_empty():
    out = MechanicalSearchCoach().coach(CoachContext(intent="q", stats={}, results=[]))
    assert out.report == "(no results surfaced)" and out.referenced == []


# --- SearchCoachAgent (the LLM coach) ------------------------------------------

def _response(content, reasoning="thinking...", ptok=100, ctok=20):
    msg = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=ptok, completion_tokens=ctok, total_tokens=ptok + ctok),
    )


class StubClient:
    """Captures create() kwargs and returns a canned report (or one derived from them)."""

    def __init__(self, handler):
        self._handler = handler
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._handler(kwargs)


def _agent(handler, **kw):
    return SearchCoachAgent(StubClient(handler), "stub-model", **kw)


def test_agent_report_is_the_message_content():
    out = _agent(lambda kw: _response("## coach report body")).coach(
        CoachContext(intent="q", stats={}, results=_results([3, 1, 2]))
    )
    assert out.report == "## coach report body"
    assert out.usage["total_tokens"] == 120 and out.reasoning == "thinking..."


def test_agent_sends_free_text_no_response_format():
    client = StubClient(lambda kw: _response("ok"))
    SearchCoachAgent(client, "m").coach(CoachContext(intent="q", stats={}, results=_results([3])))
    kwargs = client.calls[0]
    assert "response_format" not in kwargs  # free text, not guided JSON
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == 8000 and kwargs["timeout"] == 120.0
    assert kwargs["extra_body"] == {"reasoning_effort": "medium"}


def test_agent_prompt_carries_intent_and_passages_with_handles():
    client = StubClient(lambda kw: _response("ok"))
    SearchCoachAgent(client, "m").coach(
        CoachContext(intent="find the beavers", stats={}, results=_results([3, 0]))
    )
    prompt = client.calls[0]["messages"][0]["content"]
    assert "find the beavers" in prompt
    assert "[R1] grade=3" in prompt and "[R2] grade=0" in prompt
    assert "sum-0" in prompt and "why-1" in prompt


def test_agent_referenced_extraction_is_bracket_tolerant():
    # R1 bracketed, R3 bold, R5 bare -> all extracted, in first-mention order, mapped to docnos.
    # R2 appears twice (dedup); R99 is not a real handle (dropped).
    report = "See [R1] and **R3**, plus R5. Again R1. Also R2 then R2. And bogus R99."
    out = _agent(lambda kw: _response(report)).coach(
        CoachContext(intent="q", stats={}, results=_results([0, 0, 0, 0, 0]))
    )
    # handles R1..R5 -> docnos d0..d4 (input_min_grade default 3, but top_k default 25 shows all 5)
    assert out.referenced == ["d0", "d2", "d4", "d1"]  # R1,R3,R5,R2 in first-mention order; R99 gone


def test_agent_no_citations_is_empty_not_a_failure():
    out = _agent(lambda kw: _response("A report with no citations at all.")).coach(
        CoachContext(intent="q", stats={}, results=_results([3, 2]))
    )
    assert out.referenced == []


def test_agent_input_selection_limits_passages_shown():
    # input_top_k=2, input_min_grade=3: ranks 1-2 (any grade) + the deeper grade-3 at rank 5.
    client = StubClient(lambda kw: _response("ok"))
    SearchCoachAgent(client, "m", input_top_k=2, input_min_grade=3).coach(
        CoachContext(intent="q", stats={}, results=_results([1, 0, 1, 1, 3]))
    )
    prompt = client.calls[0]["messages"][0]["content"]
    assert "[R1] grade=1" in prompt and "[R2] grade=0" in prompt and "[R3] grade=3" in prompt
    assert "[R4]" not in prompt  # only three passages shown
    assert "sum-4" in prompt  # the deep grade-3 nugget (rank 5) is R3


# --- novelty signal: revisit markers + RESULT NOVELTY line (rut detection) -----

def test_agent_marks_revisits_and_reports_novelty():
    # R1 new, R2 revisit, R3 new; total_matches=500.
    res = [
        {"rank": 1, "id": "a", "score": 9.0, "grade": 3, "summary": "s1", "reason": "r1", "is_new": True},
        {"rank": 2, "id": "b", "score": 8.0, "grade": 2, "summary": "s2", "reason": "r2", "is_new": False},
        {"rank": 3, "id": "c", "score": 7.0, "grade": 1, "summary": "s3", "reason": "r3", "is_new": True},
    ]
    client = StubClient(lambda kw: _response("ok"))
    SearchCoachAgent(client, "m").coach(
        CoachContext(intent="q", stats={"count": 3, "relevant": 2, "total_matches": 500}, results=res))
    p = client.calls[0]["messages"][0]["content"]
    # per-passage revisit marker: only the revisit (R2) is marked
    assert "[R2] grade=2  (already judged on an earlier query)" in p
    r1_block = p.split("[R1]")[1].split("[R2]")[0]
    assert "already judged" not in r1_block  # a new passage carries no marker
    # RESULT NOVELTY summary line
    assert "3 result(s): 2 newly surfaced and 1 already judged on earlier queries" in p
    assert "collection holds 500 document(s)" in p


def test_novelty_line_omits_total_matches_when_none():
    res = [{"rank": 1, "id": "a", "score": 9.0, "grade": 2, "summary": "s", "reason": "r", "is_new": False}]
    client = StubClient(lambda kw: _response("ok"))
    SearchCoachAgent(client, "m").coach(
        CoachContext(intent="q", stats={"count": 1, "relevant": 1, "total_matches": None}, results=res))
    p = client.calls[0]["messages"][0]["content"]
    assert "1 result(s): 0 newly surfaced and 1 already judged on earlier queries" in p
    assert "collection holds" not in p
