#ifndef COTTONTAIL_SRC_DOCNO_CONTENTS_INDEX_H_
#define COTTONTAIL_SRC_DOCNO_CONTENTS_INDEX_H_

// Generic indexing of a TREC-like document collection -- each document is a
// unique string identifier (the docno) plus text contents -- into a static
// warren, per docs/indexing.md (decision doc-4).
//
// The indexer drives a Builder to store ONLY the contents plus one ":item"
// annotation per document; it does NOT tokenize the docno and creates NO
// ":docno" annotation. The document's unique internal id is the ":item" start
// address (cp), assigned by the address space at build time -- the same value
// ssr_ranking returns as container_p(). The docno lives only in a cp<->docno
// "sidecar" we build from the supplied docno strings.
//
// This module depends only on the Cottontail core (no apps/JSONL coupling) and
// does not touch the query path.

#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "src/builder.h"
#include "src/core.h"
#include "src/warren.h"
#include "src/working.h"

namespace cottontail {

// Base filename of the sidecar files written into a burrow's working directory.
// Three files: <BASE>.index (header + resident cp[]/offset[] arrays),
// <BASE>.docno (concatenated docno text, read lazily) and <BASE>.perm (the
// docno-sorted permutation for the reverse docno->cp lookup, read lazily).
const std::string DOCNO_SIDECAR_NAME = "sidecar";

// Drives a Builder to index a TREC-like collection and, at finalize(), writes
// the cp<->docno sidecar. The caller supplies the Builder and Working (so it
// keeps control of the tokenizer/stemmer/buffer choices); this class adds the
// new-model document layout plus the sidecar.
class DocnoContentsIndexer {
public:
  static std::shared_ptr<DocnoContentsIndexer>
  make(std::shared_ptr<Builder> builder, std::shared_ptr<Working> working,
       std::string *error = nullptr);

  // Index one document: add_text(contents) + one ":item" annotation spanning the
  // body, and record (cp, docno) for the sidecar. cp -- the ":item" start
  // address -- is the document's unique internal id.
  //
  // HARD ERROR (returns false, sets *error) on: an empty docno; empty contents;
  // or contents that yield no indexable tokens (an empty body occupies no
  // address range, so its cp would collide with the next document's and break
  // the unique-id invariant).
  bool add_document(const std::string &docno, const std::string &contents,
                    std::string *error = nullptr);

  // Finalize the underlying builder, then write the sidecar (always). Validates
  // docno uniqueness: a duplicate docno is a hard error.
  bool finalize(std::string *error = nullptr);

  virtual ~DocnoContentsIndexer(){};
  DocnoContentsIndexer(const DocnoContentsIndexer &) = delete;
  DocnoContentsIndexer &operator=(const DocnoContentsIndexer &) = delete;
  DocnoContentsIndexer(DocnoContentsIndexer &&) = delete;
  DocnoContentsIndexer &operator=(DocnoContentsIndexer &&) = delete;

private:
  DocnoContentsIndexer(){};
  std::shared_ptr<Builder> builder_;
  std::shared_ptr<Working> working_;
  std::vector<std::pair<addr, std::string>> entries_; // (cp, docno), doc order
  addr last_cq_ = -1;                                  // cq of the last document
  bool finalized_ = false;
};

// Reader over a burrow's cp<->docno sidecar. Loads the cp[] and offset[] arrays
// resident (binary-searched); reads docno text and the reverse-order
// permutation lazily from disk (sized for ~500M documents).
class DocnoContentsSidecar {
public:
  static std::shared_ptr<DocnoContentsSidecar>
  open(std::shared_ptr<Working> working, std::string *error = nullptr);

  // cp -> docno. Returns true and sets *docno when cp is a document start;
  // returns false (not an error) for an unknown cp.
  bool docno_of(addr cp, std::string *docno);

  // cp -> (cp, cq). cq is derived: cq_i = cp_{i+1} - 1, with the final cq stored
  // once. Returns false (not an error) for an unknown cp.
  bool span_of(addr cp, addr *p, addr *q);

  // docno -> cp, via a binary search over the disk-resident docno-sorted
  // permutation (no full load). Returns false (not an error) for an unknown
  // docno.
  bool cp_of(const std::string &docno, addr *cp);

  // Fetch the document body via warren->txt()->translate. *found is false (not
  // an error) for an unknown cp/docno. Returns false only on a hard error.
  bool text_by_cp(std::shared_ptr<Warren> warren, addr cp, std::string *text,
                  bool *found, std::string *error = nullptr);
  bool text_by_docno(std::shared_ptr<Warren> warren, const std::string &docno,
                     std::string *text, bool *found,
                     std::string *error = nullptr);

  virtual ~DocnoContentsSidecar(){};
  DocnoContentsSidecar(const DocnoContentsSidecar &) = delete;
  DocnoContentsSidecar &operator=(const DocnoContentsSidecar &) = delete;
  DocnoContentsSidecar(DocnoContentsSidecar &&) = delete;
  DocnoContentsSidecar &operator=(DocnoContentsSidecar &&) = delete;

private:
  DocnoContentsSidecar(){};
  // Index in [0, m_) of the document whose cp == value, or -1 if none.
  addr find_cp(addr value);
  // Read the docno text of document index i (0-based, doc order) from disk.
  std::string docno_at(addr i);

  size_t m_ = 0;       // number of documents
  size_t n_ = 0;       // total docno text bytes
  addr last_cq_ = -1;  // cq of the last document
  size_t perm_width_ = sizeof(uint32_t);
  std::unique_ptr<addr[]> cp_;     // m_ entries, sorted ascending (resident)
  std::unique_ptr<addr[]> offset_; // m_+1 entries, offset_[m_] == n_ (resident)
  std::shared_ptr<Reader> docno_reader_; // <BASE>.docno (lazy)
  std::shared_ptr<Reader> perm_reader_;  // <BASE>.perm  (lazy)
};

} // namespace cottontail
#endif // COTTONTAIL_SRC_DOCNO_CONTENTS_INDEX_H_
