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
    `docs` maps id (docno) -> body text for `read()`.
    """

    def __init__(
        self,
        script: list[SearchResponse | EngineError],
        docs: dict[str, str] | None = None,
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
        exclude: Sequence[str] = (),
        window: int = 75,
    ) -> SearchResponse:
        self.calls.append(
            {"query": query, "top_k": top_k, "exclude": list(exclude), "window": window}
        )
        return self._next(set(exclude))

    def tiered_search(
        self,
        tiers: Sequence[str],
        *,
        top_k: int = 10,
        exclude: Sequence[str] = (),
        window: int = 75,
    ) -> SearchResponse:
        # The real cascade (per-tier ranking, cross-tier de-dup, per-tier summaries)
        # runs in the C++ handler; this fake just returns the next scripted (already
        # merged) response, mirroring the server's cp exclude post-filter. The call is
        # recorded with a `tiers` key so tests can tell tiered_search from search.
        self.calls.append(
            {"tiers": list(tiers), "top_k": top_k, "exclude": list(exclude), "window": window}
        )
        return self._next(set(exclude))

    def multitext_search(
        self,
        program: str,
        *,
        top_k: int = 10,
        exclude: Sequence[str] = (),
        window: int = 75,
    ) -> SearchResponse:
        # Server-side compilation is faked the same way as the cascade: the next
        # scripted entry is returned (or raised, for a scripted EngineError whose
        # message stands in for the compiler diagnostics). Recorded with a
        # `program` key so tests can tell the three search flavors apart.
        self.calls.append(
            {"program": program, "top_k": top_k, "exclude": list(exclude), "window": window}
        )
        return self._next(set(exclude))

    def _next(self, exclude: set[str]) -> SearchResponse:
        if self._i >= len(self._script):
            # Script exhausted: a dry response so the agent loop terminates.
            return SearchResponse(
                total_matches=0, unjudged_matches=0, atom_counts=[], results=[]
            )
        entry = self._script[self._i]
        self._i += 1
        if isinstance(entry, EngineError):
            raise entry
        return _apply_exclude(entry, exclude)

    def read(self, id: str) -> str | None:
        return self._docs.get(id)


def _apply_exclude(resp: SearchResponse, exclude: set[str]) -> SearchResponse:
    """Mirror the engine's post-filter on a scripted batch: drop Hits whose id
    is excluded, decrement unjudged_matches by the number removed (total_matches is
    corpus-wide breadth and is unchanged), and re-rank the survivors 1..N."""
    if not exclude:
        return resp
    survivors = [h for h in resp.results if h.id not in exclude]
    removed = len(resp.results) - len(survivors)
    reranked = [h.model_copy(update={"rank": i}) for i, h in enumerate(survivors, 1)]
    return resp.model_copy(
        update={
            "results": reranked,
            "unjudged_matches": (resp.unjudged_matches - removed)
            if resp.unjudged_matches is not None else None,
        }
    )
