"""The SearchEngine contract for the Searcher (B1, TASK-5.5).

A `typing.Protocol` (structural typing) so both the scripted `FakeEngine` (B1,
used by B2's tests) and the real `HttpSearchEngine` (C1) satisfy it without
inheritance. The methods mirror the C++ server's tools: `search` <-> cover_search,
`read` <-> get_document. There is NO `judge` method -- judging is the controller's
job in B2; the engine only searches and reads.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from isj_agent.protocol.search import SearchResponse


class EngineError(Exception):
    """Any engine-side failure, carrying a human-readable message.

    The engine is the source of truth: there is NO Python-side query validation.
    An invalid GCL query the C++ engine rejects is one cause; a transport/HTTP
    failure (C1) is another. The B2 controller handles EngineError generally by
    feeding `str(error)` back to the model so it can self-correct.
    """


@runtime_checkable
class SearchEngine(Protocol):
    """The typed boundary between the Searcher and an engine (cp-native)."""

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        exclude: Sequence[int] = (),
        window: int = 75,
    ) -> SearchResponse:
        """Run a cover query; return the enriched cover_search response.

        `exclude` is the judged set as cp integers (the engine is stateless; the
        agent passes its whole judged set each call). MAY raise EngineError on any
        engine-side failure (e.g. an invalid query the engine rejects).
        """
        ...

    def read(self, cp: int) -> str | None:
        """Return the full document body for `cp`, or None if cp is unknown.

        Intentionally part of the engine contract for FUTURE use -- a possible
        agent read-tool and the downstream RAG grounding / Writer step -- even
        though the B2 MVP does not call it. Do NOT remove as unused. MAY raise
        EngineError on an engine-side failure.
        """
        ...
