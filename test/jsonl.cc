// Regression tests for the cottontail-jsonl-index / -query CLIs, exercised at
// the library level (apps/jsonl_core.h). See docs/cottontail-jsonl-cli-spec.md
// §11. CLI process-boundary behavior (exit codes, batch) is covered separately
// by test/jsonl_cli.cc.

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <set>
#include <string>
#include <vector>

#include "gtest/gtest.h"

#include "apps/jsonl_core.h"

namespace {
using namespace cottontail::jsonl;

std::string tmp_burrow(const std::string &name) {
  const char *t = std::getenv("TEST_TMPDIR");
  std::string base = (t != nullptr ? std::string(t) : std::string("/tmp"));
  return base + "/" + name + ".burrow";
}

bool build(const std::string &input, const std::string &burrow,
           IndexSummary *summary, std::string *error, bool strict = false) {
  IndexOptions opts;
  opts.input = input;
  opts.burrow = burrow;
  opts.overwrite = true;
  opts.strict = strict;
  return jsonl_index(opts, summary, error);
}

std::set<std::string> docids(const std::vector<Hit> &hits) {
  std::set<std::string> s;
  for (const auto &h : hits)
    s.insert(h.docid);
  return s;
}

cottontail::addr df_of(const ExplainResult &ex, const std::string &term) {
  for (const auto &l : ex.leaves)
    if (l.term == term)
      return l.df;
  return -1;
}

const ExplainLeaf *leaf_of(const ExplainResult &ex, const std::string &term) {
  for (const auto &l : ex.leaves)
    if (l.term == term)
      return &l;
  return nullptr;
}

// Write rows (one JSON object per line) into a fresh input dir and index it,
// optionally with a stemmer. Keeps the stemming fixtures inline (no committed
// fixture files needed).
bool build_rows(const std::string &name, const std::vector<std::string> &rows,
                const std::string &stemmer, std::string *burrow,
                std::string *error) {
  const char *t = std::getenv("TEST_TMPDIR");
  std::string base = (t != nullptr ? std::string(t) : std::string("/tmp"));
  std::string dir = base + "/" + name + "_src";
  std::error_code ec;
  std::filesystem::create_directories(dir, ec);
  {
    std::ofstream f(dir + "/sample.jsonl");
    for (const auto &r : rows)
      f << r << "\n";
  }
  IndexOptions opts;
  opts.input = dir;
  opts.burrow = tmp_burrow(name);
  opts.overwrite = true;
  opts.stemmer = stemmer;
  *burrow = opts.burrow;
  IndexSummary s;
  return jsonl_index(opts, &s, error);
}

const std::vector<std::string> kStemRows = {
    R"({"docid":"s-1","contents":"the elephants jumped over running foxes"})",
    R"({"docid":"s-2","contents":"organization of organs"})",
    R"({"docid":"s-3","contents":"an ox and a cat"})",
};

std::set<std::string> cover_docids(const std::vector<CoverHit> &hits) {
  std::set<std::string> s;
  for (const auto &h : hits)
    s.insert(h.docid);
  return s;
}

// Fixtures for cover_search (TASK-5.1 / A1). Lowercase so case folding is not a
// variable. c-1/c-4 have "bear"; c-2 has only "bears"; c-3 has "ox"; c-5 has the
// adjacent phrase "black bears".
const std::vector<std::string> kCoverRows = {
    R"({"docid":"c-1","contents":"black bear attacks on hikers are rare in the forest"})",
    R"({"docid":"c-2","contents":"the bears attacked a camp near the river"})",
    R"({"docid":"c-3","contents":"an ox pulled the cart along the trail"})",
    R"({"docid":"c-4","contents":"grizzly bear encounters differ from black bear behavior"})",
    R"({"docid":"c-5","contents":"black bears roam the quiet woods"})",
};
} // namespace

TEST(JsonlIndex, BuildCounts) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("plain1"), &s, &error))
      << error;
  EXPECT_EQ(s.rows_indexed, 4u);
  EXPECT_EQ(s.rows_skipped, 0u);
  EXPECT_EQ(s.files_seen, 1u);
  EXPECT_GT(s.burrow_bytes, 0u);
  auto w = open_burrow(tmp_burrow("plain1"), &error);
  ASSERT_NE(w, nullptr) << error;
  w->end();
}

