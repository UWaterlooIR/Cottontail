// Regression tests for the cottontail-jsonl-index / -query CLIs, exercised at
// the library level (apps/jsonl_core.h). See docs/cottontail-jsonl-cli-spec.md
// §11. CLI process-boundary behavior (exit codes, batch) is covered separately
// by test/jsonl_cli.cc.

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "gtest/gtest.h"

#include "apps/jsonl_core.h"
#include "src/cottontail.h"

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

// cp-native: a hit carries its cp (the :item start). Recover the document body by
// translating the :item span at cp, so tests assert on content rather than docno
// (the engine no longer carries docno -- doc-6/doc-7).
std::string body_at(std::shared_ptr<cottontail::Warren> w, cottontail::addr cp) {
  std::string err;
  auto item = w->hopper_from_gcl(":item", &err);
  cottontail::addr p, q;
  item->tau(cp, &p, &q);
  return w->txt()->translate(cp, q);
}

std::set<std::string> hit_bodies(std::shared_ptr<cottontail::Warren> w,
                                 const std::vector<Hit> &hits) {
  std::set<std::string> s;
  for (const auto &h : hits)
    s.insert(body_at(w, h.cp));
  return s;
}

// True iff some hit's body contains `needle` (a substring unique to one fixture).
bool any_body_has(std::shared_ptr<cottontail::Warren> w,
                  const std::vector<Hit> &hits, const std::string &needle) {
  for (const auto &h : hits)
    if (body_at(w, h.cp).find(needle) != std::string::npos)
      return true;
  return false;
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

// cp-native: a cover hit carries its cp; recover the document body to assert by
// content (the engine no longer carries docno). True iff some hit's body has
// `needle` (a substring unique to one fixture row).
bool cover_has(std::shared_ptr<cottontail::Warren> w,
               const std::vector<CoverHit> &hits, const std::string &needle) {
  for (const auto &h : hits)
    if (body_at(w, h.cp).find(needle) != std::string::npos)
      return true;
  return false;
}

// The cp of the first cover hit whose body contains `needle`, or -1.
cottontail::addr cover_cp(std::shared_ptr<cottontail::Warren> w,
                          const std::vector<CoverHit> &hits,
                          const std::string &needle) {
  for (const auto &h : hits)
    if (body_at(w, h.cp).find(needle) != std::string::npos)
      return h.cp;
  return -1;
}

// The atom_counts entry for `term` (as written), or -1 if absent.
long atom_count(const CoverResponse &r, const std::string &term) {
  for (const auto &a : r.atom_counts)
    if (a.term == term)
      return a.count;
  return -1;
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

// cp-native (TASK-6.2): a duplicate docno is NOT detected at index time -- both
// rows are indexed and both appear in the flat (docno<TAB>cp) dump with distinct
// cps. docno uniqueness is enforced later, when the index CLI builds the SQLite
// map (TASK-6.3 UNIQUE index). (The JSON field holding the docno is "docid".)
TEST(JsonlIndex, DuplicateDocnoIndexedNotRejected) {
  std::string error, burrow;
  const std::vector<std::string> rows = {
      R"({"docid":"dup","contents":"first body about cats"})",
      R"({"docid":"dup","contents":"second body about dogs"})",
  };
  ASSERT_TRUE(build_rows("dup_index", rows, "", &burrow, &error)) << error;
  std::ifstream flat(burrow + "/docno-cp.tsv");
  ASSERT_TRUE(flat.good());
  std::vector<std::pair<std::string, cottontail::addr>> entries;
  std::string docno;
  cottontail::addr cp;
  while (flat >> docno >> cp)
    entries.emplace_back(docno, cp);
  ASSERT_EQ(entries.size(), 2u);
  EXPECT_EQ(entries[0].first, "dup");
  EXPECT_EQ(entries[1].first, "dup");
  EXPECT_NE(entries[0].second, entries[1].second); // distinct cps
}

TEST(JsonlQuery, RetrievalByCp) {
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
  // The top hit carries its cp (a real :item start); its body is doc-004's.
  EXPECT_NE(body_at(w, hits[0].cp).find("middle east"), std::string::npos);
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
  // "fox" is in the text of doc-001 ("brown fox") and doc-002 ("red fox").
  QuerySpec fox;
  fox.query = "fox";
  ASSERT_TRUE(jsonl_query(w, fox, &hits, &error)) << error;
  EXPECT_TRUE(any_body_has(w, hits, "brown fox"));
  EXPECT_TRUE(any_body_has(w, hits, "red fox"));
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
  EXPECT_EQ(hits.size(), 2u);
  EXPECT_TRUE(any_body_has(w, hits, "brown fox"));
  EXPECT_TRUE(any_body_has(w, hits, "red fox"));
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
  EXPECT_EQ(hit_bodies(wp, hp), hit_bodies(wg, hg));
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
  EXPECT_TRUE(any_body_has(w, hits, "jumped")); // s-1
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
  EXPECT_TRUE(any_body_has(w, hits, "jumped")); // s-1
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
  EXPECT_TRUE(any_body_has(w, hits, "cat")); // s-3
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
  EXPECT_TRUE(any_body_has(w, hits, "organization")); // s-2
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
  EXPECT_TRUE(any_body_has(w, hits, "jumped")); // s-1
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

TEST(JsonlStem, DISABLED_ExplainStreamLabeling) {
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
  CoverResponse hits;

  CoverSpec fam;
  fam.query = "bear*";
  ASSERT_TRUE(jsonl_cover_search(w, fam, &hits, &error)) << error;
  EXPECT_TRUE(cover_has(w, hits.results, "camp"));   // c-2 "bears" via the family
  EXPECT_TRUE(cover_has(w, hits.results, "hikers")); // c-1 "bear" too

  CoverSpec bare;
  bare.query = "bear";
  ASSERT_TRUE(jsonl_cover_search(w, bare, &hits, &error)) << error;
  EXPECT_FALSE(cover_has(w, hits.results, "camp"));  // c-2 only "bears" -> miss
  EXPECT_TRUE(cover_has(w, hits.results, "hikers")); // c-1 literal "bear" matches
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
  CoverResponse hits;
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
  CoverResponse hits;

  CoverSpec mix;
  mix.query = "(^ black bear*)";
  ASSERT_TRUE(jsonl_cover_search(w, mix, &hits, &error)) << error;
  EXPECT_TRUE(cover_has(w, hits.results, "hikers"));   // c-1 black + bear
  EXPECT_TRUE(cover_has(w, hits.results, "grizzly"));  // c-4 black + bear
  EXPECT_TRUE(cover_has(w, hits.results, "roam"));     // c-5 black + bears
  EXPECT_FALSE(cover_has(w, hits.results, "camp"));    // c-2 bears but no black
  EXPECT_FALSE(cover_has(w, hits.results, "cart"));    // c-3 neither

  CoverSpec phrase;
  phrase.query = "\"black bear\""; // star-free phrase -> exact, left quoted
  ASSERT_TRUE(jsonl_cover_search(w, phrase, &hits, &error)) << error;
  EXPECT_TRUE(cover_has(w, hits.results, "hikers"));  // c-1 adjacent "black bear"
  EXPECT_FALSE(cover_has(w, hits.results, "camp"));   // c-2
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
  CoverResponse hits;
  CoverSpec spec;
  spec.query = "ox*";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
  EXPECT_TRUE(cover_has(w, hits.results, "cart")); // c-3 "ox"
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
  CoverResponse hits;
  CoverSpec spec;
  spec.query = "\"black bear*\"";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
  EXPECT_TRUE(cover_has(w, hits.results, "roam")); // c-5 "black bears"
  w->end();
}

// AC#6: a non-trailing, mid-token '*' is a hard error (no crash).
TEST(JsonlCover, MidTokenStarIsAnError) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_badstar", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  CoverResponse hits;
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
  CoverResponse hits;
  CoverSpec spec;
  spec.query = "(<< bear* :item)";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
  EXPECT_TRUE(cover_has(w, hits.results, "camp")); // c-2 family recall, :item intact
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
  CoverResponse hits;
  CoverSpec spec;
  spec.query = "(^ black bear*)";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
  ASSERT_FALSE(hits.results.empty());
  EXPECT_EQ(hits.results[0].rank, 1);
  EXPECT_GT(hits.results[0].score, 0.0);
  EXPECT_FALSE(body_at(w, hits.results[0].cp).empty()); // cp resolves to a body
  EXPECT_FALSE(hits.results[0].summary.empty());
  // The summary is cover-biased: it contains the matched terms.
  EXPECT_NE(hits.results[0].summary.find("black"), std::string::npos);
  EXPECT_NE(hits.results[0].summary.find("bear"), std::string::npos);
  w->end();
}

// AC#13 / AC#14 + TASK-12: with max_covers >= 2, two well-separated covers give
// two extents joined by the spaced-dots separator while nearby covers merge into
// one extent (no separator). With the DEFAULT max_covers=1 only the single best
// (tightest) cover is summarized, so a far-apart doc shows ONE extent (no gap) and
// does not sprawl across the body. Built in code to make the gap exceed the
// default 75-token window.
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
  // Pull the g-1 (far-apart) and g-2 (adjacent) summaries from one run.
  auto summaries = [&](size_t max_covers) {
    CoverResponse hits;
    CoverSpec spec;
    spec.query = "needle";
    spec.top_k = 10;
    spec.max_covers = max_covers;
    EXPECT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
    std::string g1, g2;
    for (const auto &h : hits.results) {
      std::string body = body_at(w, h.cp);
      if (body.find("tail words") != std::string::npos) // g-1
        g1 = h.summary;
      if (body.find("once more") != std::string::npos) // g-2
        g2 = h.summary;
    }
    return std::make_pair(g1, g2);
  };
  // K=2: both covers summarized -> g-1's far-apart windows show the gap; g-2's
  // adjacent windows merge into one extent.
  auto [g1_2, g2_2] = summaries(2);
  ASSERT_FALSE(g1_2.empty());
  ASSERT_FALSE(g2_2.empty());
  EXPECT_NE(g1_2.find(" . . . "), std::string::npos); // far apart -> gap shown
  EXPECT_EQ(g2_2.find(" . . . "), std::string::npos); // adjacent -> merged
  // K=1 (default): only the single best cover -> g-1 is one extent (no gap) and
  // stays near that cover instead of sprawling to the doc tail.
  auto [g1_1, g2_1] = summaries(1);
  ASSERT_FALSE(g1_1.empty());
  EXPECT_EQ(g1_1.find(" . . . "), std::string::npos);   // single best cover -> no gap
  EXPECT_EQ(g1_1.find("tail words"), std::string::npos); // does not reach the tail
  w->end();
}

// --- cover_search enrichment: counts, exclusion, atom_counts, window (A2) --

// AC#1 / AC#2 / AC#5 / Q2: total/unjudged document counts and exclude (cp).
TEST(JsonlCover, TotalAndUnjudgedMatchesAndExclude) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_counts", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  CoverResponse resp;
  CoverSpec spec;
  spec.query = "bear*"; // matches c-1, c-2, c-4, c-5 (not c-3)

  ASSERT_TRUE(jsonl_cover_search(w, spec, &resp, &error)) << error;
  EXPECT_EQ(resp.total_matches, 4);
  EXPECT_EQ(resp.unjudged_matches, 4); // no exclusion -> equal
  // c-2's cp (a match) from this result; c-3's cp (a non-match) via an ox* search.
  cottontail::addr cp_c2 = cover_cp(w, resp.results, "camp");
  ASSERT_GE(cp_c2, 0);

  // total_matches is independent of top_k.
  spec.top_k = 1;
  ASSERT_TRUE(jsonl_cover_search(w, spec, &resp, &error)) << error;
  EXPECT_EQ(resp.total_matches, 4);
  spec.top_k = 10;

  // Excluding a MATCHING cp drops unjudged by one; total is unchanged; the
  // excluded cp is gone from the results (cp post-filter, AC#5).
  spec.exclude = {cp_c2};
  ASSERT_TRUE(jsonl_cover_search(w, spec, &resp, &error)) << error;
  EXPECT_EQ(resp.total_matches, 4);
  EXPECT_EQ(resp.unjudged_matches, 3);
  EXPECT_FALSE(cover_has(w, resp.results, "camp")); // c-2 excluded

  // Excluding a NON-matching cp (c-3 has no bear) leaves unjudged == total
  // (unjudged = total - excluded-that-match, NOT total - |exclude|, Q2).
  CoverResponse ox;
  CoverSpec oxspec;
  oxspec.query = "ox*";
  ASSERT_TRUE(jsonl_cover_search(w, oxspec, &ox, &error)) << error;
  cottontail::addr cp_c3 = cover_cp(w, ox.results, "cart");
  ASSERT_GE(cp_c3, 0);
  spec.exclude = {cp_c3};
  ASSERT_TRUE(jsonl_cover_search(w, spec, &resp, &error)) << error;
  EXPECT_EQ(resp.unjudged_matches, 4);
  w->end();
}

