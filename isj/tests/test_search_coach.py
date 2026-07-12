"""SearchCoach protocol + MechanicalSearchCoach + select() (TASK-40 phase 1)."""

from isj_agent.agents.search_coach import (
    CoachContext,
    MechanicalSearchCoach,
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
