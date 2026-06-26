#include "src/content_index.h"

#include <memory>
#include <string>

#include "src/core.h"

namespace cottontail {

std::shared_ptr<ContentIndexer>
ContentIndexer::make(std::shared_ptr<Builder> builder, std::string *error) {
  if (builder == nullptr) {
    safe_error(error) = "ContentIndexer::make: null builder";
    return nullptr;
  }
  std::shared_ptr<ContentIndexer> indexer =
      std::shared_ptr<ContentIndexer>(new ContentIndexer());
  indexer->builder_ = builder;
  return indexer;
}

bool ContentIndexer::add_document(const std::string &contents, addr *cp,
                                  std::string *error) {
  if (finalized_) {
    safe_error(error) = "ContentIndexer: add_document after finalize";
    return false;
  }
  if (contents.empty()) {
    safe_error(error) = "ContentIndexer: empty contents";
    return false;
  }
  addr p_body, q_body;
  if (!builder_->add_text(contents, &p_body, &q_body, error))
    return false;
  // add_text returns an empty span (q < p) -- and does not advance the address
  // -- when the text yields no tokens (e.g. whitespace/punctuation only). Such a
  // document occupies no address range, so its cp would collide with the next
  // document's. Reject it.
  if (q_body < p_body) {
    safe_error(error) = "ContentIndexer: contents have no indexable tokens";
    return false;
  }
  if (!builder_->add_annotation(":item", p_body, q_body, 0.0, error))
    return false;
  if (cp != nullptr)
    *cp = p_body;
  return true;
}

bool ContentIndexer::finalize(std::string *error) {
  if (finalized_)
    return true;
  finalized_ = true;
  return builder_->finalize(error);
}

} // namespace cottontail