TEST(JsonlIndex, SkipNonStrict) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/bad", tmp_burrow("bad1"), &s, &error)) << error;
  EXPECT_EQ(s.rows_indexed, 2u); // m-1, m-3
  EXPECT_EQ(s.rows_skipped, 2u); // non-JSON line, missing-contents line
}

TEST(JsonlIndex, StrictIsFatal) {
  std::string error;
  IndexSummary s;
  EXPECT_FALSE(build("test/jsonl/bad", tmp_burrow("bad2"), &s, &error, true));
}

TEST(JsonlQuery, RetrievalAndDocid) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("q1"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("q1"), &error);
  ASSERT_NE(w, nullptr) << error;
  QuerySpec spec;
  spec.query = "elephants";
  std::vector<Hit> hits;
  ASSERT_TRUE(jsonl_query(w, spec, &hits, &error)) << error;
  ASSERT_FALSE(hits.empty());
  EXPECT_EQ(hits[0].docid, "doc-004");
  w->end();
}

TEST(JsonlQuery, FieldProjection) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("q2"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("q2"), &error);
  ASSERT_NE(w, nullptr) << error;
  // "zzqueryonly" appears only in the ignored "id" field -> no hits.
  QuerySpec only_in_id;
  only_in_id.query = "zzqueryonly";
  std::vector<Hit> hits;
  ASSERT_TRUE(jsonl_query(w, only_in_id, &hits, &error)) << error;
  EXPECT_TRUE(hits.empty());
  // "fox" is in contents of doc-001 and doc-002.
  QuerySpec fox;
  fox.query = "fox";
  ASSERT_TRUE(jsonl_query(w, fox, &hits, &error)) << error;
  std::set<std::string> ids = docids(hits);
  EXPECT_EQ(ids.count("doc-001"), 1u);
  EXPECT_EQ(ids.count("doc-002"), 1u);
  w->end();
}

TEST(JsonlQuery, GclContainment) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("q3"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("q3"), &error);
  ASSERT_NE(w, nullptr) << error;
  QuerySpec spec;
  spec.is_gcl = true;
  spec.query = "(^ quick fox)"; // both terms -> doc-001, doc-002
  std::vector<Hit> hits;
  ASSERT_TRUE(jsonl_query(w, spec, &hits, &error)) << error;
  std::set<std::string> ids = docids(hits);
  EXPECT_EQ(ids.size(), 2u);
  EXPECT_EQ(ids.count("doc-001"), 1u);
  EXPECT_EQ(ids.count("doc-002"), 1u);
  w->end();
}

TEST(JsonlQuery, GclParseErrorIsReported) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("q4"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("q4"), &error);
  ASSERT_NE(w, nullptr) << error;
  QuerySpec spec;
  spec.is_gcl = true;
  spec.query = "(^ quick"; // unbalanced
  std::vector<Hit> hits;
  std::string qerr;
  EXPECT_FALSE(jsonl_query(w, spec, &hits, &qerr));
  w->end();
}

TEST(JsonlQuery, GzipEqualsPlain) {
  std::string error;
  IndexSummary sp, sg;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("gp"), &sp, &error)) << error;
  ASSERT_TRUE(build("test/jsonl/gz", tmp_burrow("gg"), &sg, &error)) << error;
  EXPECT_EQ(sp.rows_indexed, sg.rows_indexed);
  auto wp = open_burrow(tmp_burrow("gp"), &error);
  auto wg = open_burrow(tmp_burrow("gg"), &error);
  ASSERT_NE(wp, nullptr);
  ASSERT_NE(wg, nullptr);
  QuerySpec spec;
  spec.query = "fox";
  std::vector<Hit> hp, hg;
  ASSERT_TRUE(jsonl_query(wp, spec, &hp, &error)) << error;
  ASSERT_TRUE(jsonl_query(wg, spec, &hg, &error)) << error;
  EXPECT_EQ(docids(hp), docids(hg));
  wp->end();
  wg->end();
}

