#include <memory>
#include <set>
#include <string>
#include <vector>

#include "gtest/gtest.h"

#include "src/cottontail.h"
#include "src/content_index.h"

namespace {

// (label, contents) fixture. The first label tokenizes into "shard"/digits if it
// were ever indexed -- but cp-native indexing stores ONLY contents, so "shard"
// and the digit tokens must have zero postings.
struct Doc {
  std::string label; // a would-be docno; deliberately NOT indexed
  std::string contents;
};

const std::vector<Doc> kDocs = {
    {"shard_00037_72680", "black bear attacks on hikers"},
    {"doc-2", "the cat in the hat"},
    {"zzz-last", "final document about mountains and rivers"},
};

// Build a cp-native burrow from kDocs; return the started warren and, via *cps,
// the cp each add_document handed back (in kDocs order).
std::shared_ptr<cottontail::Warren> build_fixture(const std::string &burrow,
                                                  std::vector<cottontail::addr> *cps,
                                                  std::string *error) {
  std::shared_ptr<cottontail::Working> working =
      cottontail::Working::mkdir(burrow, error);
  if (working == nullptr)
    return nullptr;
  std::shared_ptr<cottontail::Builder> builder =
      cottontail::SimpleBuilder::make(working, "", error);
  if (builder == nullptr)
    return nullptr;
  auto indexer = cottontail::ContentIndexer::make(builder, error);
  if (indexer == nullptr)
    return nullptr;
  for (const auto &d : kDocs) {
    cottontail::addr cp = -1;
    if (!indexer->add_document(d.contents, &cp, error))
      return nullptr;
    if (cps != nullptr)
      cps->push_back(cp);
  }
  if (!indexer->finalize(error))
    return nullptr;
  auto warren = cottontail::Warren::make("simple", burrow, error);
  if (warren == nullptr)
    return nullptr;
  warren->start();
  return warren;
}

} // namespace

TEST(ContentIndex, NoDocnoTokensOrAnnotation) {
  std::string error;
  std::string burrow = cottontail::DEFAULT_BURROW;
  std::vector<cottontail::addr> cps;
  auto warren = build_fixture(burrow, &cps, &error);
  ASSERT_NE(warren, nullptr) << error;
  auto fz = warren->featurizer();
  auto idx = warren->idx();
  // The would-be docno was not tokenized: "shard" and the digit tokens are absent.
  EXPECT_EQ(idx->count(fz->featurize("shard")), 0);
  EXPECT_EQ(idx->count(fz->featurize("00037")), 0);
  // No ":docno" annotation exists; ":item" exists once per document.
  EXPECT_EQ(idx->count(fz->featurize(":docno")), 0);
  EXPECT_EQ(idx->count(fz->featurize(":item")),
            static_cast<cottontail::addr>(kDocs.size()));
  // The contents ARE indexed.
  EXPECT_GT(idx->count(fz->featurize("bear")), 0);
  EXPECT_GT(idx->count(fz->featurize("mountains")), 0);
  warren->end();
}

TEST(ContentIndex, CpIsItemStartUniqueAndIncreasing) {
  std::string error;
  std::string burrow = cottontail::DEFAULT_BURROW;
  std::vector<cottontail::addr> cps;
  auto warren = build_fixture(burrow, &cps, &error);
  ASSERT_NE(warren, nullptr) << error;
  ASSERT_EQ(cps.size(), kDocs.size());

  // The returned cps are strictly increasing by construction.
  for (size_t i = 1; i < cps.size(); i++)
    EXPECT_LT(cps[i - 1], cps[i]);

  // Each returned cp is a real ":item" start address.
  std::set<cottontail::addr> item_starts;
  {
    auto hopper = warren->hopper_from_gcl(":item", &error);
    ASSERT_NE(hopper, nullptr) << error;
    cottontail::addr p = cottontail::minfinity, q;
    for (hopper->tau(p + 1, &p, &q); p < cottontail::maxfinity;
         hopper->tau(p + 1, &p, &q))
      item_starts.insert(p);
  }
  EXPECT_EQ(item_starts.size(), kDocs.size());
  for (cottontail::addr cp : cps)
    EXPECT_EQ(item_starts.count(cp), 1u) << cp;

  // cp equals what ssr_ranking reports as container_p(): rank a term unique to
  // the first document and confirm the top result's container start is cps[0].
  std::vector<cottontail::RankingResult> ranked =
      cottontail::ssr_ranking(warren, "bear", ":item", 10);
  ASSERT_FALSE(ranked.empty());
  EXPECT_EQ(ranked[0].container_p(), cps[0]);
  warren->end();
}

TEST(ContentIndex, EmptyAndUntokenizableRejected) {
  std::string error;
  std::string burrow = cottontail::DEFAULT_BURROW;
  auto working = cottontail::Working::mkdir(burrow, &error);
  ASSERT_NE(working, nullptr) << error;
  auto builder = cottontail::SimpleBuilder::make(working, "", &error);
  ASSERT_NE(builder, nullptr) << error;
  auto indexer = cottontail::ContentIndexer::make(builder, &error);
  ASSERT_NE(indexer, nullptr) << error;
  cottontail::addr cp = -1;
  // Empty contents.
  EXPECT_FALSE(indexer->add_document("", &cp, &error));
  // Whitespace/punctuation-only contents -> no indexable tokens.
  EXPECT_FALSE(indexer->add_document("   \t  ", &cp, &error));
}
