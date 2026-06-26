// Process-boundary regression tests for the JSONL CLIs (spec §11.6): exit codes,
// the stderr error object, stdout JSON framing, and --batch. Runs the built
// binaries (declared as data deps) via popen. This is the only committable way
// to cover the CLI surface, since .sh/.py harnesses are gitignored.

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <set>
#include <string>
#include <vector>

#include <sys/wait.h>

#include "gtest/gtest.h"

#include "src/nlohmann.h"

namespace {
const char *kIndexBin = "apps/cottontail-jsonl-index";
const char *kQueryBin = "apps/cottontail-jsonl-query";

std::string tmpdir() {
  const char *t = std::getenv("TEST_TMPDIR");
  return t != nullptr ? std::string(t) : std::string("/tmp");
}

// Run a shell command, capture combined stdout+stderr, and the exit code.
std::string run(const std::string &cmd, int *code) {
  FILE *p = popen((cmd + " 2>&1").c_str(), "r");
  std::string out;
  if (p == nullptr) {
    *code = -1;
    return out;
  }
  char buf[8192];
  size_t n;
  while ((n = fread(buf, 1, sizeof(buf), p)) > 0)
    out.append(buf, n);
  int st = pclose(p);
  *code = WIFEXITED(st) ? WEXITSTATUS(st) : -1;
  return out;
}

std::string build_burrow(const std::string &name) {
  std::string b = tmpdir() + "/" + name + ".burrow";
  int code;
  run(std::string(kIndexBin) + " --input test/jsonl/plain --burrow " + b +
          " --overwrite",
      &code);
  return b;
}

std::vector<std::string> lines(const std::string &s) {
  std::vector<std::string> out;
  std::string::size_type p = 0, nl;
  while ((nl = s.find('\n', p)) != std::string::npos) {
    if (nl > p)
      out.push_back(s.substr(p, nl - p));
    p = nl + 1;
  }
  if (p < s.size())
    out.push_back(s.substr(p));
  return out;
}
} // namespace

TEST(JsonlCli, IndexSummaryToStdout) {
  std::string b = tmpdir() + "/cli_idx.burrow";
  int code;
  std::string out = run(std::string(kIndexBin) +
                            " --input test/jsonl/plain --burrow " + b +
                            " --overwrite",
                        &code);
  ASSERT_EQ(code, 0) << out;
  json j = json::parse(out);
  EXPECT_EQ(j["rows_indexed"], 4);
  EXPECT_EQ(j["rows_skipped"], 0);
}

TEST(JsonlCli, QueryEmitsCp) {
  std::string b = build_burrow("cli_q");
  int code;
  std::string out = run(std::string(kQueryBin) + " --burrow " + b +
                            " --text elephants --format jsonl",
                        &code);
  ASSERT_EQ(code, 0) << out;
  json j = json::parse(out);
  ASSERT_TRUE(j.contains("results"));
  ASSERT_FALSE(j["results"].empty());
  // cp-native: each hit carries an integer cp; it round-trips through --get to
  // doc-004's body.
  long cp = j["results"][0]["cp"].get<long>();
  std::string g = run(std::string(kQueryBin) + " --burrow " + b + " --get " +
                          std::to_string(cp) + " --format jsonl",
                      &code);
  ASSERT_EQ(code, 0) << g;
  json jg = json::parse(g);
  EXPECT_EQ(jg["found"], true);
  EXPECT_EQ(jg["cp"].get<long>(), cp);
  EXPECT_NE(jg["text"].get<std::string>().find("middle east"), std::string::npos);
}

TEST(JsonlCli, UsageErrorExit1) {
  int code;
  run(std::string(kQueryBin), &code); // no mode/burrow
  EXPECT_EQ(code, 1);
}

TEST(JsonlCli, RuntimeErrorExit2WithErrorObject) {
  int code;
  std::string out = run(
      std::string(kQueryBin) + " --burrow /no/such/burrow --text x", &code);
  ASSERT_EQ(code, 2) << out;
  json j = json::parse(out);
  EXPECT_TRUE(j.contains("error"));
  EXPECT_EQ(j["where"], "open");
}

