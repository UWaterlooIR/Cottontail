# Specification: `cottontail-jsonl-server` — an HTTP/JSON search server

**Audience:** an implementing agent with full access to this repository.
**Goal:** a long-lived HTTP server that exposes the Cottontail search tools (the
same actions as `cottontail-jsonl-query`) over HTTP/JSON, so an LLM ReAct agent
(or any client) can drive them **without re-opening the burrow per query**.

This builds directly on `docs/cottontail-search-agent-spec.md` (the tool action
set and JSON contract) and `docs/cottontail-jsonl-cli-spec.md` (the CLI). The
server is a **thin HTTP layer over `apps/jsonl_core.{h,cc}`**, exactly as the CLIs
are thin argv layers — so its behavior and wire format are identical to the CLI by
construction.

## 0. Why a server (the one fixed point)

Open the burrow **once** at startup, hold the `started` `Warren` in memory, and
answer many requests against it. That removes the per-query cost the CLI pays on
every invocation (reloading the `.idx` dictionary, cold posting/LRU cache). Every
decision below serves that and the "identical contract" guarantee.

## 1. Scope and non-goals

In scope (v1):
- One burrow per process, opened **read-only** at startup (`open_burrow`).
- HTTP/1.1 + JSON via **`cpp-httplib`** (header-only).
- The five tool actions + a tool schema + a health check (§3).
- Bind to **loopback by default**; **optional bearer-token auth** that becomes
  **mandatory when binding a non-loopback interface** (§4).
- **Single-threaded query execution now**, structured so a **clone-per-thread
  pool** is a localized change later (§5).

Non-goals (v1):
- **In-binary TLS.** The server speaks plain HTTP. Encryption (and additional
  authentication) for remote access is handled at the **deployment layer** — an
  SSH tunnel or a TLS-terminating reverse proxy — not compiled into the binary
  (§4). In-binary TLS via `cpp-httplib` + OpenSSL stays a documented last resort.
- Multiple burrows, write/append, token scopes/roles, rate limiting, metrics.
- Replacing the CLI — both coexist over the same `jsonl_core`.

> **Security posture in one line:** loopback needs no auth; for remote access
> tunnel/proxy in (SSH gives encryption + auth for free, no certs); a bearer
> token is cheap defense-in-depth and is *required* if you bind a public
> interface, but a raw public bind without TLS upstream sends the token in clear
> — don't. See §4.

## 2. The contract is shared with the CLI (factor it out)

The CLI's JSON (de)serialization currently lives in
`apps/cottontail-jsonl-query.cc`'s anonymous namespace (`results_json`,
`hit_json`, `explain_json`, `get_json`, `count_json`, `describe_json`). To keep
the server and CLI **byte-for-byte identical** on the wire, **move these into a
shared unit** — e.g. `apps/jsonl_json.{h,cc}` — and have both the query CLI and
the server include it. Do this refactor first; it should be behavior-preserving
(the CLI tests in `test/jsonl_cli.cc` must still pass).

```cpp
// apps/jsonl_json.h  (sketch)
namespace cottontail { namespace jsonl {
json results_json(const QuerySpec &, const std::vector<Hit> &, double elapsed_ms);
json explain_json(const QuerySpec &, const ExplainResult &);
json get_json(const std::string &docid, bool found, const std::string &text);
json count_json(const QuerySpec &, long match_count);
json describe_json();   // the OpenAI/Anthropic tool schema (array)
}}  // namespace cottontail::jsonl
```

## 3. HTTP endpoints

The server mirrors the tool API 1:1, so the agent maps a tool call straight to a
URL. All bodies and responses are JSON; `Content-Type: application/json`.

| Method & path | Auth | Body (request) | Response |
|---|---|---|---|
| `GET /healthz` | **no** | — | `{"status":"ok","burrow":"<path>"}` |
| `GET /describe` | yes | — | the tool schema array (`describe_json()`) |
| `POST /tools/search_text` | yes | `{"query", "top_k"?, "stem"?, "full_text"?, "ranker"?, "snippet_chars"?}` | search results (`results_json`) |
| `POST /tools/search_gcl` | yes | `{"query", "top_k"?, "stem"?, "full_text"?, "snippet_chars"?}` | search results |
| `POST /tools/cover_search` | yes | `{"query", "top_k"?, "exclude"? : [cp,…], "window"?, "max_covers"?}` | cover results (`cover_results_json`): `{"total_matches","unjudged_matches","atom_counts":[{term,count}],"results":[{rank,score,cp,summary}]}` |
| `POST /tools/explain` | yes | `{"query", "is_gcl"?, "stem"?}` | explain (`explain_json`) |
| `POST /tools/get_document` | yes | `{"docid"}` | `{"docid","found","text"}` |
| `POST /tools/count_matches` | yes | `{"query", "is_gcl"?, "stem"?}` | `{"query","query_mode","stemmed","match_count"}` |