TEST(JsonlQuery, EmptyResultsAreOk) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("q5"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("q5"), &error);
  ASSERT_NE(w, nullptr) << error;
  QuerySpec spec;
  spec.query = "zxqwvunlikelyterm";
  std::vector<Hit> hits;
  EXPECT_TRUE(jsonl_query(w, spec, &hits, &error)); // success, not error
  EXPECT_TRUE(hits.empty());
  w->end();
}

TEST(JsonlQuery, FullText) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("q6"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("q6"), &error);
  ASSERT_NE(w, nullptr) << error;
  QuerySpec spec;
  spec.query = "elephants";
  spec.full_text = true;
  std::vector<Hit> hits;
  ASSERT_TRUE(jsonl_query(w, spec, &hits, &error)) << error;
  ASSERT_FALSE(hits.empty());
  EXPECT_TRUE(hits[0].has_full_text);
  EXPECT_NE(hits[0].full_text.find("middle east"), std::string::npos);
  w->end();
}

TEST(JsonlExplain, TextDocumentFrequencies) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("e1"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("e1"), &error);
  ASSERT_NE(w, nullptr) << error;
  QuerySpec spec;
  spec.query = "quick fox";
  ExplainResult ex = jsonl_explain(w, spec);
  EXPECT_TRUE(ex.parsed_ok);
  EXPECT_EQ(df_of(ex, "quick"), 2); // doc-001, doc-002
  EXPECT_EQ(df_of(ex, "fox"), 2);   // doc-001, doc-002
  w->end();
}

TEST(JsonlExplain, GclParse) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("e2"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("e2"), &error);
  ASSERT_NE(w, nullptr) << error;
  QuerySpec good;
  good.is_gcl = true;
  good.query = "(^ quick fox)";
  EXPECT_TRUE(jsonl_explain(w, good).parsed_ok);
  QuerySpec bad;
  bad.is_gcl = true;
  bad.query = "(^ quick";
  EXPECT_FALSE(jsonl_explain(w, bad).parsed_ok);
  w->end();
}

// --- Stemming (docs/stemming.md) ------------------------------------------

TEST(JsonlStem, StemmedRecallExactDoesNot) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("stem_recall", kStemRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<Hit> hits;

  // Exact "elephant" does not match the body "elephants".
  QuerySpec exact;
  exact.query = "elephant";
  ASSERT_TRUE(jsonl_query(w, exact, &hits, &error)) << error;
  EXPECT_TRUE(hits.empty());

  // --stem "elephant" matches s-1 (which contains only "elephants").
  QuerySpec stem;
  stem.query = "elephant";
  stem.stem = true;
  ASSERT_TRUE(jsonl_query(w, stem, &hits, &error)) << error;
  EXPECT_EQ(docids(hits).count("s-1"), 1u);
  w->end();
}

TEST(JsonlStem, ExactStreamPreservedInStemIndex) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("stem_exact", kStemRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<Hit> hits;
  // The exact surface form is still retrievable from a stemmed index.
  QuerySpec spec;
  spec.query = "elephants";
  ASSERT_TRUE(jsonl_query(w, spec, &hits, &error)) << error;
  EXPECT_EQ(docids(hits).count("s-1"), 1u);
  w->end();
}

TEST(JsonlStem, NoOpTermFallsBackToExact) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("stem_noop", kStemRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  // "ox" is too short for Porter to stem; --stem still finds it via the exact
  // stream (symmetric fallback, no silent miss).
  QuerySpec spec;
  spec.query = "ox";
  spec.stem = true;
  std::vector<Hit> hits;
  ASSERT_TRUE(jsonl_query(w, spec, &hits, &error)) << error;
  EXPECT_EQ(docids(hits).count("s-3"), 1u);
  w->end();
}

TEST(JsonlStem, OverStemConflationPinned) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("stem_over", kStemRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<Hit> hits;

  // Exact "organ" matches neither "organization" nor "organs".
  QuerySpec exact;
  exact.query = "organ";
  ASSERT_TRUE(jsonl_query(w, exact, &hits, &error)) << error;
  EXPECT_TRUE(hits.empty());

  // --stem "organ" conflates with organization/organs -> s-2.
  QuerySpec stem;
  stem.query = "organ";
  stem.stem = true;
  ASSERT_TRUE(jsonl_query(w, stem, &hits, &error)) << error;
  EXPECT_EQ(docids(hits).count("s-2"), 1u);
  w->end();
}