TEST(JsonlCli, StemBuildAndQuery) {
  std::string b = tmpdir() + "/cli_stem.burrow";
  int code;
  std::string idx = run(std::string(kIndexBin) +
                            " --input test/jsonl/plain --burrow " + b +
                            " --stem porter --overwrite",
                        &code);
  ASSERT_EQ(code, 0) << idx;
  EXPECT_EQ(json::parse(idx)["stemmer"], "porter");

  // --stem "run" matches doc-002 ("runs"); the plain index would not.
  std::string out = run(std::string(kQueryBin) + " --burrow " + b +
                            " --text run --stem --format jsonl",
                        &code);
  ASSERT_EQ(code, 0) << out;
  json j = json::parse(out);
  EXPECT_EQ(j["stemmed"], true);
  ASSERT_FALSE(j["results"].empty()) << out;
  // The match round-trips via --get to doc-002's body ("runs").
  long cp = j["results"][0]["cp"].get<long>();
  std::string g = run(std::string(kQueryBin) + " --burrow " + b + " --get " +
                          std::to_string(cp) + " --format jsonl",
                      &code);
  ASSERT_EQ(code, 0) << g;
  EXPECT_NE(json::parse(g)["text"].get<std::string>().find("runs"),
            std::string::npos)
      << g;
}

TEST(JsonlCli, StemAgainstPlainBurrowExits2) {
  std::string b = build_burrow("cli_stem_missing"); // built without --stem
  int code;
  std::string out = run(std::string(kQueryBin) + " --burrow " + b +
                            " --text elephant --stem",
                        &code);
  ASSERT_EQ(code, 2) << out;
  json j = json::parse(out);
  EXPECT_TRUE(j.contains("error"));
}

TEST(JsonlCli, CoverSearchWordStar) {
  std::string b = tmpdir() + "/cli_cover.burrow";
  int code;
  std::string idx = run(std::string(kIndexBin) +
                            " --input test/jsonl/plain --burrow " + b +
                            " --stem porter --overwrite",
                        &code);
  ASSERT_EQ(code, 0) << idx;
  // --cover "run*" reaches doc-002 ("runs") via the word* family marker.
  std::string out = run(std::string(kQueryBin) + " --burrow " + b +
                            " --cover \"run*\" --format jsonl",
                        &code);
  ASSERT_EQ(code, 0) << out;
  json j = json::parse(out);
  ASSERT_FALSE(j["results"].empty()) << out;
  for (const auto &r : j["results"])
    EXPECT_TRUE(r.contains("summary")); // cover-biased summary, not best_passage
  // The match carries its cp; it resolves to doc-002's body ("runs").
  long cp = j["results"][0]["cp"].get<long>();
  std::string g = run(std::string(kQueryBin) + " --burrow " + b + " --get " +
                          std::to_string(cp) + " --format jsonl",
                      &code);
  ASSERT_EQ(code, 0) << g;
  EXPECT_NE(json::parse(g)["text"].get<std::string>().find("runs"),
            std::string::npos);
}

TEST(JsonlCli, CoverMidTokenStarExits2) {
  std::string b = tmpdir() + "/cli_cover_badstar.burrow";
  int code;
  run(std::string(kIndexBin) + " --input test/jsonl/plain --burrow " + b +
          " --stem porter --overwrite",
      &code);
  std::string out = run(std::string(kQueryBin) + " --burrow " + b +
                            " --cover \"ru*n\"",
                        &code);
  ASSERT_EQ(code, 2) << out;
  EXPECT_TRUE(json::parse(out).contains("error"));
}

TEST(JsonlCli, CoverWordStarPlainBurrowExits2) {
  std::string b = build_burrow("cli_cover_plain"); // built without --stem
  int code;
  std::string out = run(std::string(kQueryBin) + " --burrow " + b +
                            " --cover \"run*\"",
                        &code);
  ASSERT_EQ(code, 2) << out;
  EXPECT_TRUE(json::parse(out).contains("error"));
}

