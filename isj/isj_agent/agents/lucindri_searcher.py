"""The LucindriSearcher: authors one full Lucindri query per turn (TASK-33).

A thin BaseSearcher subclass whose only query type is LucindriQuery (the LLM tool
`submit_query`). Its bundled prompt (lucindri_searcher.md) teaches the query language
SELF-CONTAINED and never names "Indri" to the model. Paired with the
LucindriSearchEngine (selected in config), it is a fully docno-native searcher over a
Lucindri HTTP service -- no base or controller changes.

Swap the prompt without touching code via the directable-prompt config field, e.g.
[agents.searcher] prompt = "isj/scouting/lucindri-query/lucindri_prompt_v4.txt".
"""

from importlib.resources import files

from isj_agent.agents.searcher import BaseSearcher
from isj_agent.protocol.queryable import LucindriQuery

_PROMPT: str = (
    files("isj_agent.agents")
    .joinpath("lucindri_searcher.md")
    .read_text(encoding="utf-8")
)


class LucindriSearcher(BaseSearcher):
    """Authors one full Lucindri query per turn (tool: submit_query)."""

    system_prompt: str = _PROMPT
    query_types = [LucindriQuery]