Notes:
- `search_text` sets `QuerySpec.is_gcl=false`; `search_gcl` sets it `true`. Both
  call `jsonl_query` and return `results_json` (which already includes
  `result_count` and `truncated`).
- Field names match the `--describe` schema exactly (`query`, not `q`) so the
  request body **is** the tool-call arguments object.
- `cover_search` (the ISJ agent's tool, distinct from `search_gcl`) calls
  `jsonl_cover_search` and returns `cover_results_json`. Its query may use the
  `word*` family marker (per-term stemming via the burrow's Porter; see
  `docs/stemming.md §6a`). It requires a `--stem porter` burrow; a `word*` query
  against a non-stemmed burrow, a non-trailing `*`, or malformed GCL → `400` with
  an `{error, where}` body. The response is EXACTLY `total_matches`,
  `unjudged_matches`, `atom_counts`, `results` — no `result_count`/`truncated`/
  `query` (the Python client mirror is strict). `total_matches`/`unjudged_matches`
  are document counts computed as a byproduct of the single ssr ranking pass
  (`unjudged = total − excluded-cps-that-match`); `atom_counts` is per query leaf
  `{term, count}` (occurrences, term as written, no `stream`); `exclude` is a list
  of judged **cps** dropped by a direct **cp post-filter** on the ranked results
  (over-fetch `top_k + |exclude|`), `window` sizes the summary. `max_covers`
  (default `1`) selects how many of the **best (tightest) covers** the summary is
  built from — `1` gives a single focused snippet; higher values include more
  covers (windowed/merged/`" . . . "`-joined as before). The server is
  stateless and cp-only: `exclude` is per-request and never opens a `:docno`/map.
- Unknown tool name under `/tools/...` → `404`.

### Request → QuerySpec mapping

```cpp
QuerySpec spec_from(const json &b, bool is_gcl) {
  QuerySpec s;
  s.is_gcl = is_gcl;
  s.query = b.at("query").get<std::string>();
  s.top_k = b.value("top_k", s.top_k);
  s.stem = b.value("stem", s.stem);
  s.full_text = b.value("full_text", s.full_text);
  s.ranker = b.value("ranker", s.ranker);
  s.snippet_chars = b.value("snippet_chars", s.snippet_chars);
  return s;
}
```

## 4. Authentication & exposure

Auth and network exposure are coupled: **loopback needs no auth; a public bind
needs auth *and* encryption.** The server encodes that and leaves encryption to
the deployment layer.

**When auth applies.** A single **bearer token**, checked on every route except
`GET /healthz`. It is **optional on loopback** (the default `--host 127.0.0.1`
needs no auth — the boundary there is simply not binding a public interface) and
**mandatory on any non-loopback `--host`**:
- `--host` is a loopback address (`127.0.0.1`/`::1`) and no token configured →
  start with **auth off** (fine for local use).
- `--host` is loopback **and** a token is configured → enforce it (cheap
  defense-in-depth).
- `--host` is **non-loopback** and no token configured → **refuse to start**
  (fail safe); require `--no-auth` to override (don't).
- `--host` is non-loopback → also print a prominent warning that the token and
  all traffic cross the network **in clear** unless TLS is terminated upstream;
  point at the deployment options below.

**Token handling (independent of TLS — these are the real local-snoop fixes).**
- Read the token from an **environment variable** (`COTTONTAIL_API_TOKEN`); accept
  `--token <value>` only as a fallback. Prefer env: argv is world-readable via
  `/proc/<pid>/cmdline` (`ps`), whereas `/proc/<pid>/environ` is owner/root-only.
  The **client (agent) must do the same** — env, never a flag (§10).
- **Never log the `Authorization` header** (or request headers generally).
- Compare with a **constant-time** comparison (below) to avoid leaking the token
  via timing; on missing/malformed/wrong → `401`
  `{"error":"unauthorized","where":"auth"}`.

**Exposure / encryption (deployment layer, not the binary).** To reach the server
from other hosts, in order of preference:
1. **SSH tunnel** (recommended): keep the server loopback-only and
   `ssh -L 8080:127.0.0.1:8080 <host>` from the client. SSH supplies encryption
   **and** authentication via existing keys — no certs, no server auth, nothing
   added to the binary.
2. **TLS-terminating reverse proxy** (e.g. caddy, which auto-provisions certs;
   or nginx): server stays loopback + plain HTTP behind it; the proxy does TLS
   (and can do auth).
3. **In-binary TLS** (`cpp-httplib` + OpenSSL) only as a last resort — it adds an
   OpenSSL build dependency and certificate management (generate a cert+key; the
   client must trust/pin it). See §11.

```cpp
// constant-time compare (avoid leaking length/contents via timing)
bool ct_equal(const std::string &a, const std::string &b) {
  if (a.size() != b.size()) return false;
  unsigned char v = 0;
  for (size_t i = 0; i < a.size(); ++i) v |= (unsigned char)(a[i] ^ b[i]);
  return v == 0;
}

// httplib pre-routing handler: one place, runs before every route.
svr.set_pre_routing_handler(
    [&](const httplib::Request &req, httplib::Response &res) {
      if (req.path == "/healthz")
        return httplib::Server::HandlerResponse::Unhandled; // public
      if (!auth_required) // auth off: loopback with no token (or --no-auth); §4
        return httplib::Server::HandlerResponse::Unhandled;
      auto h = req.get_header_value("Authorization");
      const std::string prefix = "Bearer ";
      if (h.rfind(prefix, 0) == 0 && ct_equal(h.substr(prefix.size()), token))
        return httplib::Server::HandlerResponse::Unhandled; // ok, continue
      res.status = 401;
      res.set_content(R"({"error":"unauthorized","where":"auth"})",
                      "application/json");
      return httplib::Server::HandlerResponse::Handled;
    });
```

## 5. Concurrency (single-threaded now, pool-ready)

**Important:** `cpp-httplib` dispatches each request on a worker thread from an
internal pool, so handlers can run concurrently — but a `Warren`'s read path is
**not** shared-thread-safe (the codebase rule is "clone per thread"). v1 therefore
runs **one query at a time** by serializing access to the single shared `Warren`
behind a mutex. Route every handler through one accessor so the evolution to a
clone-per-thread pool is a single localized change:

```cpp
// v1: one shared started Warren, serialized. Later: a pool of cloned Warrens,
// one borrowed per request, with no global lock.
class WarrenProvider {
public:
  explicit WarrenProvider(std::shared_ptr<Warren> w) : warren_(std::move(w)) {}
  template <class F> auto with(F &&fn) {
    std::lock_guard<std::mutex> g(mu_);     // v1 serialization point
    return fn(warren_);
  }
private:
  std::shared_ptr<Warren> warren_;
  std::mutex mu_;
};
```

Handlers call `provider.with([&](auto &warren){ return jsonl_query(warren, ...); })`.
To add a pool later: `WarrenProvider` keeps N `warren->clone()` handles and hands
one out per call (e.g. via a blocking queue) instead of locking — handler code is
unchanged. (Optionally cap `cpp-httplib`'s pool, but the mutex is the correctness
guarantee regardless of pool size.)

## 6. Implementation sketch

`apps/cottontail-jsonl-server.cc` (new). `main`:

```cpp
int main(int argc, char **argv) {
  // args: --burrow <path> (required), --host (def 127.0.0.1), --port (def 8080),
  //       token from env COTTONTAIL_API_TOKEN (or --token fallback), --no-auth.
  // Compute auth_required per §4: required for a non-loopback --host (refuse to
  // start without a token unless --no-auth); optional/off on loopback.
  std::string error;
  auto warren = cottontail::jsonl::open_burrow(burrow, &error);
  if (warren == nullptr) { std::cerr << error << "\n"; return 2; }
  WarrenProvider provider(warren);

  httplib::Server svr;
  svr.set_pre_routing_handler(/* §4 auth */);

  svr.Get("/healthz", [&](const httplib::Request &, httplib::Response &res) {
    json o; o["status"] = "ok"; o["burrow"] = burrow;
    res.set_content(o.dump(), "application/json");
  });
  svr.Get("/describe", [&](const httplib::Request &, httplib::Response &res) {
    res.set_content(cottontail::jsonl::describe_json().dump(), "application/json");
  });

  auto search = [&](bool is_gcl) {
    return [&, is_gcl](const httplib::Request &req, httplib::Response &res) {
      json b;
      try { b = json::parse(req.body); }
      catch (...) { return fail(res, 400, "bad JSON body", "request"); }
      QuerySpec spec;
      try { spec = spec_from(b, is_gcl); }
      catch (...) { return fail(res, 400, "missing/invalid 'query'", "request"); }
      std::vector<cottontail::jsonl::Hit> hits;
      std::string e;
      auto t0 = cottontail::now();
      bool ok = provider.with([&](auto &w) {
        return cottontail::jsonl::jsonl_query(w, spec, &hits, &e);
      });
      if (!ok) return fail(res, 400, e, "query"); // e.g. malformed gcl
      res.set_content(
          cottontail::jsonl::results_json(spec, hits, cottontail::now() - t0).dump(),
          "application/json");
    };
  };
  svr.Post("/tools/search_text", search(false));
  svr.Post("/tools/search_gcl", search(true));
  // /tools/explain, /tools/get_document, /tools/count_matches: analogous,
  // calling jsonl_explain / jsonl_get / jsonl_count via provider.with(...).

  std::cerr << "listening on " << host << ":" << port << " burrow=" << burrow
            << (auth_required ? " (auth on)\n" : " (NO AUTH)\n");
  if (!svr.listen(host, port)) { std::cerr << "bind failed\n"; return 2; }
}
```

`fail` is a small helper: `res.status = code; res.set_content({"error":msg,
"where":phase}.dump(), "application/json");`.

## 7. Error & status mapping

- `200` — success (including empty results / `found:false`; these are not errors).
- `400` — bad JSON body, missing required field, malformed `--gcl` (a `jsonl_*`
  hard failure that reflects bad input, including `--stem` against a burrow with
  no stemmed stream).
- `401` — auth failure.
- `404` — unknown path / unknown tool under `/tools/`.
- `405` — wrong method.
- `500` — unexpected internal error (I/O, exceptions escaping a handler; wrap
  handlers so they never crash the server).

Body is **always** JSON; errors use the existing `{"error","where"}` shape.

## 8. Build (Bazel)

Add `cpp-httplib` and a `cc_binary`:

```python
# MODULE.bazel — prefer the Bazel Central Registry module if present:
bazel_dep(name = "cpp-httplib", version = "<check BCR for current>")
# Fallback if not on BCR: vendor the single header via http_archive /
# new_local_repository and expose it as a cc_library.
```

```python
# apps/BUILD
cc_binary(
    name = "cottontail-jsonl-server",
    srcs = ["cottontail-jsonl-server.cc"],
    deps = [":jsonl_core", ":jsonl_json", "//src:cottontail", "@cpp-httplib//:httplib"],
    linkopts = ["-lz", "-pthread"],
)
```

Verify the exact BCR module/target names when wiring it; `cpp-httplib` needs
pthreads (already linked).

## 9. Tests

A C++ end-to-end test `test/jsonl_server.cc` (mirror `test/jsonl_cli.cc`'s style),
in its own `cc_test` target, that:
- builds a tiny burrow from `test/jsonl/plain` (via `jsonl_index`),
- starts the server on an **ephemeral port** in a background thread (with a known
  token), waits for `/healthz`,
- uses `httplib::Client` to assert:
  1. `/healthz` works **without** a token; every `/tools/*` returns `401` without
     the token and `200` with it.
  2. `POST /tools/search_text {"query":"elephants"}` returns a `results` array
     whose top `docid` is `doc-004`; `result_count`/`truncated` present.
  3. `POST /tools/get_document {"docid":"doc-004"}` → `found:true`, body text
     contains the expected content; an unknown docid → `found:false`, `200`.
  4. `POST /tools/count_matches {"query":"quick fox"}` → `match_count:2`.
  5. `POST /tools/search_gcl {"query":"(^ quick"}` (malformed) → `400` with an
     `{"error","where"}` body.
  6. `GET /describe` (authed) parses as a JSON array containing the five tool
     names.
- stops the server (`svr.stop()`), joins the thread.

Keep `bazel test //test:tests //test:hazel_test //test:jsonl_test
//test:jsonl_server` green; the refactor in §2 must leave the existing CLI tests
passing.

## 10. Python agent integration (follow-on, small)

`examples/agent/search_agent.py` currently shells out to the binary in
`SearchTools.call`. Add an HTTP mode (`--server-url http://127.0.0.1:8080`) where
`call(name, args)` does `POST {server-url}/tools/{name}` with `json=args` and an
`Authorization: Bearer` header, and `schema()` does `GET /describe`. Because the
contract is identical, results parse exactly as today — it's a transport swap, not
a logic change. Keep the subprocess mode as the default/fallback.

Read the token from the **environment** (`COTTONTAIL_API_TOKEN`), **not** a CLI
flag — same reasoning as the server (§4): a `--server-token` flag would expose the
secret in the agent's `/proc/<pid>/cmdline`. Send it only over loopback or a
tunnel/TLS path, never to a raw public HTTP endpoint.

## 11. Future (out of scope, design accommodates)

- **Clone-per-thread pool** (§5) for real concurrency.
- **Encryption for remote access** — prefer an SSH tunnel or a TLS-terminating
  reverse proxy (§4); **in-binary TLS** via `cpp-httplib` + OpenSSL (define
  `CPPHTTPLIB_OPENSSL_SUPPORT`, use `SSLServer(cert,key)`, add the OpenSSL dep and
  a cert+key the client trusts) only if neither is available.
- **Token scopes / multiple tokens**, rate limiting, structured access logs.
- **Multiple burrows** (path or vhost routing) behind one server.
- An **MCP adapter** that maps `tools/list`→`/describe` and
  `tools/call`→`/tools/<name>`, proxying to this server.
