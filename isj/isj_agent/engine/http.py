"""HttpSearchEngine: the live HTTP client end of the cover_search contract (C1).

Implements B1's `SearchEngine` Protocol against a running `cottontail-jsonl-server`
(the C++ JSON server). The Searcher (B2) is transport-agnostic -- in tests it gets
the scripted `FakeEngine`; in live use it gets this, wired by C3.

Docno on the wire (Option B): the agent speaks DOCNO strings, but the C++ server
speaks integer `cp`s. This engine is the sole cp<->docno boundary: it maps a hit's
`cp` -> docno on the way out, and a docno -> `cp` on the exclude list and on `read`,
using the burrow's read-only DocnoMap (memoized in-process so recurring docs and the
exclude translation are ~free). `cp` never leaves this engine. A docno-less burrow
(no map) degrades to the stringified cp as the id.

Every failure -- a non-2xx response (carrying the server's message) or an httpx
transport error (connection refused, timeout) -- is mapped to `EngineError`, so the
B2 controller can bounce it back to the model (a 400 from an invalid GCL query is
the common case the model self-corrects from).
"""

from collections.abc import Sequence

import httpx

from isj_agent.docno_map import DocnoMap
from isj_agent.engine.base import EngineError
from isj_agent.protocol.search import Hit, SearchResponse


def _server_error(r: httpx.Response) -> str:
    """The server's error message: its JSON `error` field if present, else the
    status + body."""
    try:
        body = r.json()
        if isinstance(body, dict) and "error" in body:
            return str(body["error"])
    except ValueError:
        pass
    return f"HTTP {r.status_code}: {r.text}"


class HttpSearchEngine:
    """A SearchEngine backed by an HTTP cottontail-jsonl-server.

    The default query timeout is ONE HOUR (TASK-29), deliberately: an httpx
    timeout is not a cancel — the server keeps computing an abandoned request,
    so a short timeout wastes the server's work, snowballs under retries (this
    wedged the 1M dev server for hours during the TASK-22 A/B), and the timeout
    bounce misleads the model into rewriting perfectly good queries. Slow
    queries should surface as slow turns in the trace, not as bounces.
    CONNECTION establishment still fails fast (10 s): a down server is down,
    not slow. Override via [cottontail_http_json_server].timeout_s.
    """

    DEFAULT_TIMEOUT_S: float = 3600.0
    CONNECT_TIMEOUT_S: float = 10.0

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        docno_map: DocnoMap | None = None,
    ):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        # Tests inject either a ready `client` or a `transport` (e.g.
        # httpx.MockTransport) so the base_url + auth-header logic runs with no
        # network; otherwise build a default client bound to base_url.
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=self.CONNECT_TIMEOUT_S),
            transport=transport,
        )
        self._map = docno_map
        self._docno_of: dict[int, str] = {}  # cp -> docno memo
        self._cp_of: dict[str, int] = {}     # docno -> cp memo

    # -- cp <-> docno translation (the only place cp is visible) -----------------

    def _docno(self, cp: int) -> str:
        """cp -> docno (memoized). Unmapped cp / docno-less burrow -> str(cp)."""
        d = self._docno_of.get(cp)
        if d is None:
            d = self._map.docno(cp) if self._map is not None else None
            if d is None:
                d = str(cp)
            self._docno_of[cp] = d
            self._cp_of.setdefault(d, cp)
        return d

    def _cp(self, docno: str) -> int | None:
        """docno -> cp (memoized). None if the docno is unknown to the map."""
        c = self._cp_of.get(docno)
        if c is None:
            c = self._map.cp(docno) if self._map is not None else None
            if c is None and self._map is None:
                # docno-less burrow: the id IS the stringified cp.
                try:
                    c = int(docno)
                except ValueError:
                    return None
            if c is not None:
                self._cp_of[docno] = c
                self._docno_of.setdefault(c, docno)
        return c

    def _exclude_cps(self, exclude: Sequence[str]) -> list[int]:
        """Translate the exclude docnos to cps for the server (drop any unknown)."""
        out = []
        for docno in exclude:
            c = self._cp(docno)
            if c is not None:
                out.append(c)
        return out

    def _hydrate(self, raw: dict) -> SearchResponse:
        """Build the agent-facing (docno-keyed) SearchResponse from the C++ server's
        cp-keyed JSON: map every hit's cp -> docno."""
        results = [
            Hit(
                rank=h["rank"],
                score=h["score"],
                id=self._docno(h["cp"]),
                summary=h["summary"],
            )
            for h in raw.get("results", [])
        ]
        return SearchResponse(results=results)

    def _post(self, path: str, body: dict, what: str) -> dict:
        try:
            r = self._client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise EngineError(f"{what} transport error: {exc}") from exc
        if r.status_code != 200:
            raise EngineError(_server_error(r))
        return r.json()

    # -- lifecycle ---------------------------------------------------------------

    def healthz(self) -> None:
        """Poll GET /healthz; raise EngineError (fail fast) if the server is not ready.

        The cottontail-jsonl-server reports {"burrow":..,"status":"ok"}. Used by the
        MultiShardSearchEngine to fail fast when a shard server is down (TASK-34)."""
        try:
            r = self._client.get("/healthz")
        except httpx.HTTPError as exc:
            raise EngineError(f"cottontail server unreachable at healthz: {exc}") from exc
        body = r.json() if r.status_code == 200 else None
        if not (isinstance(body, dict) and body.get("status") == "ok"):
            raise EngineError(f"cottontail server not healthy: {_server_error(r)}")

    # -- SearchEngine Protocol ---------------------------------------------------

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        exclude: Sequence[str] = (),
        window: int = 75,
    ) -> SearchResponse:
        body = {
            "query": query,
            "top_k": top_k,
            "exclude": self._exclude_cps(exclude),
            "window": window,
        }
        return self._hydrate(self._post("/tools/cover_search", body, "cover_search"))

    def tiered_search(
        self,
        tiers: Sequence[str],
        *,
        top_k: int = 10,
        exclude: Sequence[str] = (),
        window: int = 75,
    ) -> SearchResponse:
        body = {
            "tiers": list(tiers),
            "top_k": top_k,
            "exclude": self._exclude_cps(exclude),
            "window": window,
        }
        return self._hydrate(
            self._post("/tools/tiered_query_search", body, "tiered_query_search")
        )

    def multitext_search(
        self,
        program: str,
        *,
        top_k: int = 10,
        exclude: Sequence[str] = (),
        window: int = 75,
    ) -> SearchResponse:
        body = {
            "program": program,
            "top_k": top_k,
            "exclude": self._exclude_cps(exclude),
            "window": window,
        }
        return self._hydrate(
            self._post("/tools/multitext_tiered_search", body, "multitext_tiered_search")
        )

    def read(self, id: str) -> str | None:
        cp = self._cp(id)
        if cp is None:
            return None  # unknown docno
        d = self._post("/tools/get_document", {"cp": cp}, "get_document")
        return d["text"] if d.get("found") else None
