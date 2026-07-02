// cottontail-jsonl-server — an HTTP/JSON server exposing the search tools over
// the same jsonl_core actions and JSON contract as cottontail-jsonl-query. The
// burrow is opened once at startup and reused for every request. See
// docs/cottontail-search-server-spec.md.
//
// Endpoints: GET /healthz (public), GET /describe, POST /tools/<name>
//   for search_text | search_gcl | get_document | count_matches.
// Auth: a bearer token, optional on loopback, required on a non-loopback bind.

#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "httplib.h"

#include "apps/jsonl_core.h"
#include "apps/jsonl_json.h"
#include "src/cottontail.h"
#include "src/nlohmann.h"

namespace {
using cottontail::jsonl::CoverHit;
using cottontail::jsonl::CoverResponse;
using cottontail::jsonl::CoverSpec;
using cottontail::jsonl::Hit;
using cottontail::jsonl::QuerySpec;
using cottontail::jsonl::TieredSpec;

// A fixed pool of started read handles (the original Warren + its clones), built
// once at startup. with() hands one out for the duration of a query and returns
// it; the mutex is held only for the brief check-out/check-in, so queries run
// concurrently. When the pool is exhausted, callers block (backpressure). A
// Warren's text read path uses a stateful fstream, so each handle is a separate
// clone; the shared SimpleIdx is internally locked. clone() must be done at
// startup, single-threaded. See docs/cottontail-server-threadpool-spec.md.
class WarrenProvider {
public:
  explicit WarrenProvider(
      std::vector<std::shared_ptr<cottontail::Warren>> handles)
      : free_(std::move(handles)) {}

