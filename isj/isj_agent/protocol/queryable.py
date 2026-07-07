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


@dataclass(frozen=True)
class TieredQuery(Queryable):
    """An ordered precise->broad cascade of GCL cover tiers (TASK-19).

    Thin over the server's `tiered_query_search` tool: the cascade itself -- per-tier
    ranking, cross-tier de-duplication, per-tier summaries, the union `atom_counts`,
    and the exact distinct match count -- runs in the C++ handler. This class only
    carries the tiers, exposes the tool schema + trace forms, and forwards `execute`
    to `engine.tiered_search`. `tiers` is a tuple so the dataclass stays frozen and
    hashable (parity with CoverQuery); the trace/JSON forms re-expose it as a list.
    """

    tiers: tuple[str, ...]
    tool_name: ClassVar[str] = "tiered_query_search"

    @classmethod
    def tool_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": cls.tool_name,
                "description": (
                    "Run an ORDERED list of GCL cover tiers as a de-duplicated CASCADE: "
                    "each tier in turn, most precise first and broadest last. A document "
                    "found by an earlier (tighter) tier is never re-listed by a later "
                    "(looser) one, and tighter tiers outrank broader ones. Returns the NEW "
                    "documents the cascade surfaces, each already graded (0-3) with a reason "
                    "and a summary from the tier that surfaced it, plus the union atom_counts "
                    "and the count of distinct documents matched across all tiers."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tiers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "The cover tiers as GCL strings, ordered most precise to "
                                "most broad."
                            ),
                        }
                    },
                    "required": ["tiers"],
                },
            },
        }

    @classmethod
    def from_tool_arguments(cls, args: dict) -> TieredQuery:
        tiers = args["tiers"]  # KeyError -> BaseSearcher bounces
        if (
            not isinstance(tiers, list)
            or not tiers
            or not all(isinstance(t, str) for t in tiers)
        ):
            raise ValueError("tiers must be a non-empty list of GCL strings")
        return cls(tiers=tuple(tiers))

    def execute(
        self, engine: SearchEngine, *, top_k: int, exclude: Sequence[int], window: int
    ) -> SearchResponse:
        return engine.tiered_search(
            list(self.tiers), top_k=top_k, exclude=exclude, window=window
        )

    def trace_arguments(self) -> dict:
        return {"tiers": list(self.tiers)}

    def query_string(self) -> str:
        return " ; ".join(self.tiers)


@dataclass(frozen=True)
class MultiTextProgram(Queryable):
    """A MultiText DSL program: macro definitions + one @rank tier line (TASK-22).

    The third query type. The program text is compiled SERVER-side (a fresh
    cottontail::Mt per request); its tiers then run the same cascade as
    TieredQuery, so the response shape is identical. A compile failure comes back
    as an EngineError carrying the per-statement compiler diagnostics -- the
    controller's normal bounce delivers them to the model, which self-corrects
    (validated in the TASK-26 scouting). The LLM-facing tool keeps the scouted
    name `submit_tiered_query`.
    """

    program: str
    tool_name: ClassVar[str] = "submit_tiered_query"

    @classmethod
    def tool_schema(cls) -> dict:
        return {
            "type": "function",
            "function": {
                "name": cls.tool_name,
                "description": (
                    "Submit your MultiText program: the facet/tier macro definitions "
                    "(one per line, `name = expr`) followed by a single `@rank` line "
                    "listing the tier macros in precise->broad order. The program is "
                    "compiled server-side; compile errors are returned as the tool "
                    "result for you to fix. Returns the NEW documents the tier "
                    "cascade surfaces, each already graded (0-3) with a reason and a "
                    "summary from the tier that surfaced it, plus per-term "
                    "atom_counts and the count of distinct documents matched."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "program": {
                            "type": "string",
                            "description": (
                                "The full program text: macro definitions, one per "
                                "line, then one @rank line."
                            ),
                        }
                    },
                    "required": ["program"],
                },
            },
        }

    @classmethod
    def from_tool_arguments(cls, args: dict) -> MultiTextProgram:
        program = args["program"]  # KeyError -> BaseSearcher bounces
        if not isinstance(program, str) or not program.strip():
            raise ValueError("program must be a non-empty MultiText program string")
        return cls(program=program)

    def execute(
        self, engine: SearchEngine, *, top_k: int, exclude: Sequence[int], window: int
    ) -> SearchResponse:
        return engine.multitext_search(
            self.program, top_k=top_k, exclude=exclude, window=window
        )

    def trace_arguments(self) -> dict:
        return {"program": self.program}

    def query_string(self) -> str:
        return self.program
