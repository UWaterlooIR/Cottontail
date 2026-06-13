// cottontail-jsonl-server — an HTTP/JSON server exposing the search tools over
// the same jsonl_core actions and JSON contract as cottontail-jsonl-query. The
// burrow is opened once at startup and reused for every request. See
// docs/cottontail-search-server-spec.md.
//
// Endpoints: GET /healthz (public), GET /describe, POST /tools/<name>
//   for search_text | search_gcl | explain | get_document | count_matches.
// Auth: a bearer token, optional on loopback, required on a non-loopback bind.

#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#include "httplib.h"

#include "apps/jsonl_core.h"
#include "apps/jsonl_json.h"
#include "src/cottontail.h"
#include "src/nlohmann.h"

namespace {
using cottontail::jsonl::ExplainResult;
using cottontail::jsonl::Hit;
using cottontail::jsonl::QuerySpec;

// v1: one shared started Warren, serialized by a mutex (a Warren's read path is
// not shared-thread-safe, and cpp-httplib dispatches requests on a thread pool).
// To add real concurrency later, hand out a cloned Warren per call from a pool
// instead of locking — handlers are unchanged. See spec §5.
class WarrenProvider {
public:
  explicit WarrenProvider(std::shared_ptr<cottontail::Warren> w)
      : warren_(std::move(w)) {}
  template <class F> auto with(F &&fn) {
    std::lock_guard<std::mutex> g(mu_);
    return fn(warren_);
  }

private:
  std::shared_ptr<cottontail::Warren> warren_;
  std::mutex mu_;
};

// Constant-time string compare (avoid leaking the token via timing).
bool ct_equal(const std::string &a, const std::string &b) {
  if (a.size() != b.size())
    return false;
  unsigned char v = 0;
  for (size_t i = 0; i < a.size(); ++i)
    v |= static_cast<unsigned char>(a[i] ^ b[i]);
  return v == 0;
}

bool is_loopback(const std::string &host) {
  return host == "127.0.0.1" || host == "::1" || host == "localhost";
}

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

void fail(httplib::Response &res, int code, const std::string &msg,
          const std::string &where) {
  json e;
  e["error"] = msg;
  e["where"] = where;
  res.status = code;
  res.set_content(e.dump(), "application/json");
}

void usage(const char *prog) {
  std::cerr << "usage: " << prog << " --burrow <path> [options]\n"
            << "  --host <addr>   default 127.0.0.1 (loopback)\n"
            << "  --port <n>      default 8080\n"
            << "  --token <t>     bearer token (prefer env COTTONTAIL_API_TOKEN)\n"
            << "  --no-auth       disable auth (loopback dev only)\n";
}
} // namespace