// AC#6 / AC#7: excluding the top hit promotes the next-best to rank 1; surviving
// scores are exclusion-invariant; rank restarts at 1 with no gaps.
TEST(JsonlCover, ExcludePromotesNextBestScoreInvariant) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_promote", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  CoverResponse resp1;
  CoverSpec spec;
  spec.query = "bear*";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &resp1, &error)) << error;
  ASSERT_GE(resp1.results.size(), 2u);
  cottontail::addr top = resp1.results[0].cp;
  cottontail::addr survivor = resp1.results[1].cp; // next-best
  double survivor_score = resp1.results[1].score;

  CoverResponse resp2;
  spec.exclude = {top};
  ASSERT_TRUE(jsonl_cover_search(w, spec, &resp2, &error)) << error;
  ASSERT_FALSE(resp2.results.empty());
  EXPECT_NE(resp2.results[0].cp, top); // next-best is now rank 1
  bool top_present = false, survivor_present = false;
  int expect_rank = 1;
  for (const auto &h : resp2.results) {
    EXPECT_EQ(h.rank, expect_rank++); // restarts at 1, no gaps
    if (h.cp == top)
      top_present = true;
    if (h.cp == survivor) {
      survivor_present = true;
      EXPECT_DOUBLE_EQ(h.score, survivor_score); // score is per-document
    }
  }
  EXPECT_FALSE(top_present);    // top cp post-filtered out
  EXPECT_TRUE(survivor_present);
  w->end();
}