TEST(JsonlCli, CoverWindowAndExcludeFlags) {
  std::string b = tmpdir() + "/cli_cover_a2.burrow";
  int code;
  run(std::string(kIndexBin) + " --input test/jsonl/plain --burrow " + b +
          " --stem porter --overwrite",
      &code);
  // --window runs and returns the matching doc with the A2 response fields.
  std::string out = run(std::string(kQueryBin) + " --burrow " + b +
                            " --cover \"run*\" --window 50 --format jsonl",
                        &code);
  ASSERT_EQ(code, 0) << out;
  json j = json::parse(out);
  EXPECT_TRUE(j.contains("total_matches"));
  EXPECT_TRUE(j.contains("atom_counts"));
  ASSERT_FALSE(j["results"].empty()) << out;
  long cp = j["results"][0]["cp"].get<long>();

  // --exclude <cp> carves doc-002 (the only run* match): unjudged 0, results
  // empty, total unchanged.
  out = run(std::string(kQueryBin) + " --burrow " + b + " --cover \"run*\" --exclude " +
                std::to_string(cp) + " --format jsonl",
            &code);
  ASSERT_EQ(code, 0) << out;
  j = json::parse(out);
  EXPECT_EQ(j["total_matches"], 1);
  EXPECT_EQ(j["unjudged_matches"], 0);
  EXPECT_TRUE(j["results"].empty()) << out;
}

TEST(JsonlCli, GetByCp) {
  std::string b = build_burrow("cli_get");
  int code;
  // Get a cp from a search, then fetch by cp.
  std::string s = run(std::string(kQueryBin) + " --burrow " + b +
                          " --text elephants --format jsonl",
                      &code);
  ASSERT_EQ(code, 0) << s;
  long cp = json::parse(s)["results"][0]["cp"].get<long>();
  std::string out = run(std::string(kQueryBin) + " --burrow " + b + " --get " +
                            std::to_string(cp) + " --format jsonl",
                        &code);
  ASSERT_EQ(code, 0) << out;
  json j = json::parse(out);
  EXPECT_EQ(j["found"], true);
  EXPECT_EQ(j["cp"].get<long>(), cp);
  EXPECT_NE(j["text"].get<std::string>().find("elephants"), std::string::npos);
}

TEST(JsonlCli, CountMatches) {
  std::string b = build_burrow("cli_count");
  int code;
  std::string out = run(std::string(kQueryBin) + " --burrow " + b +
                            " --count --text \"quick fox\" --format jsonl",
                        &code);
  ASSERT_EQ(code, 0) << out;
  json j = json::parse(out);
  EXPECT_EQ(j["match_count"], 2);
}

TEST(JsonlCli, ResultCountAndTruncated) {
  std::string b = build_burrow("cli_trunc");
  int code;
  std::string out = run(std::string(kQueryBin) + " --burrow " + b +
                            " --text fox --top-k 1 --format jsonl",
                        &code);
  ASSERT_EQ(code, 0) << out;
  json j = json::parse(out);
  EXPECT_EQ(j["result_count"], 1);
  EXPECT_EQ(j["truncated"], true); // fox matches 2 docs, asked for 1
}

TEST(JsonlCli, DescribeEmitsToolSchema) {
  int code;
  std::string out = run(std::string(kQueryBin) + " --describe", &code);
  ASSERT_EQ(code, 0) << out;
  json j = json::parse(out);
  ASSERT_TRUE(j.is_array());
  std::set<std::string> names;
  for (const auto &t : j) {
    EXPECT_EQ(t["type"], "function");
    names.insert(t["function"]["name"].get<std::string>());
  }
  EXPECT_EQ(names.count("search_text"), 1u);
  EXPECT_EQ(names.count("search_gcl"), 1u);
  EXPECT_EQ(names.count("explain"), 1u);
  EXPECT_EQ(names.count("get_document"), 1u);
  EXPECT_EQ(names.count("count_matches"), 1u);
}

TEST(JsonlCli, BatchPreservesOrderAndIsolatesErrors) {
  std::string b = build_burrow("cli_batch");
  std::string in = tmpdir() + "/batch_in.txt";
  {
    std::ofstream f(in);
    f << "{\"q\":\"elephants\"}\n";
    f << "{\"q\":\"(^ quick\",\"is_gcl\":true}\n"; // malformed gcl
  }
  int code;
  std::string out = run(
      std::string(kQueryBin) + " --burrow " + b + " --batch < " + in, &code);
  ASSERT_EQ(code, 0) << out;
  std::vector<std::string> ls = lines(out);
  ASSERT_EQ(ls.size(), 2u) << out;
  json l0 = json::parse(ls[0]);
  json l1 = json::parse(ls[1]);
  EXPECT_EQ(l0["input_index"], 0);
  EXPECT_TRUE(l0.contains("results"));
  EXPECT_EQ(l1["input_index"], 1);
  EXPECT_TRUE(l1.contains("error")); // bad gcl isolated, batch not aborted
}