int main(int argc, char **argv) {
  std::string burrow, host = "127.0.0.1", flag_token;
  int port = 8080;
  bool no_auth = false;

  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    auto next = [&]() -> std::string {
      if (i + 1 >= argc) {
        usage(argv[0]);
        std::exit(1);
      }
      return argv[++i];
    };
    if (a == "--burrow")
      burrow = next();
    else if (a == "--host")
      host = next();
    else if (a == "--port")
      port = std::stoi(next());
    else if (a == "--token")
      flag_token = next();
    else if (a == "--no-auth")
      no_auth = true;
    else if (a == "--help") {
      usage(argv[0]);
      return 0;
    } else {
      std::cerr << "unknown argument: " << a << "\n";
      usage(argv[0]);
      return 1;
    }
  }
  if (burrow.empty()) {
    usage(argv[0]);
    return 1;
  }

  // Token from env (preferred), falling back to --token.
  std::string token;
  if (const char *t = std::getenv("COTTONTAIL_API_TOKEN"))
    token = t;
  if (token.empty())
    token = flag_token;

  // Auth/exposure coupling (spec §4): loopback may run without auth; a
  // non-loopback bind requires a token (fail safe) unless --no-auth is forced.
  bool loopback = is_loopback(host);
  bool auth_required;
  if (no_auth) {
    auth_required = false;
  } else if (!token.empty()) {
    auth_required = true;
  } else if (loopback) {
    auth_required = false; // localhost, no token: fine
  } else {
    std::cerr << "refusing to bind non-loopback host '" << host
              << "' without a token: set COTTONTAIL_API_TOKEN (or --token), or "
                 "pass --no-auth to override.\n";
    return 2;
  }
  if (!loopback)
    std::cerr << "WARNING: binding non-loopback host '" << host
              << "' over plain HTTP — token and traffic cross the network in "
                 "clear. Front with an SSH tunnel or TLS proxy (spec §4).\n";

  std::string error;
  auto warren = cottontail::jsonl::open_burrow(burrow, &error);
  if (warren == nullptr) {
    std::cerr << "could not open burrow: " << error << "\n";
    return 2;
  }
  WarrenProvider provider(warren);

  httplib::Server svr;

  svr.set_exception_handler(
      [](const httplib::Request &, httplib::Response &res, std::exception_ptr) {
        fail(res, 500, "internal error", "server");
      });

  // Auth: runs before every route except the public health check.
  svr.set_pre_routing_handler(
      [&](const httplib::Request &req, httplib::Response &res) {
        if (req.path == "/healthz" || !auth_required)
          return httplib::Server::HandlerResponse::Unhandled;
        const std::string prefix = "Bearer ";
        std::string h = req.get_header_value("Authorization");
        if (h.rfind(prefix, 0) == 0 &&
            ct_equal(h.substr(prefix.size()), token))
          return httplib::Server::HandlerResponse::Unhandled;
        fail(res, 401, "unauthorized", "auth");
        return httplib::Server::HandlerResponse::Handled;
      });

  svr.Get("/healthz", [&](const httplib::Request &, httplib::Response &res) {
    json o;
    o["status"] = "ok";
    o["burrow"] = burrow;
    res.set_content(o.dump(), "application/json");
  });

  svr.Get("/describe", [&](const httplib::Request &, httplib::Response &res) {
    res.set_content(cottontail::jsonl::describe_json().dump(),
                    "application/json");
  });

  auto search = [&](bool is_gcl) {
    return [&, is_gcl](const httplib::Request &req, httplib::Response &res) {
      json b;
      try {
        b = json::parse(req.body);
      } catch (...) {
        return fail(res, 400, "bad JSON body", "request");
      }
      QuerySpec spec;
      try {
        spec = spec_from(b, is_gcl);
      } catch (...) {
        return fail(res, 400, "missing/invalid 'query'", "request");
      }
      std::vector<Hit> hits;
      std::string e;
      cottontail::addr t0 = cottontail::now();
      bool ok = provider.with([&](std::shared_ptr<cottontail::Warren> &w) {
        return cottontail::jsonl::jsonl_query(w, spec, &hits, &e);
      });
      if (!ok)
        return fail(res, 400, e, "query");
      res.set_content(
          cottontail::jsonl::results_json(spec, hits, cottontail::now() - t0)
              .dump(),
          "application/json");
    };
  };
  svr.Post("/tools/search_text", search(false));
  svr.Post("/tools/search_gcl", search(true));

  svr.Post("/tools/explain",
           [&](const httplib::Request &req, httplib::Response &res) {
             json b;
             try {
               b = json::parse(req.body);
             } catch (...) {
               return fail(res, 400, "bad JSON body", "request");
             }
             QuerySpec spec;
             try {
               spec = spec_from(b, b.value("is_gcl", false));
             } catch (...) {
               return fail(res, 400, "missing/invalid 'query'", "request");
             }
             ExplainResult ex = provider.with(
                 [&](std::shared_ptr<cottontail::Warren> &w) {
                   return cottontail::jsonl::jsonl_explain(w, spec);
                 });
             res.set_content(cottontail::jsonl::explain_json(spec, ex).dump(),
                             "application/json");
           });

  svr.Post("/tools/get_document",
           [&](const httplib::Request &req, httplib::Response &res) {
             json b;
             try {
               b = json::parse(req.body);
             } catch (...) {
               return fail(res, 400, "bad JSON body", "request");
             }
             std::string docid;
             try {
               docid = b.at("docid").get<std::string>();
             } catch (...) {
               return fail(res, 400, "missing/invalid 'docid'", "request");
             }
             std::string body, e;
             bool found = false;
             bool ok = provider.with(
                 [&](std::shared_ptr<cottontail::Warren> &w) {
                   return cottontail::jsonl::jsonl_get(w, docid, &body, &found,
                                                       &e);
                 });
             if (!ok)
               return fail(res, 400, e, "get");
             res.set_content(cottontail::jsonl::get_json(docid, found, body).dump(),
                             "application/json");
           });

  svr.Post("/tools/count_matches",
           [&](const httplib::Request &req, httplib::Response &res) {
             json b;
             try {
               b = json::parse(req.body);
             } catch (...) {
               return fail(res, 400, "bad JSON body", "request");
             }
             QuerySpec spec;
             try {
               spec = spec_from(b, b.value("is_gcl", false));
             } catch (...) {
               return fail(res, 400, "missing/invalid 'query'", "request");
             }
             long n = 0;
             std::string e;
             bool ok = provider.with(
                 [&](std::shared_ptr<cottontail::Warren> &w) {
                   return cottontail::jsonl::jsonl_count(w, spec, &n, &e);
                 });
             if (!ok)
               return fail(res, 400, e, "count");
             res.set_content(cottontail::jsonl::count_json(spec, n).dump(),
                             "application/json");
           });

  std::cerr << "cottontail-jsonl-server listening on " << host << ":" << port
            << " burrow=" << burrow
            << (auth_required ? " (auth on)" : " (NO AUTH)") << "\n";
  if (!svr.listen(host, port)) {
    std::cerr << "bind failed on " << host << ":" << port << "\n";
    return 2;
  }
  return 0;
}