// AC#3 / AC#4 / Q4: atom_counts (occurrences, term-as-written, zero flags a dead
// atom, word* family vs exact, dedup, phrase words as leaves).
TEST(JsonlCover, AtomCounts) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_atoms", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  CoverResponse resp;
  CoverSpec spec;
  spec.query = "(^ black bear* zzz*)";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &resp, &error)) << error;
  EXPECT_EQ(resp.atom_counts.size(), 3u);
  EXPECT_GT(atom_count(resp, "black"), 0);
  EXPECT_GT(atom_count(resp, "bear*"), 0);
  EXPECT_EQ(atom_count(resp, "zzz*"), 0);       // dead atom -> 0 occurrences
  EXPECT_EQ(atom_count(resp, "porter:bear"), -1); // never the porter: form

  // ox* is unstemmable -> resolves to the exact feature and counts it (AC#4).
  spec.query = "ox*";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &resp, &error)) << error;
  EXPECT_EQ(resp.atom_counts.size(), 1u);
  EXPECT_GT(atom_count(resp, "ox*"), 0);

  // Phrase words are individual leaves; bare "bear" and family "bear*" are
  // distinct leaves (family count >= exact count); dedup keeps one row per term.
  spec.query = "(^ \"black bear\" bear*)";
  ASSERT_TRUE(jsonl_cover_search(w, spec, &resp, &error)) << error;
  EXPECT_EQ(resp.atom_counts.size(), 3u); // black, bear, bear*
  EXPECT_GT(atom_count(resp, "black"), 0);
  EXPECT_GT(atom_count(resp, "bear"), 0);
  EXPECT_GT(atom_count(resp, "bear*"), 0);
  EXPECT_GE(atom_count(resp, "bear*"), atom_count(resp, "bear"));
  w->end();
}

