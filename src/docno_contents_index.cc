#include "src/docno_contents_index.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <memory>
#include <numeric>
#include <string>
#include <vector>

#include "src/compressor.h"
#include "src/core.h"

namespace cottontail {

namespace {

// The sidecar's resident addr[] arrays (cp[], offset[]) are stored with the
// "post" compressor, mirroring FastidTxt; the docno text blob and the reverse
// permutation are stored UNCOMPRESSED so a single entry can be read by random
// access without decompressing the whole file (the "read lazily" requirement).
// FastidTxt's equivalents live in an anonymous namespace, so these are small
// local copies rather than a refactor of src/fastid_txt.cc.
std::shared_ptr<Compressor> post_compressor(std::string *error) {
  std::string name = "post";
  std::string recipe = "";
  return Compressor::make(name, recipe, error);
}

// Append a length-prefixed, post-compressed block of `n` bytes from `buffer`.
bool compressed_write(std::fstream *out, char *buffer, size_t n,
                      std::shared_ptr<Compressor> compressor,
                      std::string *error) {
  size_t available = n + compressor->extra(n);
  std::unique_ptr<char[]> compressed =
      std::unique_ptr<char[]>(new char[available + 1]);
  size_t m = compressor->crush(buffer, n, compressed.get(), available);
  out->write(reinterpret_cast<char *>(&m), sizeof(size_t));
  out->write(compressed.get(), m);
  if (out->fail()) {
    safe_error(error) = "DocnoContentsIndexer: sidecar write failure";
    return false;
  }
  return true;
}

// Read a length-prefixed, post-compressed addr[] block of `count` entries from
// `*b` (advancing `*b`) into `dest`.
void compressed_read(char **b, addr *dest, size_t count,
                     std::shared_ptr<Compressor> compressor) {
  size_t k = *(reinterpret_cast<size_t *>(*b));
  *b += sizeof(size_t);
  compressor->tang(*b, k, reinterpret_cast<char *>(dest), count * sizeof(addr));
  *b += k;
}

} // namespace

std::shared_ptr<DocnoContentsIndexer>
DocnoContentsIndexer::make(std::shared_ptr<Builder> builder,
                           std::shared_ptr<Working> working,
                           std::string *error) {
  if (builder == nullptr || working == nullptr) {
    safe_error(error) = "DocnoContentsIndexer::make: null builder or working";
    return nullptr;
  }
  std::shared_ptr<DocnoContentsIndexer> indexer =
      std::shared_ptr<DocnoContentsIndexer>(new DocnoContentsIndexer());
  indexer->builder_ = builder;
  indexer->working_ = working;
  return indexer;
}

bool DocnoContentsIndexer::add_document(const std::string &docno,
                                        const std::string &contents,
                                        std::string *error) {
  if (finalized_) {
    safe_error(error) = "DocnoContentsIndexer: add_document after finalize";
    return false;
  }
  if (docno.empty()) {
    safe_error(error) = "DocnoContentsIndexer: empty docno";
    return false;
  }
  if (contents.empty()) {
    safe_error(error) = "DocnoContentsIndexer: empty contents for docno " + docno;
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
    safe_error(error) =
        "DocnoContentsIndexer: docno " + docno + " has no indexable tokens";
    return false;
  }
  if (!builder_->add_annotation(":item", p_body, q_body, 0.0, error))
    return false;
  entries_.emplace_back(p_body, docno);
  last_cq_ = q_body;
  return true;
}

bool DocnoContentsIndexer::finalize(std::string *error) {
  if (finalized_)
    return true;
  finalized_ = true;
  if (!builder_->finalize(error))
    return false;

  size_t m = entries_.size();
  if (m > 0xffffffffUL) {
    safe_error(error) =
        "DocnoContentsIndexer: too many documents for a 32-bit permutation";
    return false;
  }

  std::shared_ptr<Compressor> compressor = post_compressor(error);
  if (compressor == nullptr)
    return false;

  // cp[] (doc order, strictly increasing by construction) and offset[] into the
  // docno text blob; write the uncompressed docno blob as we accumulate offsets.
  std::unique_ptr<addr[]> cp(new addr[m]);
  std::unique_ptr<addr[]> offset(new addr[m]);
  std::string docno_name = working_->make_name(DOCNO_SIDECAR_NAME + ".docno");
  std::remove(docno_name.c_str());
  std::fstream docno_out(docno_name, std::ios::binary | std::ios::out);
  if (docno_out.fail()) {
    safe_error(error) = "DocnoContentsIndexer: cannot create " + docno_name;
    return false;
  }
  addr n = 0;
  for (size_t i = 0; i < m; i++) {
    cp[i] = entries_[i].first;
    offset[i] = n;
    const std::string &d = entries_[i].second;
    docno_out.write(d.data(), d.size());
    n += d.size();
  }
  docno_out.close();
  if (docno_out.fail()) {
    safe_error(error) = "DocnoContentsIndexer: sidecar docno write failure";
    return false;
  }

  // Reverse-order permutation, sorted by docno string. Sorting it is also the
  // uniqueness check: adjacent equal docnos in the sorted order are duplicates.
  std::vector<uint32_t> perm(m);
  std::iota(perm.begin(), perm.end(), 0u);
  std::sort(perm.begin(), perm.end(), [&](uint32_t a, uint32_t b) {
    return entries_[a].second < entries_[b].second;
  });
  for (size_t r = 1; r < m; r++)
    if (entries_[perm[r]].second == entries_[perm[r - 1]].second) {
      safe_error(error) =
          "DocnoContentsIndexer: duplicate docno " + entries_[perm[r]].second;
      return false;
    }
  std::string perm_name = working_->make_name(DOCNO_SIDECAR_NAME + ".perm");
  std::remove(perm_name.c_str());
  std::fstream perm_out(perm_name, std::ios::binary | std::ios::out);
  if (perm_out.fail()) {
    safe_error(error) = "DocnoContentsIndexer: cannot create " + perm_name;
    return false;
  }
  if (m > 0)
    perm_out.write(reinterpret_cast<char *>(perm.data()),
                   perm.size() * sizeof(uint32_t));
  perm_out.close();
  if (perm_out.fail()) {
    safe_error(error) = "DocnoContentsIndexer: sidecar perm write failure";
    return false;
  }

  // Index file: header (m, n, last_cq, perm_width) + compressed cp[] + offset[].
  std::string index_name = working_->make_name(DOCNO_SIDECAR_NAME + ".index");
  std::remove(index_name.c_str());
  std::fstream out(index_name, std::ios::binary | std::ios::out);
  if (out.fail()) {
    safe_error(error) = "DocnoContentsIndexer: cannot create " + index_name;
    return false;
  }
  size_t total = static_cast<size_t>(n);
  size_t perm_width = sizeof(uint32_t);
  out.write(reinterpret_cast<char *>(&m), sizeof(size_t));
  out.write(reinterpret_cast<char *>(&total), sizeof(size_t));
  out.write(reinterpret_cast<char *>(&last_cq_), sizeof(addr));
  out.write(reinterpret_cast<char *>(&perm_width), sizeof(size_t));
  if (out.fail()) {
    safe_error(error) = "DocnoContentsIndexer: sidecar index write failure";
    return false;
  }
  if (!compressed_write(&out, reinterpret_cast<char *>(cp.get()),
                        m * sizeof(addr), compressor, error))
    return false;
  if (!compressed_write(&out, reinterpret_cast<char *>(offset.get()),
                        m * sizeof(addr), compressor, error))
    return false;
  out.close();
  if (out.fail()) {
    safe_error(error) = "DocnoContentsIndexer: sidecar index write failure";
    return false;
  }
  return true;
}

std::shared_ptr<DocnoContentsSidecar>
DocnoContentsSidecar::open(std::shared_ptr<Working> working,
                           std::string *error) {
  if (working == nullptr) {
    safe_error(error) = "DocnoContentsSidecar::open: null working";
    return nullptr;
  }
  std::shared_ptr<Reader> index_reader =
      working->reader(DOCNO_SIDECAR_NAME + ".index", error);
  if (index_reader == nullptr) {
    safe_error(error) = "DocnoContentsSidecar::open: no sidecar in burrow";
    return nullptr;
  }
  std::shared_ptr<Compressor> compressor = post_compressor(error);
  if (compressor == nullptr)
    return nullptr;

  size_t size = index_reader->size();
  std::unique_ptr<char[]> buffer(new char[size]);
  index_reader->read(buffer.get(), 0, size);
  char *b = buffer.get();
  size_t m = *(reinterpret_cast<size_t *>(b));
  b += sizeof(size_t);
  size_t n = *(reinterpret_cast<size_t *>(b));
  b += sizeof(size_t);
  addr last_cq = *(reinterpret_cast<addr *>(b));
  b += sizeof(addr);
  size_t perm_width = *(reinterpret_cast<size_t *>(b));
  b += sizeof(size_t);

  std::unique_ptr<addr[]> cp(new addr[m]);
  std::unique_ptr<addr[]> offset(new addr[m + 1]);
  compressed_read(&b, cp.get(), m, compressor);
  compressed_read(&b, offset.get(), m, compressor);
  offset[m] = static_cast<addr>(n);

  std::shared_ptr<DocnoContentsSidecar> sidecar =
      std::shared_ptr<DocnoContentsSidecar>(new DocnoContentsSidecar());
  sidecar->m_ = m;
  sidecar->n_ = n;
  sidecar->last_cq_ = last_cq;
  sidecar->perm_width_ = perm_width;
  sidecar->cp_ = std::move(cp);
  sidecar->offset_ = std::move(offset);
  if (m > 0) {
    sidecar->docno_reader_ =
        working->reader(DOCNO_SIDECAR_NAME + ".docno", error);
    sidecar->perm_reader_ =
        working->reader(DOCNO_SIDECAR_NAME + ".perm", error);
    if (sidecar->docno_reader_ == nullptr || sidecar->perm_reader_ == nullptr) {
      safe_error(error) = "DocnoContentsSidecar::open: incomplete sidecar";
      return nullptr;
    }
  }
  return sidecar;
}

addr DocnoContentsSidecar::find_cp(addr value) {
  addr lo = 0, hi = static_cast<addr>(m_) - 1;
  while (lo <= hi) {
    addr mid = lo + (hi - lo) / 2;
    if (cp_[mid] == value)
      return mid;
    else if (cp_[mid] < value)
      lo = mid + 1;
    else
      hi = mid - 1;
  }
  return -1;
}

std::string DocnoContentsSidecar::docno_at(addr i) {
  addr start = offset_[i];
  addr length = offset_[i + 1] - start;
  std::string docno;
  if (length > 0) {
    docno.resize(static_cast<size_t>(length));
    docno_reader_->read(&docno[0], static_cast<size_t>(start),
                        static_cast<size_t>(length));
  }
  return docno;
}

bool DocnoContentsSidecar::docno_of(addr cp, std::string *docno) {
  addr i = find_cp(cp);
  if (i < 0)
    return false;
  if (docno != nullptr)
    *docno = docno_at(i);
  return true;
}

bool DocnoContentsSidecar::span_of(addr cp, addr *p, addr *q) {
  addr i = find_cp(cp);
  if (i < 0)
    return false;
  if (p != nullptr)
    *p = cp;
  if (q != nullptr)
    *q = (static_cast<size_t>(i) + 1 < m_) ? cp_[i + 1] - 1 : last_cq_;
  return true;
}

bool DocnoContentsSidecar::cp_of(const std::string &docno, addr *cp) {
  addr lo = 0, hi = static_cast<addr>(m_) - 1;
  while (lo <= hi) {
    addr r = lo + (hi - lo) / 2;
    uint32_t j = 0;
    perm_reader_->read(reinterpret_cast<char *>(&j),
                       static_cast<size_t>(r) * perm_width_, perm_width_);
    std::string candidate = docno_at(static_cast<addr>(j));
    int c = docno.compare(candidate);
    if (c == 0) {
      if (cp != nullptr)
        *cp = cp_[j];
      return true;
    } else if (c > 0) {
      lo = r + 1;
    } else {
      hi = r - 1;
    }
  }
  return false;
}

bool DocnoContentsSidecar::text_by_cp(std::shared_ptr<Warren> warren, addr cp,
                                      std::string *text, bool *found,
                                      std::string *error) {
  addr p, q;
  if (!span_of(cp, &p, &q)) {
    if (found != nullptr)
      *found = false;
    return true;
  }
  if (text != nullptr)
    *text = warren->txt()->translate(p, q);
  if (found != nullptr)
    *found = true;
  return true;
}

bool DocnoContentsSidecar::text_by_docno(std::shared_ptr<Warren> warren,
                                         const std::string &docno,
                                         std::string *text, bool *found,
                                         std::string *error) {
  addr cp;
  if (!cp_of(docno, &cp)) {
    if (found != nullptr)
      *found = false;
    return true;
  }
  return text_by_cp(warren, cp, text, found, error);
}

} // namespace cottontail
