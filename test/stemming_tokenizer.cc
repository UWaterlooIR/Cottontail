#include "src/stemming_tokenizer.h"

#include <cstdlib>
#include <map>
#include <string>
#include <vector>

#include "gtest/gtest.h"

#include "src/core.h"
#include "src/featurizer.h"
#include "src/simple_builder.h"
#include "src/stemmer.h"
#include "src/tokenizer.h"
#include "src/warren.h"
#include "src/working.h"

namespace {

using namespace cottontail;

// ascii surface tokens + Porter stems, co-located.
const char *kRecipe = "[ tokenizer:[ name:\"ascii\", recipe:\"noxml\" ],"
                      "  stemmer:[ name:\"porter\", recipe:\"\" ], ]";

std::string scratch_dir(const std::string &name) {
  const char *base = std::getenv("TEST_TMPDIR");
  std::string root = base != nullptr ? std::string(base) : std::string("/tmp");
  return root + "/stemming_tokenizer_" + name;
}

// Count how many tokens in a tokenization landed at a given address.
size_t at_address(const std::vector<Token> &tokens, addr address) {
  size_t n = 0;
  for (const auto &t : tokens)
    if (t.address == address)
      ++n;
  return n;
}

bool has_feature(const std::vector<Token> &tokens, addr feature) {
  for (const auto &t : tokens)
    if (t.feature == feature)
      return true;
  return false;
}

} // namespace

// A word the stemmer changes gets two co-located features: the exact surface
// feature and the stem feature, both at the same address.
TEST(StemmingTokenizer, EmitsCoLocatedStem) {
  std::string error;
  auto featurizer = Featurizer::make("hashing", "", &error);
  ASSERT_NE(featurizer, nullptr) << error;
  auto tokenizer = Tokenizer::make("stemming", kRecipe, &error);
  ASSERT_NE(tokenizer, nullptr) << error;
  auto stemmer = Stemmer::make("porter", "", &error);
  ASSERT_NE(stemmer, nullptr) << error;

  auto tokens = tokenizer->tokenize(featurizer, std::string("running"));
  EXPECT_EQ(tokens.size(), 2u);
  EXPECT_EQ(at_address(tokens, 0), 2u);
  EXPECT_TRUE(has_feature(tokens, featurizer->featurize("running")));
  EXPECT_TRUE(has_feature(tokens, featurizer->featurize(stemmer->stem("running"))));
}

// When the stemmer reports it did nothing (too short, or non-letters present),
// no co-located stem feature is added -- the token stands alone.
TEST(StemmingTokenizer, SkipsNoOpStem) {
  std::string error;
  auto featurizer = Featurizer::make("hashing", "", &error);
  ASSERT_NE(featurizer, nullptr) << error;
  auto tokenizer = Tokenizer::make("stemming", kRecipe, &error);
  ASSERT_NE(tokenizer, nullptr) << error;

  // "ox" is below Porter's minimum length; "covid19" contains a digit.
  EXPECT_EQ(tokenizer->tokenize(featurizer, std::string("ox")).size(), 1u);
  EXPECT_EQ(tokenizer->tokenize(featurizer, std::string("covid19")).size(), 1u);
}

// The wrapped ascii tokenizer already emits two tokens at one address for a
// capitalized word (verbatim + lower-cased); both stem to the same feature, so
// the stem is added once, not twice.
TEST(StemmingTokenizer, DedupesCapitalizedPair) {
  std::string error;
  auto featurizer = Featurizer::make("hashing", "", &error);
  ASSERT_NE(featurizer, nullptr) << error;
  auto tokenizer = Tokenizer::make("stemming", kRecipe, &error);
  ASSERT_NE(tokenizer, nullptr) << error;

  auto tokens = tokenizer->tokenize(featurizer, std::string("RUNNING"));
  EXPECT_EQ(tokens.size(), 3u); // verbatim + lower-cased + one stem
  EXPECT_EQ(at_address(tokens, 0), 3u);
}

// The recipe round-trips: recipe() of a constructed tokenizer rebuilds an
// identical one, so a warren restored from a burrow's dna gets the same
// tokenizer back.
TEST(StemmingTokenizer, RecipeRoundTrips) {
  std::string error;
  auto tokenizer = Tokenizer::make("stemming", kRecipe, &error);
  ASSERT_NE(tokenizer, nullptr) << error;
  EXPECT_EQ(tokenizer->name(), "stemming");
  std::string recipe = tokenizer->recipe();
  EXPECT_TRUE(StemmingTokenizer::check(recipe, &error)) << error;
  auto rebuilt = Tokenizer::make("stemming", recipe, &error);
  ASSERT_NE(rebuilt, nullptr) << error;
  EXPECT_EQ(rebuilt->recipe(), recipe);
}

// A bad recipe is reported, not crashed on.
TEST(StemmingTokenizer, RejectsBadRecipe) {
  std::string error;
  EXPECT_FALSE(StemmingTokenizer::check("[ stemmer:[ name:\"porter\" ] ]",
                                        &error)); // missing tokenizer
  EXPECT_EQ(Tokenizer::make("stemming",
                            "[ tokenizer:[ name:\"nosuch\", recipe:\"\" ],"
                            "  stemmer:[ name:\"porter\", recipe:\"\" ], ]",
                            &error),
            nullptr); // unknown wrapped tokenizer
}

// End to end through a real burrow: a stemmed query matches a morphological
// variant, while the exact stream keeps the surface forms distinct.
TEST(StemmingTokenizer, StemStreamMatchesVariantExactDoesNot) {
  std::string error;
  std::string dir = scratch_dir("burrow");
  auto working = Working::mkdir(dir, &error);
  ASSERT_NE(working, nullptr) << error;
  auto featurizer = Featurizer::make("hashing", "", &error, working);
  ASSERT_NE(featurizer, nullptr) << error;
  auto tokenizer = Tokenizer::make("stemming", kRecipe, &error);
  ASSERT_NE(tokenizer, nullptr) << error;
  auto builder = SimpleBuilder::make(working, featurizer, tokenizer, &error);
  ASSERT_NE(builder, nullptr) << error;
  addr p, q;
  ASSERT_TRUE(builder->add_text("the dogs barked loudly", &p, &q, &error))
      << error;
  ASSERT_TRUE(builder->add_annotation(":item", p, q, 0.0, &error)) << error;
  ASSERT_TRUE(builder->finalize(&error)) << error;

  auto warren = Warren::make("simple", dir, &error);
  ASSERT_NE(warren, nullptr) << error;
  warren->start();
  auto fz = warren->featurizer();
  auto idx = warren->idx();
  auto stemmer = Stemmer::make("porter", "", &error);
  ASSERT_NE(stemmer, nullptr) << error;

  // Exact stream: the surface "dogs" is present; "dog" never appeared, so the
  // exact feature for "dog" has no postings (no over-stemming leak).
  EXPECT_GT(idx->count(fz->featurize("dogs")), 0);
  EXPECT_EQ(idx->count(fz->featurize("dog")), 0);

  // Stem stream: "dog" and "dogs" share a stem feature, and it has postings --
  // so a --stem query for "dog" would find this row.
  EXPECT_EQ(fz->featurize(stemmer->stem("dog")),
            fz->featurize(stemmer->stem("dogs")));
  EXPECT_GT(idx->count(fz->featurize(stemmer->stem("dog"))), 0);

  warren->end();
}
