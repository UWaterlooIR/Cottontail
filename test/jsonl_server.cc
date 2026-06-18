// End-to-end test for cottontail-jsonl-server (docs/cottontail-search-server-spec.md
// §9): starts the built server binary on a free loopback port with a token, then
// drives it with an httplib::Client and asserts auth, the tool endpoints, and the
// error/contract behavior. Mirrors test/jsonl_cli.cc's "run the real binary" style.

#include <atomic>
#include <csignal>
#include <cstdlib>
#include <string>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

#include "httplib.h"

#include "gtest/gtest.h"

#include "src/nlohmann.h"

namespace {
const char *kIndexBin = "apps/cottontail-jsonl-index";
const char *kServerBin = "apps/cottontail-jsonl-server";
const char *kToken = "test-secret-token";

std::string tmpdir() {
  const char *t = std::getenv("TEST_TMPDIR");
  return t != nullptr ? std::string(t) : std::string("/tmp");
}

// Grab a free loopback TCP port (close it and hand the number to the server).
int free_port() {
  int s = ::socket(AF_INET, SOCK_STREAM, 0);
  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  addr.sin_port = 0;
  ::bind(s, reinterpret_cast<sockaddr *>(&addr), sizeof(addr));
  socklen_t len = sizeof(addr);
  ::getsockname(s, reinterpret_cast<sockaddr *>(&addr), &len);
  int port = ntohs(addr.sin_port);
  ::close(s);
  return port;
}

pid_t start_server(const std::string &burrow, int port) {
  pid_t pid = ::fork();
  if (pid == 0) {
    std::string ports = std::to_string(port);
    ::execl(kServerBin, kServerBin, "--burrow", burrow.c_str(), "--host",
            "127.0.0.1", "--port", ports.c_str(), "--threads", "4", "--token",
            kToken, static_cast<char *>(nullptr));
    _exit(127); // exec failed
  }
  return pid;
}
} // namespace