TEST(JsonlStem, GclStem) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("stem_gcl", kStemRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  // (^ elephant fox) with --stem matches s-1 (elephants + foxes).
  QuerySpec spec;
  spec.is_gcl = true;
  spec.query = "(^ elephant fox)";
  spec.stem = true;
  std::vector<Hit> hits;
  ASSERT_TRUE(jsonl_query(w, spec, &hits, &error)) << error;
  EXPECT_EQ(docids(hits).count("s-1"), 1u);
  w->end();
}

TEST(JsonlStem, MissingStreamIsAnError) {
  std::string error, burrow;
  // Built WITHOUT a stemmer.
  ASSERT_TRUE(build_rows("stem_missing", kStemRows, "", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  QuerySpec spec;
  spec.query = "elephant";
  spec.stem = true;
  std::vector<Hit> hits;
  std::string qerr;
  EXPECT_FALSE(jsonl_query(w, spec, &hits, &qerr)); // no silent fallback
  EXPECT_FALSE(qerr.empty());
  w->end();
}

TEST(JsonlStem, ExplainStreamLabeling) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("stem_explain", kStemRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  QuerySpec spec;
  spec.query = "elephant ox";
  spec.stem = true;
  ExplainResult ex = jsonl_explain(w, spec);
  ASSERT_TRUE(ex.parsed_ok);
  const ExplainLeaf *el = leaf_of(ex, "elephant");
  const ExplainLeaf *ox = leaf_of(ex, "ox");
  ASSERT_NE(el, nullptr);
  ASSERT_NE(ox, nullptr);
  EXPECT_EQ(el->stream, "stemmed"); // elephant -> stemmed stream
  EXPECT_GT(el->df, 0);
  EXPECT_EQ(ox->stream, "exact"); // ox unstemmable -> exact stream
  EXPECT_GT(ox->df, 0);
  w->end();
}

// --- cover_search: word* family marker + cover-biased summary (A1) ---------

// AC#1 / AC#2: bear* matches a row whose body has only "bears"; bare bear does
// not, while still matching rows that literally contain "bear".
TEST(JsonlCover, FamilyRecallVsBareExact) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_family", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<CoverHit> hits;

  CoverSpec fam;
  fam.query = "bear*";
  ASSERT_TRUE(jsonl_cover_search(w, fam, &hits, &error)) << error;
  auto fam_ids = cover_docids(hits);
  EXPECT_EQ(fam_ids.count("c-2"), 1u); // "bears" reached via the family
  EXPECT_EQ(fam_ids.count("c-1"), 1u); // "bear" too

  CoverSpec bare;
  bare.query = "bear";
  ASSERT_TRUE(jsonl_cover_search(w, bare, &hits, &error)) << error;
  auto bare_ids = cover_docids(hits);
  EXPECT_EQ(bare_ids.count("c-2"), 0u); // only "bears" -> bare "bear" misses
  EXPECT_EQ(bare_ids.count("c-1"), 1u); // literal "bear" still matches
  w->end();
}

// AC#2 (second clause): a burrow built without a stemmer is unaffected, and a
// word* query against it is a hard error (no silent fallback) -- AC#7.
TEST(JsonlCover, NoStemmedStreamIsAnError) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_nostem", kCoverRows, "", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<CoverHit> hits;
  std::string qerr;
  CoverSpec spec;
  spec.query = "bear*";
  EXPECT_FALSE(jsonl_cover_search(w, spec, &hits, &qerr));
  EXPECT_FALSE(qerr.empty());
  w->end();
}

