#include <memory>
#include <set>
#include <string>
#include <vector>

#include "gtest/gtest.h"

#include "src/cottontail.h"
#include "src/docno_contents_index.h"

namespace {

// (docno, contents) fixture. The first docno tokenizes into "shard"/digits if it
// were ever indexed -- it must NOT be, so "shard" must have zero postings.
struct Doc {
  std::string docno;
  std::string contents;
};

const std::vector<Doc> kDocs = {
    {"shard_00037_72680", "black bear attacks on hikers"},
    {"doc-2", "the cat in the hat"},
    {"zzz-last", "final document about mountains and rivers"},
};

std::shared_ptr<cottontail::Warren> build_fixture(const std::string &burrow,
                                                  std::string *error) {
  std::shared_ptr<cottontail::Working> working =
      cottontail::Working::mkdir(burrow, error);
  if (working == nullptr)
    return nullptr;
  std::shared_ptr<cottontail::Builder> builder =
      cottontail::SimpleBuilder::make(working, "", error);
  if (builder == nullptr)
    return nullptr;
  auto indexer = cottontail::DocnoContentsIndexer::make(builder, working, error);
  if (indexer == nullptr)
    return nullptr;
  for (const auto &d : kDocs)
    if (!indexer->add_document(d.docno, d.contents, error))
      return nullptr;
  if (!indexer->finalize(error))
    return nullptr;
  auto warren = cottontail::Warren::make("simple", burrow, error);
  if (warren == nullptr)
    return nullptr;
  warren->start();
  return warren;
}

} // namespace

TEST(DocnoContentsIndex, NoDocnoTokensOrAnnotation) {
  std::string error;
  std::string burrow = cottontail::DEFAULT_BURROW;
  auto warren = build_fixture(burrow, &error);
  ASSERT_NE(warren, nullptr) << error;
  auto fz = warren->featurizer();
  auto idx = warren->idx();
  // The docno was not tokenized: "shard" (and the digit tokens) are absent.
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

TEST(DocnoContentsIndex, RoundTripAndSpansAndFetch) {
  std::string error;
  std::string burrow = cottontail::DEFAULT_BURROW;
  auto warren = build_fixture(burrow, &error);
  ASSERT_NE(warren, nullptr) << error;
  auto working = cottontail::Working::make(burrow, &error);
  ASSERT_NE(working, nullptr) << error;
  auto sidecar = cottontail::DocnoContentsSidecar::open(working, &error);
  ASSERT_NE(sidecar, nullptr) << error;

  // The cp set from the sidecar matches the actual ":item" start addresses.
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

  for (const auto &d : kDocs) {
    cottontail::addr cp = -1;
    ASSERT_TRUE(sidecar->cp_of(d.docno, &cp)) << d.docno;
    EXPECT_EQ(item_starts.count(cp), 1u) << d.docno; // cp is a real :item start
    // Reverse round-trips back to the same docno.
    std::string back;
    ASSERT_TRUE(sidecar->docno_of(cp, &back));
    EXPECT_EQ(back, d.docno);
    // span_of derives (cp, cq); the body translates to the contents. The
    // tokenizer appends a trailing separator, so compare on a prefix.
    cottontail::addr sp, sq;
    ASSERT_TRUE(sidecar->span_of(cp, &sp, &sq));
    EXPECT_EQ(sp, cp);
    std::string body = warren->txt()->translate(sp, sq);
    EXPECT_EQ(body.compare(0, d.contents.size(), d.contents), 0)
        << "got: [" << body << "]";
    // Fetch helpers.
    std::string by_cp, by_docno;
    bool found = false;
    ASSERT_TRUE(sidecar->text_by_cp(warren, cp, &by_cp, &found, &error));
    EXPECT_TRUE(found);
    EXPECT_EQ(by_cp, body);
    found = false;
    ASSERT_TRUE(
        sidecar->text_by_docno(warren, d.docno, &by_docno, &found, &error));
    EXPECT_TRUE(found);
    EXPECT_EQ(by_docno, body);
  }
  warren->end();
}

TEST(DocnoContentsIndex, UnknownNotFound) {
  std::string error;
  std::string burrow = cottontail::DEFAULT_BURROW;
  auto warren = build_fixture(burrow, &error);
  ASSERT_NE(warren, nullptr) << error;
  auto working = cottontail::Working::make(burrow, &error);
  auto sidecar = cottontail::DocnoContentsSidecar::open(working, &error);
  ASSERT_NE(sidecar, nullptr) << error;

  cottontail::addr cp = -1;
  EXPECT_FALSE(sidecar->cp_of("no-such-docno", &cp));
  std::string docno;
  EXPECT_FALSE(sidecar->docno_of(123456789, &docno)); // not an :item start
  cottontail::addr p, q;
  EXPECT_FALSE(sidecar->span_of(123456789, &p, &q));

  bool found = true;
  std::string text;
  EXPECT_TRUE(sidecar->text_by_docno(warren, "no-such-docno", &text, &found,
                                     &error));
  EXPECT_FALSE(found);
  found = true;
  EXPECT_TRUE(sidecar->text_by_cp(warren, 123456789, &text, &found, &error));
  EXPECT_FALSE(found);
  warren->end();
}

TEST(DocnoContentsIndex, DuplicateDocnoRejected) {
  std::string error;
  std::string burrow = cottontail::DEFAULT_BURROW;
  auto working = cottontail::Working::mkdir(burrow, &error);
  ASSERT_NE(working, nullptr) << error;
  auto builder = cottontail::SimpleBuilder::make(working, "", &error);
  ASSERT_NE(builder, nullptr) << error;
  auto indexer = cottontail::DocnoContentsIndexer::make(builder, working, &error);
  ASSERT_NE(indexer, nullptr) << error;
  ASSERT_TRUE(indexer->add_document("dup", "first contents", &error));
  ASSERT_TRUE(indexer->add_document("dup", "second contents", &error));
  // The duplicate is caught at finalize, while building the reverse permutation.
  EXPECT_FALSE(indexer->finalize(&error));
  EXPECT_NE(error.find("duplicate"), std::string::npos) << error;
}

TEST(DocnoContentsIndex, EmptyInputsRejected) {
  std::string error;
  std::string burrow = cottontail::DEFAULT_BURROW;
  auto working = cottontail::Working::mkdir(burrow, &error);
  ASSERT_NE(working, nullptr) << error;
  auto builder = cottontail::SimpleBuilder::make(working, "", &error);
  ASSERT_NE(builder, nullptr) << error;
  auto indexer = cottontail::DocnoContentsIndexer::make(builder, working, &error);
  ASSERT_NE(indexer, nullptr) << error;
  // Empty docno.
  EXPECT_FALSE(indexer->add_document("", "some contents", &error));
  // Empty contents.
  EXPECT_FALSE(indexer->add_document("d1", "", &error));
  // Whitespace/punctuation-only contents -> no indexable tokens.
  EXPECT_FALSE(indexer->add_document("d2", "   \t  ", &error));
}
