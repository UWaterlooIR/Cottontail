"""LucindriSearchEngine: the SearchEngine adapter over a Lucindri HTTP service (TASK-33).

Implements B1's `SearchEngine` Protocol against a running LucindriServer (Lucindri
TASK-0019: JDK HttpServer + Gson). Docno-native by construction -- Lucindri speaks
docnos, so this engine needs NO cp<->docno map (contrast the Cottontail HttpSearchEngine).

Wire contract (validated live 2026-07-10; see backlog TASK-33 WIRE CONTRACT):
  - POST /search {query, count, summaries} -> {results:[{docno, score, summary?}]}.
    count is required + positive, NO server cap; scores are NEGATIVE (Dirichlet LM).
    A malformed query -> 400 {error}; a degenerate/null parse -> 200 {results:[]}.
  - POST /document {docno} -> {docno, fulltext}; unknown docno -> 404 {error}.
  - GET /healthz -> 200 {ok:true} once the index is open.

Lucindri has NO server-side exclude and NO cursor, so paging/exclude is CLIENT-side:
each call re-requests count = |exclude| + top_k (deterministic ranking, so the top
|exclude|+top_k contain the next top_k unseen), drops the consumed docnos, keeps top_k.
The response is just the ranked results -- the uniform surface every engine presents.
"""

from collections.abc import Sequence

import httpx

from isj_agent.engine.base import EngineError
from isj_agent.protocol.search import Hit, SearchResponse


def _server_error(r: httpx.Response) -> str:
    try:
        body = r.json()
        if isinstance(body, dict) and "error" in body:
            return str(body["error"])
    except ValueError:
        pass
    return f"HTTP {r.status_code}: {r.text}"


class LucindriSearchEngine:
    """A SearchEngine backed by a Lucindri HTTP service (docno-native)."""

    DEFAULT_TIMEOUT_S: float = 3600.0
    CONNECT_TIMEOUT_S: float = 10.0

    def __init__(
        self,
        base_url: str,
        timeout: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=self.CONNECT_TIMEOUT_S),
            transport=transport,
        )

    # -- lifecycle ---------------------------------------------------------------

    def healthz(self) -> None:
        """Poll GET /healthz; raise EngineError (fail fast) if the server is not ready.

        Called on startup before the first search (Q6: operator-launched server)."""
        try:
            r = self._client.get("/healthz")
        except httpx.HTTPError as exc:
            raise EngineError(f"Lucindri server unreachable at healthz: {exc}") from exc
        if r.status_code != 200 or not (
            isinstance(r.json(), dict) and r.json().get("ok") is True
        ):
            raise EngineError(f"Lucindri server not healthy: {_server_error(r)}")

    # -- SearchEngine Protocol ---------------------------------------------------

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        exclude: Sequence[str] = (),
        window: int = 75,  # ignored: Lucindri summaries are startup-configured
    ) -> SearchResponse:
        excl = set(exclude)
        body = {"query": query, "count": len(excl) + top_k, "summaries": True}
        try:
            r = self._client.post("/search", json=body)
        except httpx.HTTPError as exc:
            raise EngineError(f"Lucindri /search transport error: {exc}") from exc
        # 400 = malformed query -> bounce to the model. A degenerate/null parse is a
        # 200 {results:[]}, a VALID empty result -- never treated as an error.
        if r.status_code != 200:
            raise EngineError(_server_error(r))
        raw = r.json().get("results", [])
        fresh = [h for h in raw if h["docno"] not in excl][:top_k]
        results = [
            Hit(
                rank=i,
                score=h["score"],
                id=h["docno"],
                summary=h.get("summary", ""),
            )
            for i, h in enumerate(fresh, 1)
        ]
        return SearchResponse(results=results)

    def read(self, id: str) -> str | None:
        try:
            r = self._client.post("/document", json={"docno": id})
        except httpx.HTTPError as exc:
            raise EngineError(f"Lucindri /document transport error: {exc}") from exc
        if r.status_code == 404:
            return None  # unknown docno
        if r.status_code != 200:
            raise EngineError(_server_error(r))
        return r.json().get("fulltext", "")

    # Lucindri has a single search endpoint; the tiered/multitext tools are
    # Cottontail-only and never reached for a LucindriQuery.
    def tiered_search(self, *a, **k) -> SearchResponse:
        raise NotImplementedError("LucindriSearchEngine has no tiered_search")

    def multitext_search(self, *a, **k) -> SearchResponse:
        raise NotImplementedError("LucindriSearchEngine has no multitext_search")