// AC#3: a mixed cover (^ black bear*) keeps black exact and bear* a family; a
// star-free quoted phrase is left exact.
TEST(JsonlCover, MixedCoverAndStarFreePhrase) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_mixed", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<CoverHit> hits;

  CoverSpec mix;
  mix.query = "(^ black bear*)";
  ASSERT_TRUE(jsonl_cover_search(w, mix, &hits, &error)) << error;
  auto ids = cover_docids(hits);
  EXPECT_EQ(ids.count("c-1"), 1u); // black + bear
  EXPECT_EQ(ids.count("c-4"), 1u); // black + bear
  EXPECT_EQ(ids.count("c-5"), 1u); // black + bears
  EXPECT_EQ(ids.count("c-2"), 0u); // bears but no black
  EXPECT_EQ(ids.count("c-3"), 0u); // neither

  CoverSpec phrase;
  phrase.query = "\"black bear\""; // star-free phrase -> exact, left quoted
  ASSERT_TRUE(jsonl_cover_search(w, phrase, &hits, &error)) << error;
  auto pids = cover_docids(hits);
  EXPECT_EQ(pids.count("c-1"), 1u); // adjacent "black bear"
  EXPECT_EQ(pids.count("c-2"), 0u);
  w->end();
}

// AC#4 / AC#9: ox* resolves through the single shared helper to the exact
// feature (Porter leaves "ox" unchanged) and matches, with no error.
TEST(JsonlCover, UnstemmableStarFallsBackToExact) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_ox", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<CoverHit> hits;
  CoverSpec spec;
  spec.query = "ox*";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
  EXPECT_EQ(cover_docids(hits).count("c-3"), 1u);
  w->end();
}

// AC#5: a starred word inside a quoted phrase is honored (desugar-with-stem
// before expand_phrases); "black bear*" matches the adjacent "black bears".
TEST(JsonlCover, StarHonoredInsidePhrase) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_phrase", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<CoverHit> hits;
  CoverSpec spec;
  spec.query = "\"black bear*\"";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
  EXPECT_EQ(cover_docids(hits).count("c-5"), 1u); // "black bears"
  w->end();
}

// AC#6: a non-trailing, mid-token '*' is a hard error (no crash).
TEST(JsonlCover, MidTokenStarIsAnError) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_badstar", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<CoverHit> hits;
  std::string qerr;
  CoverSpec spec;
  spec.query = "at*ack";
  EXPECT_FALSE(jsonl_cover_search(w, spec, &hits, &qerr));
  EXPECT_FALSE(qerr.empty());
  w->end();
}

// AC#8: operators and :tags survive the rewrite; (<< bear* :item) runs with
// :item intact and only bear* translated.
TEST(JsonlCover, TagsAndOperatorsUntouched) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_tags", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<CoverHit> hits;
  CoverSpec spec;
  spec.query = "(<< bear* :item)";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
  EXPECT_EQ(cover_docids(hits).count("c-2"), 1u); // family recall, :item intact
  w->end();
}

// AC#12: the per-document response is {rank, score, docid, summary}: rank is
// 1-based, score is the ssr sum (> 0 for a match), and summary is populated
// (it replaces the old best_passage).
TEST(JsonlCover, ResponseShape) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_shape", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<CoverHit> hits;
  CoverSpec spec;
  spec.query = "(^ black bear*)";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
  ASSERT_FALSE(hits.empty());
  EXPECT_EQ(hits[0].rank, 1);
  EXPECT_GT(hits[0].score, 0.0);
  EXPECT_FALSE(hits[0].docid.empty());
  EXPECT_FALSE(hits[0].summary.empty());
  // The summary is cover-biased: it contains the matched terms.
  EXPECT_NE(hits[0].summary.find("black"), std::string::npos);
  EXPECT_NE(hits[0].summary.find("bear"), std::string::npos);
  w->end();
}

