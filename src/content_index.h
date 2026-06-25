#ifndef COTTONTAIL_SRC_CONTENT_INDEX_H_
#define COTTONTAIL_SRC_CONTENT_INDEX_H_

// Generic cp-native indexing of a document collection into a static warren, per
// docs/indexing.md (decision doc-6, which supersedes doc-4). Each document is
// just text contents; the indexer drives a Builder to store ONLY the contents
// plus one ":item" annotation spanning the body. It does NOT tokenize or store
// any docno and creates NO ":docno" annotation.
//
// The document's unique internal id is the ":item" start address, called cp --
// assigned by the address space at build time, the same value ssr_ranking
// returns as container_p(). cp is the working identity on the wire, in the
// engine, and in the live agent loop (doc-6). The optional docno lives only at a
// boundary, in a cp<->docno SQLite map the caller builds from the (docno, cp)
// pairs (TASK-6.2 dumps them; TASK-6.3 builds the map); it is NOT this module's
// concern.
//
// This module depends only on the Cottontail core (no apps/JSONL coupling) and
// does not touch the query path.

#include <memory>
#include <string>

#include "src/builder.h"
#include "src/core.h"

namespace cottontail {

// Drives a Builder to index a document collection cp-native. The caller supplies
// the Builder (so it keeps control of the tokenizer/stemmer/buffer choices);
// this class adds the contents + ":item" document layout and hands back each
// document's cp.
class ContentIndexer {
public:
  static std::shared_ptr<ContentIndexer> make(std::shared_ptr<Builder> builder,
                                               std::string *error = nullptr);

  // Index one document: add_text(contents) + one ":item" annotation spanning the
  // body. On success sets *cp -- the ":item" start address, the document's
  // unique internal id -- and returns true.
  //
  // HARD ERROR (returns false, sets *error, leaves *cp untouched) on empty
  // contents, or contents that yield no indexable tokens: an empty body occupies
  // no address range, so its cp would collide with the next document's and break
  // the unique-id invariant.
  bool add_document(const std::string &contents, addr *cp,
                    std::string *error = nullptr);

  // Finalize the underlying builder. cp-native indexing writes no sidecar/map.
  bool finalize(std::string *error = nullptr);

  virtual ~ContentIndexer(){};
  ContentIndexer(const ContentIndexer &) = delete;
  ContentIndexer &operator=(const ContentIndexer &) = delete;
  ContentIndexer(ContentIndexer &&) = delete;
  ContentIndexer &operator=(ContentIndexer &&) = delete;

private:
  ContentIndexer(){};
  std::shared_ptr<Builder> builder_;
  bool finalized_ = false;
};

} // namespace cottontail
#endif // COTTONTAIL_SRC_CONTENT_INDEX_H_
