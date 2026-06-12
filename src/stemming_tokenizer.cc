#include "src/stemming_tokenizer.h"

#include <map>
#include <memory>
#include <string>
#include <vector>

#include "src/core.h"
#include "src/featurizer.h"
#include "src/recipe.h"
#include "src/stemmer.h"
#include "src/tokenizer.h"

namespace cottontail {

namespace {
// Parse the nested name/recipe recipe into a wrapped tokenizer and a stemmer.
bool parse_recipe(const std::string &recipe, std::string *tokenizer_name,
                  std::string *tokenizer_recipe, std::string *stemmer_name,
                  std::string *stemmer_recipe, std::string *error) {
  std::map<std::string, std::string> parameters;
  if (!cook(recipe, &parameters, error))
    return false;
  if (!name_and_recipe(parameters, "tokenizer", tokenizer_name,
                       tokenizer_recipe, error))
    return false;
  if (!name_and_recipe(parameters, "stemmer", stemmer_name, stemmer_recipe,
                       error))
    return false;
  return true;
}
} // namespace

std::shared_ptr<Tokenizer> StemmingTokenizer::make(const std::string &recipe,
                                                   std::string *error) {
  std::string tokenizer_name, tokenizer_recipe, stemmer_name, stemmer_recipe;
  if (!parse_recipe(recipe, &tokenizer_name, &tokenizer_recipe, &stemmer_name,
                    &stemmer_recipe, error))
    return nullptr;
  std::shared_ptr<Tokenizer> wrapped =
      Tokenizer::make(tokenizer_name, tokenizer_recipe, error);
  if (wrapped == nullptr)
    return nullptr;
  std::shared_ptr<Stemmer> stemmer =
      Stemmer::make(stemmer_name, stemmer_recipe, error);
  if (stemmer == nullptr)
    return nullptr;
  return make(wrapped, stemmer, error);
}

std::shared_ptr<Tokenizer>
StemmingTokenizer::make(std::shared_ptr<Tokenizer> wrapped,
                        std::shared_ptr<Stemmer> stemmer, std::string *error) {
  if (wrapped == nullptr) {
    safe_error(error) = "StemmingTokenizer requires a wrapped tokenizer";
    return nullptr;
  }
  if (stemmer == nullptr) {
    safe_error(error) = "StemmingTokenizer requires a stemmer";
    return nullptr;
  }
  std::shared_ptr<StemmingTokenizer> tokenizer =
      std::shared_ptr<StemmingTokenizer>(new StemmingTokenizer());
  tokenizer->wrapped_ = wrapped;
  tokenizer->stemmer_ = stemmer;
  return tokenizer;
}

bool StemmingTokenizer::check(const std::string &recipe, std::string *error) {
  std::string tokenizer_name, tokenizer_recipe, stemmer_name, stemmer_recipe;
  if (!parse_recipe(recipe, &tokenizer_name, &tokenizer_recipe, &stemmer_name,
                    &stemmer_recipe, error))
    return false;
  if (!Tokenizer::check(tokenizer_name, tokenizer_recipe, error))
    return false;
  if (!Stemmer::check(stemmer_name, stemmer_recipe, error))
    return false;
  return true;
}

std::string StemmingTokenizer::recipe_() {
  std::map<std::string, std::string> tokenizer_parameters;
  tokenizer_parameters["name"] = wrapped_->name();
  tokenizer_parameters["recipe"] = wrapped_->recipe();
  std::map<std::string, std::string> stemmer_parameters;
  stemmer_parameters["name"] = stemmer_->name();
  stemmer_parameters["recipe"] = stemmer_->recipe();
  std::map<std::string, std::string> parameters;
  parameters["tokenizer"] = freeze(tokenizer_parameters);
  parameters["stemmer"] = freeze(stemmer_parameters);
  return freeze(parameters);
}

std::vector<Token>
StemmingTokenizer::tokenize_(std::shared_ptr<Featurizer> featurizer,
                             char *buffer, size_t length) {
  // The wrapped tokenizer produces the exact stream (and may already emit more
  // than one token at a single address, e.g. ascii's verbatim + lower-cased
  // pair for words containing capitals).  We pass those through unchanged and,
  // for each, add a co-located stemmed feature when the stemmer actually
  // stemmed the surface form.
  std::vector<Token> tokens = wrapped_->tokenize(featurizer, buffer, length);
  std::vector<Token> result;
  result.reserve(2 * tokens.size());
  addr last_stem_feature = null_feature;
  addr last_stem_address = -1;
  for (const auto &token : tokens) {
    result.push_back(token);
    if (token.feature == null_feature)
      continue;
    std::string surface(buffer + token.offset, token.length);
    bool stemmed = false;
    std::string stem = stemmer_->stem(surface, &stemmed);
    if (!stemmed)
      continue;
    addr feature = featurizer->featurize(stem);
    // Skip a duplicate co-located stem (two exact tokens at the same address can
    // stem to the same feature -- again, ascii's capitalized-word pair).
    if (feature == last_stem_feature && token.address == last_stem_address)
      continue;
    result.emplace_back(feature, token.address, token.offset, token.length);
    last_stem_feature = feature;
    last_stem_address = token.address;
  }
  return result;
}

const char *StemmingTokenizer::skip_(const char *buffer, size_t length,
                                     addr n) {
  return wrapped_->skip(buffer, length, n);
}

std::vector<std::string> StemmingTokenizer::split_(const std::string &text) {
  return wrapped_->split(text);
}

bool StemmingTokenizer::destructive_() { return wrapped_->destructive(); }

} // namespace cottontail