// AC#13 / AC#14: with two well-separated covers the summary is two extents
// joined by the spaced-dots separator; nearby covers merge into one extent (no
// separator). Built in code to make the gap exceed the default 75-token window.
TEST(JsonlCover, SummaryWindowingAndGap) {
  std::string filler;
  for (int i = 0; i < 200; i++)
    filler += "alpha ";
  // needle ... (200 tokens) ... needle  -> two covers far enough apart that
  // their 75-token windows do not overlap even after edge-clamping.
  std::string content = "needle " + filler + "needle tail words here";
  std::vector<std::string> rows = {
      std::string(R"({"docid":"g-1","contents":")") + content + R"("})",
      R"({"docid":"g-2","contents":"needle needle close together once more"})",
  };
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_gap", rows, "porter", &burrow, &error)) << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::vector<CoverHit> hits;
  CoverSpec spec;
  spec.query = "needle";
  spec.top_k = 10;
  ASSERT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
  std::string g1, g2;
  for (const auto &h : hits) {
    if (h.docid == "g-1")
      g1 = h.summary;
    if (h.docid == "g-2")
      g2 = h.summary;
  }
  ASSERT_FALSE(g1.empty());
  ASSERT_FALSE(g2.empty());
  EXPECT_NE(g1.find(" . . . "), std::string::npos); // far apart -> gap shown
  EXPECT_EQ(g2.find(" . . . "), std::string::npos); // adjacent -> merged
  w->end();
}

// --- Tokenizer choice: ascii vs utf8 (docs/stemming.md §6) -----------------

namespace {
// Index one row of content with an explicit tokenizer/stemmer.
bool build_one(const std::string &name, const std::string &content,
               const std::string &tokenizer, const std::string &stemmer,
               std::string *burrow, std::string *error) {
  const char *t = std::getenv("TEST_TMPDIR");
  std::string base = (t != nullptr ? std::string(t) : std::string("/tmp"));
  std::string dir = base + "/" + name + "_src";
  std::error_code ec;
  std::filesystem::create_directories(dir, ec);
  {
    std::ofstream f(dir + "/sample.jsonl");
    f << "{\"docid\":\"d-1\",\"contents\":\"" << content << "\"}\n";
  }
  IndexOptions opts;
  opts.input = dir;
  opts.burrow = tmp_burrow(name);
  opts.overwrite = true;
  opts.tokenizer = tokenizer;
  opts.stemmer = stemmer;
  *burrow = opts.burrow;
  IndexSummary s;
  return jsonl_index(opts, &s, error);
}
} // namespace

TEST(JsonlTokenizer, Utf8KeepsAccentedWordsWholeAsciiDoesNot) {
  std::string error, bu, ba;
  ASSERT_TRUE(build_one("tok_u", "Montréal café", "utf8", "", &bu, &error))
      << error;
  ASSERT_TRUE(build_one("tok_a", "Montréal café", "ascii", "", &ba, &error))
      << error;
  auto wu = open_burrow(bu, &error);
  ASSERT_NE(wu, nullptr) << error;
  auto wa = open_burrow(ba, &error);
  ASSERT_NE(wa, nullptr) << error;
  EXPECT_EQ(wu->tokenizer()->name(), "utf8");
  EXPECT_EQ(wa->tokenizer()->name(), "ascii");
  // utf8: "Montréal" folds (capital + accent) to the whole token "montréal";
  // "café" is one token too.
  EXPECT_GT(wu->idx()->count(wu->featurizer()->featurize("montréal")), 0);
  EXPECT_GT(wu->idx()->count(wu->featurizer()->featurize("café")), 0);
  // ascii: the accent byte is a separator, so the whole accented word is never
  // a token.
  EXPECT_EQ(wa->idx()->count(wa->featurizer()->featurize("montréal")), 0);
  wu->end();
  wa->end();
}

TEST(JsonlTokenizer, DefaultsToUtf8AndReportsIt) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("tok_def"), &s, &error))
      << error;
  EXPECT_EQ(s.tokenizer, "utf8"); // default
  auto w = open_burrow(tmp_burrow("tok_def"), &error);
  ASSERT_NE(w, nullptr) << error;
  EXPECT_EQ(w->tokenizer()->name(), "utf8");
  w->end();
}

TEST(JsonlTokenizer, Utf8WithStem) {
  std::string error, b;
  ASSERT_TRUE(build_one("tok_us", "running foxes", "utf8", "porter", &b, &error))
      << error;
  auto w = open_burrow(b, &error);
  ASSERT_NE(w, nullptr) << error;
  EXPECT_EQ(w->tokenizer()->name(), "stemming"); // wraps utf8
  // English stemmed recall still works over a utf8 index.
  QuerySpec stem;
  stem.query = "run";
  stem.stem = true;
  std::vector<Hit> hits;
  ASSERT_TRUE(jsonl_query(w, stem, &hits, &error)) << error;
  EXPECT_EQ(docids(hits).count("d-1"), 1u); // "running" -> porter:run
  w->end();
}

