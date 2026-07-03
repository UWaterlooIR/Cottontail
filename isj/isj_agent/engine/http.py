"""HttpSearchEngine: the live HTTP client end of the cover_search contract (C1).

Implements B1's `SearchEngine` Protocol against a running `cottontail-jsonl-server`
(the C++ JSON server). The Searcher (B2) is transport-agnostic -- in tests it gets
the scripted `FakeEngine`; in live use it gets this, wired by C3. cp-native
(doc-6): `exclude` is a list of cp integers, results carry `cp`, `get_document`
takes a `cp`.

Every failure -- a non-2xx response (carrying the server's message) or an httpx
transport error (connection refused, timeout) -- is mapped to `EngineError`, so the
B2 controller can bounce it back to the model (a 400 from an invalid GCL query is
the common case the model self-corrects from).
"""

from collections.abc import Sequence

import httpx

from isj_agent.engine.base import EngineError
from isj_agent.protocol.search import SearchResponse


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
    """A SearchEngine backed by an HTTP cottontail-jsonl-server."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        # Tests inject either a ready `client` or a `transport` (e.g.
        # httpx.MockTransport) so the base_url + auth-header logic runs with no
        # network; otherwise build a default client bound to base_url.
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        exclude: Sequence[int] = (),
        window: int = 75,
    ) -> SearchResponse:
        body = {
            "query": query,
            "top_k": top_k,
            "exclude": list(exclude),
            "window": window,
        }
        try:
            r = self._client.post("/tools/cover_search", json=body)
        except httpx.HTTPError as exc:
            raise EngineError(f"cover_search transport error: {exc}") from exc
        if r.status_code != 200:
            raise EngineError(_server_error(r))
        return SearchResponse.model_validate(r.json())

    def tiered_search(
        self,
        tiers: Sequence[str],
        *,
        top_k: int = 10,
        exclude: Sequence[int] = (),
        window: int = 75,
    ) -> SearchResponse:
        body = {
            "tiers": list(tiers),
            "top_k": top_k,
            "exclude": list(exclude),
            "window": window,
        }
        try:
            r = self._client.post("/tools/tiered_query_search", json=body)
        except httpx.HTTPError as exc:
            raise EngineError(f"tiered_query_search transport error: {exc}") from exc
        if r.status_code != 200:
            raise EngineError(_server_error(r))
        return SearchResponse.model_validate(r.json())

    def read(self, cp: int) -> str | None:
        try:
            r = self._client.post("/tools/get_document", json={"cp": cp})
        except httpx.HTTPError as exc:
            raise EngineError(f"get_document transport error: {exc}") from exc
        if r.status_code != 200:
            raise EngineError(_server_error(r))
        d = r.json()
        return d["text"] if d.get("found") else None
