#ifndef COTTONTAIL_SRC_STEMMING_TOKENIZER_H_
#define COTTONTAIL_SRC_STEMMING_TOKENIZER_H_

#include <memory>
#include <string>
#include <vector>

#include "src/core.h"
#include "src/stemmer.h"
#include "src/tokenizer.h"

namespace cottontail {

// A general tokenizer decorator: it wraps another tokenizer together with a
// stemmer.  For every token the wrapped tokenizer emits, StemmingTokenizer also
// emits a co-located feature -- same address, offset, and length -- for the
// stemmed surface form, but only when the stemmer reports (via its bool out
// parameter) that it actually changed the word.  Exact and stemmed features
// therefore share token addresses, so GCL operators, containment, best-passage
// spans, and identifier recovery behave identically whether a match lands on an
// exact or a stemmed feature.  A query selects which stream to hit simply by how
// it featurizes its terms (the bare surface form vs. the stemmer's output).
//
// Only tokenize is specialized; skip and split delegate to the wrapped
// tokenizer (stems add no new addresses, and split returns surface terms for the
// default exact query path).
//
// The recipe is the usual nested name/recipe structure, e.g.:
//   [ tokenizer:[ name:"ascii",  recipe:"noxml" ],
//     stemmer:[   name:"porter", recipe:"" ] ]
// It round-trips through recipe(), so a warren rebuilt from a burrow's dna
// reconstructs an identical tokenizer.

class StemmingTokenizer final : public Tokenizer {
public:
  static std::shared_ptr<Tokenizer> make(const std::string &recipe,
                                         std::string *error = nullptr);
  static std::shared_ptr<Tokenizer> make(std::shared_ptr<Tokenizer> wrapped,
                                         std::shared_ptr<Stemmer> stemmer,
                                         std::string *error = nullptr);
  static bool check(const std::string &recipe, std::string *error = nullptr);

  virtual ~StemmingTokenizer(){};
  StemmingTokenizer(const StemmingTokenizer &) = delete;
  StemmingTokenizer &operator=(const StemmingTokenizer &) = delete;
  StemmingTokenizer(StemmingTokenizer &&) = delete;
  StemmingTokenizer &operator=(StemmingTokenizer &&) = delete;

private:
  StemmingTokenizer(){};
  std::shared_ptr<Tokenizer> wrapped_;
  std::shared_ptr<Stemmer> stemmer_;
  std::string recipe_() final;
  std::vector<Token> tokenize_(std::shared_ptr<Featurizer> featurizer,
                               char *buffer, size_t length) final;
  const char *skip_(const char *buffer, size_t length, addr n) final;
  std::vector<std::string> split_(const std::string &text) final;
  bool destructive_() final;
};

} // namespace cottontail

#endif // COTTONTAIL_SRC_STEMMING_TOKENIZER_H_