TEST(JsonlTokenizer, UnknownTokenizerIsAnError) {
  std::string error, b;
  EXPECT_FALSE(build_one("tok_bad", "hello", "klingon", "", &b, &error));
  EXPECT_FALSE(error.empty());
}

// --- get_document (spec §3.1) ----------------------------------------------

TEST(JsonlGet, FetchByDocid) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("get1"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("get1"), &error);
  ASSERT_NE(w, nullptr) << error;
  std::string text;
  bool found = false;
  ASSERT_TRUE(jsonl_get(w, "doc-004", &text, &found, &error)) << error;
  EXPECT_TRUE(found);
  EXPECT_NE(text.find("elephants"), std::string::npos);
  // Unknown docid: not found, but not an error.
  ASSERT_TRUE(jsonl_get(w, "doc-999", &text, &found, &error)) << error;
  EXPECT_FALSE(found);
  EXPECT_TRUE(text.empty());
  w->end();
}

TEST(JsonlGet, ExactMatchGuard) {
  // "alpha"'s docno tokens are a subset of "alpha beta"'s; the exact-string guard
  // must still return the right row.
  std::string error, burrow;
  std::vector<std::string> rows = {
      R"({"docid":"alpha","contents":"the first document"})",
      R"({"docid":"alpha beta","contents":"the second document"})"};
  ASSERT_TRUE(build_rows("get_guard", rows, "", &burrow, &error)) << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  std::string text;
  bool found = false;
  ASSERT_TRUE(jsonl_get(w, "alpha", &text, &found, &error)) << error;
  EXPECT_TRUE(found);
  EXPECT_NE(text.find("first"), std::string::npos);
  EXPECT_EQ(text.find("second"), std::string::npos);
  ASSERT_TRUE(jsonl_get(w, "alpha beta", &text, &found, &error)) << error;
  EXPECT_TRUE(found);
  EXPECT_NE(text.find("second"), std::string::npos);
  w->end();
}

// --- count_matches (spec §3.3) ---------------------------------------------

TEST(JsonlCount, TextIsConjunctive) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("cnt1"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("cnt1"), &error);
  ASSERT_NE(w, nullptr) << error;
  long n = -1;
  QuerySpec a;
  a.query = "quick fox"; // both in doc-001 and doc-002
  ASSERT_TRUE(jsonl_count(w, a, &n, &error)) << error;
  EXPECT_EQ(n, 2);
  QuerySpec b;
  b.query = "quick dog"; // quick:{001,002} AND dog:{001,003} = {001}
  ASSERT_TRUE(jsonl_count(w, b, &n, &error)) << error;
  EXPECT_EQ(n, 1);
  w->end();
}

TEST(JsonlCount, GclAndStem) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("cnt2"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("cnt2"), &error);
  ASSERT_NE(w, nullptr) << error;
  long n = -1;
  QuerySpec g;
  g.is_gcl = true;
  g.query = "(^ lazy dog)"; // doc-001, doc-003
  ASSERT_TRUE(jsonl_count(w, g, &n, &error)) << error;
  EXPECT_EQ(n, 2);
  // malformed gcl -> hard error
  QuerySpec bad;
  bad.is_gcl = true;
  bad.query = "(^ lazy";
  EXPECT_FALSE(jsonl_count(w, bad, &n, &error));
  w->end();

  // stemmed count
  std::string burrow;
  ASSERT_TRUE(build_rows("cnt_stem", kStemRows, "porter", &burrow, &error))
      << error;
  auto ws = open_burrow(burrow, &error);
  ASSERT_NE(ws, nullptr) << error;
  QuerySpec st;
  st.query = "elephant fox"; // s-1: elephants + foxes
  st.stem = true;
  ASSERT_TRUE(jsonl_count(ws, st, &n, &error)) << error;
  EXPECT_EQ(n, 1);
  ws->end();
}
