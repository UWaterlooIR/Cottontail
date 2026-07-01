"""Queryable: the pluggable query-type abstraction (TASK-18).

A `Queryable` is what the Searcher hands the Controller in place of a bare query
string. Each concrete query type fully owns four things:

  - its LLM tool schema (`tool_schema`) and how to build itself from a tool call
    (`from_tool_arguments`);
  - how it runs against the engine (`execute`) -- the engine is PASSED IN, never
    held, so only the Controller (which owns the engine) can execute it, which
    structurally enforces "agents never touch Cottontail";
  - its trace/display forms: `tool_name` + `trace_arguments()` (the structured
    dict the LLM-facing sinks read: the llm_call tool arguments and the leading
    field of the judged-results payload) and `query_string()` (the plain string
    the display/persisted sinks read: the propose/search trace events' `query`
    key and RankedEntry.surfacing_query).

The Controller reads every former `query` sink through these members -- never via
`isinstance` -- so new query types (e.g. TieredQuery, TASK-19) add no controller
code: they just implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from isj_agent.protocol.search import SearchResponse

if TYPE_CHECKING:
    from collections.abc import Sequence

    from isj_agent.engine.base import SearchEngine


class Queryable(ABC):
    """A pluggable query type: schema + construction + execution + trace forms."""

    tool_name: ClassVar[str]  # the LLM-facing tool name (and BaseSearcher routing key)

    @classmethod
    @abstractmethod
    def tool_schema(cls) -> dict:
        """The OpenAI function-tool definition offered to the LLM."""

    @classmethod
    @abstractmethod
    def from_tool_arguments(cls, args: dict) -> Queryable:
        """Build the queryable from the LLM tool call's parsed `arguments` dict.

        MAY raise (KeyError/TypeError/ValueError) on a malformed argument shape;
        BaseSearcher catches that and bounces (yields queryable=None)."""

    @abstractmethod
    def execute(
        self, engine: SearchEngine, *, top_k: int, exclude: Sequence[int], window: int
    ) -> SearchResponse:
        """Run this query against `engine` and return the enriched response.

        The engine is PASSED IN (never held): only the Controller can execute.
        MAY raise EngineError (propagated from the engine) -- the Controller
        catches it and bounces the query back to the Searcher."""

    @abstractmethod
    def trace_arguments(self) -> dict:
        """Structured dict for the LLM-facing sinks (llm_call args + the leading
        field of the judged-results payload). Cover -> {"query": gcl}."""

    @abstractmethod
    def query_string(self) -> str:
        """Plain string for the display/persisted sinks (the propose/search trace
        events' `query` key and RankedEntry.surfacing_query). Distinct from the
        dict `trace_arguments()`."""


@dataclass(frozen=True)
class CoverQuery(Queryable):
    """A single GCL cover query -- the pre-TASK-18 behavior, now a Queryable."""

    gcl: str
    tool_name: ClassVar[str] = "cover_search"

    @classmethod
    def tool_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": cls.tool_name,
                "description": (
                    "Run a GCL cover query over the collection. Returns the NEW documents it "
                    "surfaces, each already graded (0-3) with a reason, plus a count of results "
                    "at those ranks that were already judged by earlier queries."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }

    @classmethod
    def from_tool_arguments(cls, args: dict) -> CoverQuery:
        return cls(gcl=args["query"])

    def execute(
        self, engine: SearchEngine, *, top_k: int, exclude: Sequence[int], window: int
    ) -> SearchResponse:
        return engine.search(self.gcl, top_k=top_k, exclude=exclude, window=window)

    def trace_arguments(self) -> dict:
        return {"query": self.gcl}

    def query_string(self) -> str:
        return self.gcl
