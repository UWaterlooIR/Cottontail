"""Coach-prompt framing test (TASK-44.4): report goal + SEARCH TARGET + the new grade legend."""
from importlib.resources import files


def test_coach_prompt_is_report_target_framed():
    p = files("isj_agent.agents").joinpath("search_coach.md").read_text(encoding="utf-8")
    assert "SEARCH TARGET" in p
    assert "report" in p.lower()
    # the updated grade legend (must match the judger's rubric: grade 1 = report-not-target)
    assert "1 = relevant to the REPORT but NOT the target" in p
    # still a template with the composed-need + passages slots
    assert "{intent}" in p and "{passages}" in p