  template <class F> auto with(F &&fn) {
    std::shared_ptr<cottontail::Warren> w;
    {
      std::unique_lock<std::mutex> lock(mu_);
      cv_.wait(lock, [&] { return !free_.empty(); });
      w = free_.back();
      free_.pop_back();
    }
    // RAII: return the handle to the pool when fn returns or throws.
    struct Return {
      WarrenProvider *p;
      std::shared_ptr<cottontail::Warren> w;
      ~Return() {
        {
          std::lock_guard<std::mutex> lock(p->mu_);
          p->free_.push_back(w);
        }
        p->cv_.notify_one();
      }
    } ret{this, w};
    return fn(w); // query runs without holding mu_
  }

private:
  std::vector<std::shared_ptr<cottontail::Warren>> free_;
  std::mutex mu_;
  std::condition_variable cv_;
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

CoverSpec cover_spec_from(const json &b) {
  CoverSpec s;
  s.query = b.at("query").get<std::string>();
  s.top_k = b.value("top_k", s.top_k);
  s.window = b.value("window", s.window);
  s.max_covers = b.value("max_covers", s.max_covers);
  s.max_words = b.value("max_words", s.max_words);
  if (b.contains("exclude"))
    s.exclude = b.at("exclude").get<std::vector<cottontail::addr>>();
  return s;
}

TieredSpec tiered_spec_from(const json &b) {
  TieredSpec s;
  s.tiers = b.at("tiers").get<std::vector<std::string>>();
  s.top_k = b.value("top_k", s.top_k);
  s.window = b.value("window", s.window);
  s.max_covers = b.value("max_covers", s.max_covers);
  s.max_words = b.value("max_words", s.max_words);
  if (b.contains("exclude"))
    s.exclude = b.at("exclude").get<std::vector<cottontail::addr>>();
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

// Access log. Writers may run concurrently (one per worker thread), so serialize
// whole lines through one mutex to keep them from interleaving. To stderr, like
// the startup/exception logging. The Authorization header is never logged.
std::mutex log_mu;
void log_line(const std::string &line) {
  std::lock_guard<std::mutex> lock(log_mu);
  std::cerr << line << "\n";
}

void usage(const char *prog) {
  std::cerr << "usage: " << prog << " --burrow <path> [options]\n"
            << "  --host <addr>   default 127.0.0.1 (loopback)\n"
            << "  --port <n>      default 8080\n"
            << "  --threads <n>   concurrent query handlers (default 4)\n"
            << "  --token <t>     bearer token (prefer env COTTONTAIL_API_TOKEN)\n"
            << "  --no-auth       disable auth (loopback dev only)\n";
}
} // namespace

int main(int argc, char **argv) {
  std::string burrow, host = "127.0.0.1", flag_token;
  int port = 8080;
  int threads = 4;
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
    else if (a == "--threads")
      threads = std::stoi(next());
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
  // Fixed pool of read handles: the original + (threads-1) clones, built once at
  // startup, single-threaded (clone() auto-starts a started parent). Each clone
  // shares the idx cache but gets its own Txt fstream; see the threadpool spec.
  if (threads < 1)
    threads = 1;
  std::vector<std::shared_ptr<cottontail::Warren>> handles;
  handles.push_back(warren);
  for (int i = 1; i < threads; ++i) {
    auto clone = warren->clone(&error);
    if (clone == nullptr) {
      std::cerr << "failed to clone warren for the pool: " << error << "\n";
      return 2;
    }
    handles.push_back(clone);
  }
  WarrenProvider provider(std::move(handles));

  httplib::Server svr;
  // Match cpp-httplib's worker pool to the warren pool so they don't fight.
  svr.new_task_queue = [threads] { return new httplib::ThreadPool(threads); };

  svr.set_exception_handler(
      [](const httplib::Request &req, httplib::Response &res,
         std::exception_ptr ep) {
        // The client gets a generic 500, but log the real cause so internal
        // errors aren't opaque (recovering the message otherwise means a crash).
        std::string what = "unknown exception";
        try {
          if (ep)
            std::rethrow_exception(ep);
        } catch (const std::exception &e) {
          what = e.what();
        } catch (...) {
        }
        std::cerr << "internal error handling " << req.method << " " << req.path
                  << ": " << what << "\n";
        fail(res, 500, "internal error", "server");
      });

  // Response summary, logged after each request is handled.
  svr.set_logger([](const httplib::Request &req, const httplib::Response &res) {
    log_line("[res] " + req.method + " " + req.path + " -> " +
             std::to_string(res.status) + " (" +
             std::to_string(res.body.size()) + " bytes)");
  });
  // The request body (the query/params) is only readable once a route handler
  // runs -- the pre-routing handler fires before httplib reads the body -- so each
  // request is logged AT HANDLER ENTRY (via log_req below), before the work that
  // could crash the process. The pre-routing handler does auth only.
  auto log_req = [](const httplib::Request &req) {
    log_line("[req] " + req.method + " " + req.path +
             (req.body.empty() ? "" : " body=" + req.body));
  };
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

  svr.Get("/healthz", [&](const httplib::Request &req, httplib::Response &res) {
    log_req(req);
    json o;
    o["status"] = "ok";
    o["burrow"] = burrow;
    res.set_content(o.dump(), "application/json");
  });

  svr.Get("/describe", [&](const httplib::Request &req, httplib::Response &res) {
    log_req(req);
    res.set_content(cottontail::jsonl::describe_json().dump(),
                    "application/json");
  });

  auto search = [&](bool is_gcl) {
    return [&, is_gcl](const httplib::Request &req, httplib::Response &res) {
      log_req(req);
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

  svr.Post("/tools/cover_search",
           [&](const httplib::Request &req, httplib::Response &res) {
             log_req(req);
             json b;
             try {
               b = json::parse(req.body);
             } catch (...) {
               return fail(res, 400, "bad JSON body", "request");
             }
             CoverSpec spec;
             try {
               spec = cover_spec_from(b);
             } catch (...) {
               return fail(res, 400, "missing/invalid 'query'", "request");
             }
             CoverResponse resp;
             std::string e;
             bool ok = provider.with(
                 [&](std::shared_ptr<cottontail::Warren> &w) {
                   return cottontail::jsonl::jsonl_cover_search(w, spec, &resp,
                                                                &e);
                 });
             if (!ok)
               return fail(res, 400, e, "cover_search");
             res.set_content(cottontail::jsonl::cover_results_json(resp).dump(),
                             "application/json");
           });

  svr.Post("/tools/tiered_query_search",
           [&](const httplib::Request &req, httplib::Response &res) {
             log_req(req);
             json b;
             try {
               b = json::parse(req.body);
             } catch (...) {
               return fail(res, 400, "bad JSON body", "request");
             }
             TieredSpec spec;
             try {
               spec = tiered_spec_from(b);
             } catch (...) {
               return fail(res, 400, "missing/invalid 'tiers'", "request");
             }
             CoverResponse resp;
             std::string e;
             bool ok = provider.with(
                 [&](std::shared_ptr<cottontail::Warren> &w) {
                   return cottontail::jsonl::jsonl_tiered_query_search(w, spec,
                                                                      &resp, &e);
                 });
             if (!ok)
               return fail(res, 400, e, "tiered_query_search");
             // Reuse the cover_search response shape (identical CoverResponse).
             res.set_content(cottontail::jsonl::cover_results_json(resp).dump(),
                             "application/json");
           });

  svr.Post("/tools/get_document",
           [&](const httplib::Request &req, httplib::Response &res) {
             log_req(req);
             json b;
             try {
               b = json::parse(req.body);
             } catch (...) {
               return fail(res, 400, "bad JSON body", "request");
             }
             cottontail::addr cp;
             try {
               cp = b.at("cp").get<cottontail::addr>();
             } catch (...) {
               return fail(res, 400, "missing/invalid 'cp'", "request");
             }
             std::string body, e;
             bool found = false;
             bool ok = provider.with(
                 [&](std::shared_ptr<cottontail::Warren> &w) {
                   return cottontail::jsonl::jsonl_get(w, cp, &body, &found, &e);
                 });
             if (!ok)
               return fail(res, 400, e, "get");
             res.set_content(cottontail::jsonl::get_json(cp, found, body).dump(),
                             "application/json");
           });

  svr.Post("/tools/count_matches",
           [&](const httplib::Request &req, httplib::Response &res) {
             log_req(req);
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
            << " burrow=" << burrow << " threads=" << threads
            << (auth_required ? " (auth on)" : " (NO AUTH)") << "\n";
  if (!svr.listen(host, port)) {
    std::cerr << "bind failed on " << host << ":" << port << "\n";
    return 2;
  }
  return 0;
}
