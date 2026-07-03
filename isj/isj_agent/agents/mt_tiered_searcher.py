"""The MultiTextTieredSearcher: authors a MultiText DSL program per turn (TASK-22).

The THIRD interchangeable searcher (alongside the plain Searcher and the JSON
TieredSearcher). A thin concrete `BaseSearcher` that swaps in the program query
type: it exposes ONLY the `submit_tiered_query` tool and emits one
`MultiTextProgram` per turn. The program is compiled SERVER-side; compile
diagnostics bounce back through the controller's normal EngineError path and the
model self-corrects (validated in the TASK-26 scouting,
isj/scouting/multitext-dsl-2/captured/FINDINGS.md). Everything else -- the LLM
round-trip, tool exposure, routing, and the malformed-call bounce -- is inherited
from `BaseSearcher` unchanged, so this needs no controller or base changes.
Select it via `[agents.searcher].class`:

    class = "isj_agent.agents.mt_tiered_searcher.MultiTextTieredSearcher"
"""

from __future__ import annotations

from importlib.resources import files

from isj_agent.agents.searcher import BaseSearcher
from isj_agent.protocol.queryable import MultiTextProgram

_PROMPT: str = (
    files("isj_agent.agents")
    .joinpath("mt_tiered_searcher.md")
    .read_text(encoding="utf-8")
)


class MultiTextTieredSearcher(BaseSearcher):
    """The MultiText searcher: one DSL program (macros + @rank) per turn."""

    prompt: str = _PROMPT
    system_prompt: str = _PROMPT  # alias; the controller seeds msgs from this
    query_types: list[type[MultiTextProgram]] = [MultiTextProgram]
