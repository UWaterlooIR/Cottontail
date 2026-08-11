"""MultiShardSearchEngine: fan one query across N single-burrow Cottontail servers (TASK-34).

The corpus is PARTITIONED across N sub-burrows (each doc in exactly one shard), each served by
its own cottontail-jsonl-server. This engine runs the query on all N shards IN PARALLEL and
merges by score into the global top_k. It is exact because the cover-density / SSR ranker is
STATS-FREE (score = sum over covers of 1/(K + q-p), fixed K, no corpus IDF/df): a document's
score is the same on its shard as on the whole corpus, so cross-shard scores are directly
comparable and the top_k of the union is the TRUE global top_k. (GUARD: this holds only while
the ranker stays stats-free -- a BM25/IDF ranker would break cross-shard comparability.)

Docno on the wire (TASK-33): each shard engine (HttpSearchEngine) already returns globally
unique docnos (it owns its burrow's cp<->docno map), and the corpus is partitioned, so the
merge is docno-keyed and needs no cross-shard de-dup. This engine implements the SearchEngine
Protocol, so the controller / judger / run-output are unchanged.

FAIL-FAST (owner decision -- science, not a degraded-service deployment): if ANY shard errors,
the whole search raises EngineError; a partial (missing-shard) result is NEVER returned. A
malformed query fails every shard identically, so ONE of the duplicate parse errors is surfaced
(and bounced to the model).
"""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from isj_agent.engine.base import EngineError
from isj_agent.protocol.search import Hit, SearchResponse


class MultiShardSearchEngine:
    """A SearchEngine that fans a query across N shard engines and merges by score."""

    def __init__(self, shards: Sequence):
        if not shards:
            raise ValueError("MultiShardSearchEngine needs at least one shard engine")
        self._shards = list(shards)
        self._shard_of: dict[str, int] = {}  # docno -> shard index (read-routing memo)

    # -- lifecycle --------------------------------------------------------------

    def healthz(self) -> None:
        """Fail fast (EngineError) if ANY shard is down (Q2); checked on startup."""
        for i, shard in enumerate(self._shards):
            try:
                shard.healthz()
            except EngineError as exc:
                raise EngineError(f"shard {i} unhealthy: {exc}") from exc

    # -- fan-out + merge --------------------------------------------------------

    def _fan(self, method: str, *args, **kw) -> list[SearchResponse]:
        """Call shard.<method>(*args, **kw) on EVERY shard in parallel. Fail-fast: the first
        shard to raise propagates as EngineError -- never a partial result. (For a parse error
        every shard raises the same message; the first one is surfaced and bounced.)"""
        with ThreadPoolExecutor(max_workers=len(self._shards)) as pool:
            futures = [pool.submit(getattr(s, method), *args, **kw) for s in self._shards]
            responses = []
            for f in futures:
                try:
                    responses.append(f.result())
                except EngineError:
                    raise
                except Exception as exc:  # defensive: surface anything else as EngineError
                    raise EngineError(f"shard error in {method}: {exc}") from exc
        return responses

    def _merge(self, responses: list[SearchResponse], top_k: int) -> SearchResponse:
        hits: list[Hit] = []
        for i, resp in enumerate(responses):
            for h in resp.results:
                self._shard_of[h.id] = i  # remember the owning shard (read routing)
                hits.append(h)
        # higher cover-density score = better; stable sort keeps shard/rank order on ties.
        hits.sort(key=lambda h: h.score, reverse=True)
        merged = [h.model_copy(update={"rank": r}) for r, h in enumerate(hits[:top_k], 1)]
        return SearchResponse(results=merged)

    # -- SearchEngine Protocol --------------------------------------------------

    def search(self, query: str, *, top_k: int = 10,
               exclude: Sequence[str] = (), window: int = 75) -> SearchResponse:
        return self._merge(
            self._fan("search", query, top_k=top_k, exclude=exclude, window=window), top_k
        )

    def tiered_search(self, tiers: Sequence[str], *, top_k: int = 10,
                      exclude: Sequence[str] = (), window: int = 75) -> SearchResponse:
        return self._merge(
            self._fan("tiered_search", tiers, top_k=top_k, exclude=exclude, window=window), top_k
        )

    def multitext_search(self, program: str, *, top_k: int = 10,
                         exclude: Sequence[str] = (), window: int = 75) -> SearchResponse:
        return self._merge(
            self._fan("multitext_search", program, top_k=top_k, exclude=exclude, window=window), top_k
        )

    def read(self, id: str) -> str | None:
        i = self._shard_of.get(id)
        if i is not None:
            return self._shards[i].read(id)
        # Cold miss: the controller normally reads a just-surfaced docno (memo hit), so this
        # fallback is rare. Try shards in order until one owns the docno.
        for shard in self._shards:
            body = shard.read(id)
            if body is not None:
                return body
        return None
