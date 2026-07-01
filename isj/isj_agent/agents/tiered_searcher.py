"""The TieredSearcher: authors a tiered precise->broad GCL cascade per turn (TASK-20).

A thin concrete `BaseSearcher` (see searcher.py) that swaps the cover query type for
the tiered one: it exposes ONLY the `tiered_query_search` tool and emits one
`TieredQuery` per turn (an ordered list of GCL cover tiers). Everything else -- the
LLM round-trip, tool exposure, tool-call routing, and the defensive bounce on a
malformed/absent call -- is inherited from `BaseSearcher` unchanged, so this needs no
controller or base changes. Select it via `[agents.searcher].class`:

    class = "isj_agent.agents.tiered_searcher.TieredSearcher"
"""

from __future__ import annotations

from importlib.resources import files

from isj_agent.agents.searcher import BaseSearcher
from isj_agent.protocol.queryable import TieredQuery

_PROMPT: str = (
    files("isj_agent.agents").joinpath("tiered_searcher.md").read_text(encoding="utf-8")
)


class TieredSearcher(BaseSearcher):
    """The tiered searcher: one precise->broad GCL cascade per turn."""

    prompt: str = _PROMPT
    system_prompt: str = _PROMPT  # alias; the controller seeds msgs from this
    query_types: list[type[TieredQuery]] = [TieredQuery]
