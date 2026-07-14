"""compose_need tests (TASK-44.1): the labeled per-intent need string.

The three section labels (USER REQUEST / ANALYSIS / SEARCH TARGET) are the contract the Searcher,
Judger, and Coach prompts rely on, so pin them and the target marking here.
"""
from isj_agent.need import compose_need


def test_need_has_the_three_labeled_sections():
    need = compose_need("the whole request", ["alpha", "beta", "gamma"], "beta")
    assert "USER REQUEST" in need
    assert "ANALYSIS" in need
    assert "SEARCH TARGET" in need
    assert "the whole request" in need


def test_need_lists_all_interpretations_and_marks_the_target():
    need = compose_need("Q", ["alpha", "beta", "gamma"], "beta")
    for interp in ("alpha", "beta", "gamma"):
        assert interp in need
    # only the target line is marked
    marked = [ln for ln in need.splitlines() if "<-- SEARCH TARGET" in ln]
    assert len(marked) == 1
    assert "beta" in marked[0]


def test_need_states_the_target_in_its_own_section():
    need = compose_need("Q", ["alpha", "beta"], "beta")
    tail = need.split("SEARCH TARGET (the one component to find information for now):")[1]
    assert tail.strip() == "beta"


def test_single_interpretation_need():
    need = compose_need("Q", ["only"], "only")
    assert need.count("<-- SEARCH TARGET") == 1
    assert "  1. only      <-- SEARCH TARGET" in need


def test_duplicate_interpretations_mark_only_the_first():
    # defensive: identical strings shouldn't double-mark
    need = compose_need("Q", ["dup", "dup"], "dup")
    assert need.count("<-- SEARCH TARGET") == 1
