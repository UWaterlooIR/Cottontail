"""Searcher-prompt framing tests (TASK-44.2): the three arms we run are report-target framed.

Light content checks -- the behavior is exercised via the live model, but the framing markers
(report goal + SEARCH TARGET + strictly-on-target) must be present so the prompt matches the
composed need the Controller now seeds.
"""
import pytest

from isj_agent.agents.lucindri_searcher import LucindriSearcher
from isj_agent.agents.mt_tiered_searcher import MultiTextTieredSearcher
from isj_agent.agents.searcher import Searcher


@pytest.mark.parametrize("cls", [Searcher, MultiTextTieredSearcher, LucindriSearcher])
def test_prompt_is_report_target_framed(cls):
    p = cls.system_prompt
    assert "SEARCH TARGET" in p
    assert "report" in p.lower()
    # strictly-on-target instruction present
    assert "STRICTLY" in p
    # the off-target grade-1 signal is explained
    assert "off" in p.lower() and "target" in p.lower()