TEST(JsonlServer, EndToEnd) {
  // Build a small burrow from the committed fixture.
  std::string burrow = tmpdir() + "/server.burrow";
  std::string build = std::string(kIndexBin) + " --input test/jsonl/plain --burrow " +
                      burrow + " --overwrite >/dev/null 2>&1";
  ASSERT_EQ(std::system(build.c_str()), 0);

  int port = free_port();
  pid_t pid = start_server(burrow, port);
  ASSERT_GT(pid, 0);

  httplib::Client cli("127.0.0.1", port);
  cli.set_connection_timeout(2, 0);

  // Wait for the server to come up (poll /healthz).
  bool up = false;
  for (int i = 0; i < 100 && !up; ++i) {
    if (auto r = cli.Get("/healthz"); r && r->status == 200)
      up = true;
    else
      ::usleep(50 * 1000);
  }
  ASSERT_TRUE(up) << "server did not start";

  const httplib::Headers auth = {{"Authorization", std::string("Bearer ") + kToken}};

  // /healthz is public.
  {
    auto r = cli.Get("/healthz");
    ASSERT_TRUE(r);
    EXPECT_EQ(r->status, 200);
  }
  // Tool endpoints require the token.
  {
    auto r = cli.Post("/tools/search_text", R"({"query":"elephants"})",
                      "application/json");
    ASSERT_TRUE(r);
    EXPECT_EQ(r->status, 401);
  }
  // search_text with the token -> ranked results.
  {
    auto r = cli.Post("/tools/search_text", auth, R"({"query":"elephants"})",
                      "application/json");
    ASSERT_TRUE(r);
    ASSERT_EQ(r->status, 200) << r->body;
    json j = json::parse(r->body);
    ASSERT_FALSE(j["results"].empty());
    EXPECT_EQ(j["results"][0]["docid"], "doc-004");
    EXPECT_TRUE(j.contains("result_count"));
    EXPECT_TRUE(j.contains("truncated"));
  }
  // get_document round-trips; unknown docid is found:false (still 200).
  {
    auto r = cli.Post("/tools/get_document", auth, R"({"docid":"doc-004"})",
                      "application/json");
    ASSERT_TRUE(r);
    ASSERT_EQ(r->status, 200) << r->body;
    json j = json::parse(r->body);
    EXPECT_EQ(j["found"], true);
    EXPECT_NE(j["text"].get<std::string>().find("elephants"), std::string::npos);

    auto r2 = cli.Post("/tools/get_document", auth, R"({"docid":"nope"})",
                       "application/json");
    ASSERT_TRUE(r2);
    EXPECT_EQ(r2->status, 200);
    EXPECT_EQ(json::parse(r2->body)["found"], false);
  }
  // count_matches: AND of the terms.
  {
    auto r = cli.Post("/tools/count_matches", auth, R"({"query":"quick fox"})",
                      "application/json");
    ASSERT_TRUE(r);
    ASSERT_EQ(r->status, 200) << r->body;
    EXPECT_EQ(json::parse(r->body)["match_count"], 2);
  }
  // Malformed GCL -> 400 with an {error,where} body.
  {
    auto r = cli.Post("/tools/search_gcl", auth, R"({"query":"(^ quick"})",
                      "application/json");
    ASSERT_TRUE(r);
    EXPECT_EQ(r->status, 400);
    EXPECT_TRUE(json::parse(r->body).contains("error"));
  }
  // /describe returns the five tools.
  {
    auto r = cli.Get("/describe", auth);
    ASSERT_TRUE(r);
    ASSERT_EQ(r->status, 200) << r->body;
    json j = json::parse(r->body);
    ASSERT_TRUE(j.is_array());
    std::set<std::string> names;
    for (const auto &t : j)
      names.insert(t["function"]["name"].get<std::string>());
    EXPECT_EQ(names.count("search_text"), 1u);
    EXPECT_EQ(names.count("get_document"), 1u);
    EXPECT_EQ(names.count("count_matches"), 1u);
    EXPECT_EQ(names.count("cover_search"), 1u); // A1 tool advertised
    // cover_search advertises its A2 request fields (AC#15).
    for (const auto &t : j)
      if (t["function"]["name"] == "cover_search") {
        const auto &props = t["function"]["parameters"]["properties"];
        EXPECT_TRUE(props.contains("query"));
        EXPECT_TRUE(props.contains("top_k"));
        EXPECT_TRUE(props.contains("exclude_docids"));
        EXPECT_TRUE(props.contains("window"));
      }
  }

  ::kill(pid, SIGTERM);
  int status = 0;
  ::waitpid(pid, &status, 0);
}

// cover_search over a stemmed burrow: a word* query round-trips and returns
// {rank,score,docid,summary}; a malformed cover query is a 400.
TEST(JsonlServer, CoverSearch) {
  std::string burrow = tmpdir() + "/server_cover.burrow";
  std::string build = std::string(kIndexBin) +
                      " --input test/jsonl/plain --burrow " + burrow +
                      " --stem porter --overwrite >/dev/null 2>&1";
  ASSERT_EQ(std::system(build.c_str()), 0);

  int port = free_port();
  pid_t pid = start_server(burrow, port);
  ASSERT_GT(pid, 0);

  httplib::Client cli("127.0.0.1", port);
  cli.set_connection_timeout(2, 0);
  bool up = false;
  for (int i = 0; i < 100 && !up; ++i) {
    if (auto r = cli.Get("/healthz"); r && r->status == 200)
      up = true;
    else
      ::usleep(50 * 1000);
  }
  ASSERT_TRUE(up) << "server did not start";
  const httplib::Headers auth = {
      {"Authorization", std::string("Bearer ") + kToken}};

  // run* reaches doc-002 ("runs") via the word* family marker; the A2 fields are
  // present and there are NO legacy fields (B1's SearchResponse is extra=forbid).
  {
    auto r = cli.Post("/tools/cover_search", auth, R"({"query":"run*"})",
                      "application/json");
    ASSERT_TRUE(r);
    ASSERT_EQ(r->status, 200) << r->body;
    json j = json::parse(r->body);
    EXPECT_EQ(j["total_matches"], 1);
    EXPECT_EQ(j["unjudged_matches"], 1);
    ASSERT_TRUE(j.contains("atom_counts"));
    for (const auto &a : j["atom_counts"]) {
      EXPECT_TRUE(a.contains("term"));
      EXPECT_TRUE(a.contains("count"));
      EXPECT_FALSE(a.contains("stream")); // no stream field (A2 AC#3)
    }
    // exactly the four response keys -- no result_count/truncated/stemmed/query.
    EXPECT_EQ(j.size(), 4u) << r->body;
    EXPECT_FALSE(j.contains("result_count"));
    EXPECT_FALSE(j.contains("truncated"));
    EXPECT_FALSE(j.contains("stemmed"));
    bool found = false;
    for (const auto &res : j["results"]) {
      EXPECT_TRUE(res.contains("rank"));
      EXPECT_TRUE(res.contains("score"));
      EXPECT_TRUE(res.contains("summary"));
      if (res["docid"] == "doc-002")
        found = true;
    }
    EXPECT_TRUE(found) << r->body;
  }
  // exclude_docids carves doc-002 (the only run* match): unjudged 0, results
  // empty, total unchanged.
  {
    auto r = cli.Post("/tools/cover_search", auth,
                      R"({"query":"run*","exclude_docids":["doc-002"]})",
                      "application/json");
    ASSERT_TRUE(r);
    ASSERT_EQ(r->status, 200) << r->body;
    json j = json::parse(r->body);
    EXPECT_EQ(j["total_matches"], 1);
    EXPECT_EQ(j["unjudged_matches"], 0);
    EXPECT_TRUE(j["results"].empty()) << r->body;
  }
  // Statelessness: a follow-up request with no exclusion sees doc-002 again
  // (the prior exclude_docids did not persist).
  {
    auto r = cli.Post("/tools/cover_search", auth, R"({"query":"run*"})",
                      "application/json");
    ASSERT_TRUE(r);
    ASSERT_EQ(r->status, 200) << r->body;
    json j = json::parse(r->body);
    EXPECT_EQ(j["unjudged_matches"], 1);
    EXPECT_FALSE(j["results"].empty());
  }
  // A non-trailing '*' is a 400 with an error body.
  {
    auto r = cli.Post("/tools/cover_search", auth, R"({"query":"ru*n"})",
                      "application/json");
    ASSERT_TRUE(r);
    EXPECT_EQ(r->status, 400) << r->body;
    EXPECT_TRUE(json::parse(r->body).contains("error"));
  }

  ::kill(pid, SIGTERM);
  int status = 0;
  ::waitpid(pid, &status, 0);
}

// Many concurrent requests against the clone-per-thread pool must all return
// correct results and not deadlock (the server is started with --threads 4).
TEST(JsonlServer, ConcurrentRequests) {
  std::string burrow = tmpdir() + "/server_concurrent.burrow";
  std::string build = std::string(kIndexBin) +
                      " --input test/jsonl/plain --burrow " + burrow +
                      " --overwrite >/dev/null 2>&1";
  ASSERT_EQ(std::system(build.c_str()), 0);

  int port = free_port();
  pid_t pid = start_server(burrow, port);
  ASSERT_GT(pid, 0);

  { // wait for the server to come up
    httplib::Client cli("127.0.0.1", port);
    cli.set_connection_timeout(2, 0);
    bool up = false;
    for (int i = 0; i < 100 && !up; ++i) {
      if (auto r = cli.Get("/healthz"); r && r->status == 200)
        up = true;
      else
        ::usleep(50 * 1000);
    }
    ASSERT_TRUE(up) << "server did not start";
  }

  const httplib::Headers auth = {
      {"Authorization", std::string("Bearer ") + kToken}};
  const int kClients = 8, kIters = 25; // 8 threads x 25 x 3 calls = 600 requests
  std::atomic<int> failures{0};
  std::vector<std::thread> workers;
  for (int t = 0; t < kClients; ++t) {
    workers.emplace_back([&]() {
      httplib::Client cli("127.0.0.1", port); // per-thread (Client isn't shared)
      cli.set_connection_timeout(5, 0);
      for (int i = 0; i < kIters; ++i) {
        try {
          auto s = cli.Post("/tools/search_text", auth,
                            R"({"query":"elephants"})", "application/json");
          json js;
          if (!s || s->status != 200 || (js = json::parse(s->body))["results"].empty() ||
              js["results"][0]["docid"] != "doc-004") {
            failures++;
            continue;
          }
          auto c = cli.Post("/tools/count_matches", auth,
                            R"({"query":"quick fox"})", "application/json");
          if (!c || c->status != 200 || json::parse(c->body)["match_count"] != 2) {
            failures++;
            continue;
          }
          auto g = cli.Post("/tools/get_document", auth, R"({"docid":"doc-004"})",
                            "application/json");
          if (!g || g->status != 200 || json::parse(g->body)["found"] != true)
            failures++;
        } catch (...) {
          failures++;
        }
      }
    });
  }
  for (auto &w : workers)
    w.join();
  EXPECT_EQ(failures.load(), 0);

  ::kill(pid, SIGTERM);
  int status = 0;
  ::waitpid(pid, &status, 0);
}
