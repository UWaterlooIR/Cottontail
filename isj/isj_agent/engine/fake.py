"""A deterministic, scripted SearchEngine for testing the Searcher (B1, TASK-5.5).

FakeEngine lets B2's tests drive the agent loop with no C++ engine, no server, and
no network: each `search()` returns the next scripted `SearchResponse` (or raises a
scripted `EngineError`). It does NOT parse GCL or react to the query content --
real query/cover semantics are validated in C1 against the live engine; here the
point is deterministic, inspectable behavior.
"""

from collections.abc import Sequence

from isj_agent.engine.base import EngineError
from isj_agent.protocol.search import SearchResponse


class FakeEngine:
    """A SearchEngine driven by an ordered script of responses/errors.

    Each entry is either a `SearchResponse` to return or an `EngineError` to raise.
    `docs` maps cp -> body text for `read()`.
    """

    def __init__(
        self,
        script: list[SearchResponse | EngineError],
        docs: dict[int, str] | None = None,
    ):
        self._script = list(script)
        self._docs = docs or {}
        self._i = 0
        # Public record of every search() call's arguments (including calls that
        # raise), so tests can assert what the controller sent.
        self.calls: list[dict] = []

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        exclude: Sequence[int] = (),
        window: int = 75,
    ) -> SearchResponse:
        self.calls.append(
            {"query": query, "top_k": top_k, "exclude": list(exclude), "window": window}
        )
        if self._i >= len(self._script):
            # Script exhausted: a dry response so the agent loop terminates.
            return SearchResponse(
                total_matches=0, unjudged_matches=0, atom_counts=[], results=[]
            )
        entry = self._script[self._i]
        self._i += 1
        if isinstance(entry, EngineError):
            raise entry
        return _apply_exclude(entry, set(exclude))

    def read(self, cp: int) -> str | None:
        return self._docs.get(cp)


def _apply_exclude(resp: SearchResponse, exclude: set[int]) -> SearchResponse:
    """Mirror the engine's cp post-filter on a scripted batch: drop Hits whose cp
    is excluded, decrement unjudged_matches by the number removed (total_matches is
    corpus-wide breadth and is unchanged), and re-rank the survivors 1..N."""
    if not exclude:
        return resp
    survivors = [h for h in resp.results if h.cp not in exclude]
    removed = len(resp.results) - len(survivors)
    reranked = [h.model_copy(update={"rank": i}) for i, h in enumerate(survivors, 1)]
    return resp.model_copy(
        update={
            "results": reranked,
            "unjudged_matches": resp.unjudged_matches - removed,
        }
    )