// AC#13 / AC#14: a larger window yields a longer summary; rank and score are
// unchanged (window affects only the summary text, not ranking).
TEST(JsonlCover, WindowOverrideLongerSummary) {
  std::string body = "lead ";
  for (int i = 0; i < 100; i++)
    body += "alpha ";
  body += "target ";
  for (int i = 0; i < 100; i++)
    body += "beta ";
  body += "end";
  std::vector<std::string> rows = {
      std::string(R"({"docid":"w-1","contents":")") + body + R"("})"};
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_window", rows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;

  CoverResponse small, large;
  CoverSpec spec;
  spec.query = "target";
  spec.window = 8;
  ASSERT_TRUE(jsonl_cover_search(w, spec, &small, &error)) << error;
  spec.window = 80;
  ASSERT_TRUE(jsonl_cover_search(w, spec, &large, &error)) << error;
  ASSERT_FALSE(small.results.empty());
  ASSERT_FALSE(large.results.empty());
  EXPECT_GT(large.results[0].summary.size(), small.results[0].summary.size());
  EXPECT_DOUBLE_EQ(small.results[0].score, large.results[0].score);
  EXPECT_EQ(small.results[0].rank, large.results[0].rank);
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
  EXPECT_TRUE(any_body_has(w, hits, "running")); // d-1: "running" -> porter:run
  w->end();
}

TEST(JsonlTokenizer, UnknownTokenizerIsAnError) {
  std::string error, b;
  EXPECT_FALSE(build_one("tok_bad", "hello", "klingon", "", &b, &error));
  EXPECT_FALSE(error.empty());
}

// --- get_document (spec §3.1) ----------------------------------------------

TEST(JsonlGet, FetchByCp) {
  std::string error;
  IndexSummary s;
  ASSERT_TRUE(build("test/jsonl/plain", tmp_burrow("get1"), &s, &error)) << error;
  auto w = open_burrow(tmp_burrow("get1"), &error);
  ASSERT_NE(w, nullptr) << error;
  // cp-native: get a real cp from a search, then fetch the full body by cp.
  QuerySpec spec;
  spec.query = "elephants";
  std::vector<Hit> hits;
  ASSERT_TRUE(jsonl_query(w, spec, &hits, &error)) << error;
  ASSERT_FALSE(hits.empty());
  std::string text;
  bool found = false;
  ASSERT_TRUE(jsonl_get(w, hits[0].cp, &text, &found, &error)) << error;
  EXPECT_TRUE(found);
  EXPECT_NE(text.find("elephants"), std::string::npos);
  // A cp that is not an :item start: not found, but not an error.
  ASSERT_TRUE(jsonl_get(w, 999999999, &text, &found, &error)) << error;
  EXPECT_FALSE(found);
  EXPECT_TRUE(text.empty());
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

// cp-native (TASK-6.2): the burrow carries NO :docno and no docno tokens; the
// docno is paired with its cp only in the flat <burrow>/docno-cp.tsv dump (from
// which the index CLI, TASK-6.3, builds the cp<->docno SQLite map). Assert the
// dump lists (docno, cp) for each row, with each cp a real ":item" start whose
// body translates back to that row's text.
TEST(JsonlFlatDump, MapsDocnoToItemStart) {
  std::string error;
  IndexSummary s;
  std::string burrow = tmp_burrow("flat1");
  ASSERT_TRUE(build("test/jsonl/plain", burrow, &s, &error)) << error;
  EXPECT_EQ(s.rows_indexed, 4u);

  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  // No :docno annotation and no docno tokens were indexed.
  auto fz = w->featurizer();
  EXPECT_EQ(w->idx()->count(fz->featurize(":docno")), 0);
  EXPECT_EQ(w->idx()->count(fz->featurize("doc")), 0); // from "doc-00N"
  EXPECT_EQ(w->idx()->count(fz->featurize(":item")), 4);

  // Collect the ":item" spans: cp (start) -> cq (end).
  std::map<cottontail::addr, cottontail::addr> item_span;
  {
    auto hopper = w->hopper_from_gcl(":item", &error);
    ASSERT_NE(hopper, nullptr) << error;
    cottontail::addr p = cottontail::minfinity, q;
    for (hopper->tau(p + 1, &p, &q); p < cottontail::maxfinity;
         hopper->tau(p + 1, &p, &q))
      item_span[p] = q;
  }
  EXPECT_EQ(item_span.size(), 4u);

  // The flat dump maps each docno to a cp that is a real ":item" start, and the
  // body at that span is the row's text.
  const std::map<std::string, std::string> expected = {
      {"doc-001", "the quick brown fox jumps over the lazy dog"},
      {"doc-002", "a quick red fox runs very fast"},
      {"doc-003", "the lazy dog sleeps all day long"},
      {"doc-004", "elephants disappeared from the middle east long ago"},
  };
  std::ifstream flat(burrow + "/docno-cp.tsv");
  ASSERT_TRUE(flat.good());
  size_t seen = 0;
  std::string docno;
  cottontail::addr cp;
  while (flat >> docno >> cp) {
    seen++;
    ASSERT_EQ(item_span.count(cp), 1u) << docno << " cp=" << cp;
    auto it = expected.find(docno);
    ASSERT_NE(it, expected.end()) << docno;
    std::string body = w->txt()->translate(cp, item_span[cp]);
    EXPECT_EQ(body.compare(0, it->second.size(), it->second), 0)
        << "got: [" << body << "]";
  }
  EXPECT_EQ(seen, 4u);
  w->end();
}

// TASK-14: max_words caps the whole summary (in tokens). A cover wider than the cap
// is shown from its START and ends with " ..."; max_words=0 is uncapped.
TEST(JsonlCover, MaxWordsCap) {
  std::string filler;
  for (int i = 0; i < 200; i++)
    filler += "mid ";
  // alpha ... (200 tokens) ... beta  -> one cover spanning > 150 tokens.
  std::string content = "alpha " + filler + "beta tail";
  std::vector<std::string> rows = {
      std::string(R"({"docid":"w-1","contents":")") + content + R"("})"};
  std::string error, burrow;
  ASSERT_TRUE(build_rows("cover_maxwords", rows, "porter", &burrow, &error)) << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;
  auto summary = [&](size_t max_words) {
    CoverResponse hits;
    CoverSpec spec;
    spec.query = "(^ alpha beta)";
    spec.max_words = max_words;
    EXPECT_TRUE(jsonl_cover_search(w, spec, &hits, &error)) << error;
    return hits.results.empty() ? std::string() : hits.results[0].summary;
  };
  // default cap (150 tokens): starts at the cover (alpha), is cut before beta
  // (200+ tokens away), and ends with the truncation marker.
  std::string capped = summary(150);
  ASSERT_FALSE(capped.empty());
  EXPECT_EQ(capped.rfind("alpha", 0), 0u);            // starts at the cover start
  EXPECT_EQ(capped.find("beta"), std::string::npos);  // cut before the far term
  EXPECT_NE(capped.find(" ..."), std::string::npos);  // truncation marked
  // uncapped: the whole cover -> reaches beta, no marker, longer.
  std::string full = summary(0);
  EXPECT_NE(full.find("beta"), std::string::npos);
  EXPECT_EQ(full.find(" ..."), std::string::npos);
  EXPECT_GT(full.size(), capped.size());
  w->end();
}

// --- tiered_query_search: an ordered de-duplicated cascade of covers (TASK-19) ---

namespace {
// A long two-anchor doc: "alpha" near the start and "omega" near the end, far
// apart, so a small-window summary reveals WHICH tier's cover it was built around.
const std::vector<std::string> kTierRows = {
    R"({"docid":"t-1","contents":"alpha one two three four five six seven eight nine ten omega"})",
};

// The first result hit whose body contains `needle`, or nullptr.
const CoverHit *tier_hit(std::shared_ptr<cottontail::Warren> w,
                         const std::vector<CoverHit> &hits,
                         const std::string &needle) {
  for (const auto &h : hits)
    if (body_at(w, h.cp).find(needle) != std::string::npos)
      return &h;
  return nullptr;
}
} // namespace

// AC#8: a single-tier cascade is byte-for-byte the same as cover_search -- same
// counts, atom_counts, and per-hit rank/cp/score/summary (the base case).
TEST(JsonlTiered, SingleTierEqualsCoverSearch) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("tiered_base", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;

  CoverResponse cover;
  CoverSpec cs;
  cs.query = "(^ black bear*)";
  ASSERT_TRUE(jsonl_cover_search(w, cs, &cover, &error)) << error;

  CoverResponse tiered;
  TieredSpec ts;
  ts.tiers = {"(^ black bear*)"};
  ASSERT_TRUE(jsonl_tiered_query_search(w, ts, &tiered, &error)) << error;

  EXPECT_EQ(cover.total_matches, tiered.total_matches);
  EXPECT_EQ(cover.unjudged_matches, tiered.unjudged_matches);
  ASSERT_EQ(cover.atom_counts.size(), tiered.atom_counts.size());
  for (size_t i = 0; i < cover.atom_counts.size(); i++) {
    EXPECT_EQ(cover.atom_counts[i].term, tiered.atom_counts[i].term);
    EXPECT_EQ(cover.atom_counts[i].count, tiered.atom_counts[i].count);
  }
  ASSERT_EQ(cover.results.size(), tiered.results.size());
  for (size_t i = 0; i < cover.results.size(); i++) {
    EXPECT_EQ(cover.results[i].rank, tiered.results[i].rank);
    EXPECT_EQ(cover.results[i].cp, tiered.results[i].cp);
    EXPECT_DOUBLE_EQ(cover.results[i].score, tiered.results[i].score);
    EXPECT_EQ(cover.results[i].summary, tiered.results[i].summary);
  }
  w->end();
}

// AC#2: the cascade de-dups across tiers (a cp from a tighter tier never reappears)
// and tighter tiers outrank looser ones (tier-monotonic score).
TEST(JsonlTiered, CascadeDedupAndTierOrder) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("tiered_dedup", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;

  TieredSpec ts;
  ts.tiers = {"(^ black bear*)", "bear*"}; // tier 0 subset of tier 1
  CoverResponse r;
  ASSERT_TRUE(jsonl_tiered_query_search(w, ts, &r, &error)) << error;

  EXPECT_TRUE(cover_has(w, r.results, "hikers"));  // c-1 black bear
  EXPECT_TRUE(cover_has(w, r.results, "grizzly")); // c-4 black bear
  EXPECT_TRUE(cover_has(w, r.results, "roam"));    // c-5 black bears
  EXPECT_TRUE(cover_has(w, r.results, "camp"));    // c-2 bears (tier 1 only)
  EXPECT_FALSE(cover_has(w, r.results, "cart"));   // c-3 neither

  // c-1 is matched by BOTH tiers but appears exactly once (merge-skip de-dup).
  int hikers = 0;
  for (const auto &h : r.results)
    if (body_at(w, h.cp).find("hikers") != std::string::npos)
      hikers++;
  EXPECT_EQ(hikers, 1);

  // the tier-1-only doc (camp) ranks below, and scores below, every tier-0 doc.
  const CoverHit *camp = tier_hit(w, r.results, "camp");
  const CoverHit *hik = tier_hit(w, r.results, "hikers");
  ASSERT_NE(camp, nullptr);
  ASSERT_NE(hik, nullptr);
  EXPECT_GT(camp->rank, hik->rank);
  EXPECT_LT(camp->score, hik->score);
  w->end();
}

// AC#3: cps in the incoming exclude never appear in the results.
TEST(JsonlTiered, ExcludeIsHonored) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("tiered_exclude", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;

  TieredSpec ts;
  ts.tiers = {"(^ black bear*)", "bear*"};
  CoverResponse r0;
  ASSERT_TRUE(jsonl_tiered_query_search(w, ts, &r0, &error)) << error;
  cottontail::addr cp_c1 = cover_cp(w, r0.results, "hikers");

  ts.exclude = {cp_c1};
  CoverResponse r1;
  ASSERT_TRUE(jsonl_tiered_query_search(w, ts, &r1, &error)) << error;
  EXPECT_FALSE(cover_has(w, r1.results, "hikers")); // the excluded cp is gone
  EXPECT_TRUE(cover_has(w, r1.results, "camp"));     // others remain
  w->end();
}

// AC#6: total/unjudged are the EXACT distinct union across tiers (not the per-tier
// sum, which would double-count the overlap), and are 0 iff every tier is dry.
TEST(JsonlTiered, ExactUnionCountsNotSum) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("tiered_counts", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;

  // tier 0 matches {c-1,c-4,c-5} (3); tier 1 matches {c-1,c-2,c-4,c-5} (4).
  // Distinct union = 4; the per-tier SUM would be 7.
  TieredSpec ts;
  ts.tiers = {"(^ black bear*)", "bear*"};
  CoverResponse r;
  ASSERT_TRUE(jsonl_tiered_query_search(w, ts, &r, &error)) << error;
  EXPECT_EQ(r.total_matches, 4);
  EXPECT_EQ(r.unjudged_matches, 4);

  // all tiers dry -> 0; a count-0 atom is NOT an error, it just goes dry.
  TieredSpec dry;
  dry.tiers = {"zzzznope", "qqqxxx"};
  CoverResponse rd;
  std::string derr;
  ASSERT_TRUE(jsonl_tiered_query_search(w, dry, &rd, &derr)) << derr;
  EXPECT_EQ(rd.total_matches, 0);
  EXPECT_EQ(rd.unjudged_matches, 0);
  EXPECT_TRUE(rd.results.empty());
  ASSERT_EQ(rd.atom_counts.size(), 2u); // atoms present + deterministic ...
  for (const auto &a : rd.atom_counts)
    EXPECT_EQ(a.count, 0); // ... each 0 => a diagnosable dead atom

  // one live tier among dead ones -> not dry (0 iff ALL dry).
  TieredSpec mix;
  mix.tiers = {"zzzznope", "bear*"};
  CoverResponse rm;
  ASSERT_TRUE(jsonl_tiered_query_search(w, mix, &rm, &error)) << error;
  EXPECT_GT(rm.total_matches, 0);
  w->end();
}

// AC#7: each summary is built against the SPECIFIC tier that surfaced the document.
// The same doc, with the tier order flipped, is summarized around the other anchor.
TEST(JsonlTiered, PerTierSummaryBiasing) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("tiered_summary", kTierRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;

  // "omega" is the tighter (first) tier -> the summary is biased to omega.
  TieredSpec a;
  a.tiers = {"omega", "alpha"};
  a.window = 3;
  a.max_covers = 1;
  CoverResponse ra;
  ASSERT_TRUE(jsonl_tiered_query_search(w, a, &ra, &error)) << error;
  ASSERT_EQ(ra.results.size(), 1u);
  EXPECT_NE(ra.results[0].summary.find("omega"), std::string::npos);
  EXPECT_EQ(ra.results[0].summary.find("alpha"), std::string::npos);

  // flip the order -> "alpha" now surfaces the doc, and the summary follows it.
  TieredSpec b;
  b.tiers = {"alpha", "omega"};
  b.window = 3;
  b.max_covers = 1;
  CoverResponse rb;
  ASSERT_TRUE(jsonl_tiered_query_search(w, b, &rb, &error)) << error;
  ASSERT_EQ(rb.results.size(), 1u);
  EXPECT_NE(rb.results[0].summary.find("alpha"), std::string::npos);
  EXPECT_EQ(rb.results[0].summary.find("omega"), std::string::npos);
  w->end();
}

// AC#15: a malformed tier fails the WHOLE request (whole-request-fail), and the
// error NAMES the offending tier (by index) so the agent fixes the right one.
TEST(JsonlTiered, MalformedTierFailsWholeRequestNamingTier) {
  std::string error, burrow;
  ASSERT_TRUE(build_rows("tiered_bad", kCoverRows, "porter", &burrow, &error))
      << error;
  auto w = open_burrow(burrow, &error);
  ASSERT_NE(w, nullptr) << error;

  // a GCL syntax error in tier 1 rejects the whole call, naming "tier 1".
  TieredSpec unbalanced;
  unbalanced.tiers = {"(^ black bear*)", "(^ unbalanced"};
  CoverResponse r1;
  std::string e1;
  EXPECT_FALSE(jsonl_tiered_query_search(w, unbalanced, &r1, &e1));
  EXPECT_NE(e1.find("tier 1"), std::string::npos) << e1;

  // a bad mid-token '*' in tier 0 is likewise named.
  TieredSpec badstar;
  badstar.tiers = {"bad*star*mid"};
  CoverResponse r0;
  std::string e0;
  EXPECT_FALSE(jsonl_tiered_query_search(w, badstar, &r0, &e0));
  EXPECT_NE(e0.find("tier 0"), std::string::npos) << e0;
  w->end();
}
