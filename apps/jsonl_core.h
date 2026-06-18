#ifndef COTTONTAIL_APPS_JSONL_CORE_H_
#define COTTONTAIL_APPS_JSONL_CORE_H_

// Shared logic for the cottontail-jsonl-index / cottontail-jsonl-query CLIs.
// The CLIs are thin argv/JSON wrappers over these functions so the behavior is
// unit-testable without spawning processes (see docs/cottontail-jsonl-cli-spec.md
// §11). The index is a static, disk-based SimpleWarren with one document per JSON
// row: a ":item" annotation spans the whole row, ":docno" marks the identifier.
// Retrieval is cover-density / proximity ranking with no precomputed statistics.

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "src/cottontail.h"

namespace cottontail {
namespace jsonl {

struct IndexOptions {
  std::string input;                  // root directory to recurse
  std::string burrow;                 // output burrow path
  std::string docid_field = "docid";
  std::string contents_field = "contents";
  size_t buffer = 256UL * 1024 * 1024; // builder token/annotation buffer (records)
  bool overwrite = false;
  long limit = -1;                    // -1 = unlimited
  bool strict = false;                // turn skips into fatal errors
  bool verbose = false;
  std::string tokenizer = "utf8";     // token model: "utf8" (Unicode) | "ascii"
  std::string stemmer = "";           // "" = none; "porter" = add a stemmed stream
};

struct IndexSummary {
  std::string burrow;
  size_t files_seen = 0;
  size_t rows_indexed = 0;
  size_t rows_skipped = 0;
  double elapsed_seconds = 0.0;
  uintmax_t burrow_bytes = 0;
  std::string tokenizer = ""; // token model baked into the index
  std::string stemmer = "";   // stemmer baked into the index ("" = none)
};

// Recursively index every *.jsonl / *.jsonl.gz under opts.input into a static
// SimpleWarren burrow. Returns false (with *error) on a fatal error.
bool jsonl_index(const IndexOptions &opts, IndexSummary *summary,
                 std::string *error = nullptr);

// Open the burrow read-only, started, with default container ":item".
std::shared_ptr<Warren> open_burrow(const std::string &burrow,
                                    std::string *error = nullptr);

struct Passage {
  addr start = 0;
  addr end = 0;
  std::string text;
};

struct Hit {
  int rank = 0;
  double score = 0.0;
  std::string docid;
  Passage best_passage;
  bool has_full_text = false;
  std::string full_text;
};

struct QuerySpec {
  bool is_gcl = false;
  std::string query;            // words (text mode) or a GCL expression (gcl mode)
  std::string ranker = "icover"; // text mode: icover | ssr | tiered
  size_t top_k = 10;
  bool full_text = false;
  size_t snippet_chars = 240;
  bool stem = false;             // match against the stemmed stream (opt-in)
};

// Rank a query against a started burrow (from open_burrow). Returns false (with
// *error) only on a hard failure, including a malformed --gcl expression.
bool jsonl_query(std::shared_ptr<Warren> warren, const QuerySpec &spec,
                 std::vector<Hit> *hits, std::string *error = nullptr);

// ---- cover_search: the ISJ agent's search tool (TASK-5.1 / A1) ------------
// A NEW tool, separate from jsonl_query / search_gcl. It understands the `word*`
// family marker (a full word + a trailing '*' -> the word AND its morphological
// family) and returns, per ranked document, a cover-biased extractive summary
// built from the query's covers within that document. search_gcl stays a pure
// GCL primitive and is unaffected by any of this.
struct CoverSpec {
  std::string query;  // a GCL cover query that MAY use the word* family marker
  size_t top_k = 10;
  // A2 extends this with exclude_docids and a request-side `window` override.
};

struct CoverHit {
  int rank = 0;        // 1-based position within this response
  double score = 0.0;  // ssr cover-density score (sum over covers of 1/(K+q-p))
  std::string docid;
  std::string summary; // cover-biased extractive summary (replaces best_passage)
};

// Rank a cover query by ssr cover density within :item and return, per returned
// document, a cover-biased extractive summary. `word*` atoms resolve to the
// burrow's stemmed stream (parity with the index's own Porter). Returns false
// (with *error) on a hard failure: malformed GCL, a non-trailing '*' in a term,
// or a word* query against a burrow with no stemmed stream (no silent fallback
// to exact).
bool jsonl_cover_search(std::shared_ptr<Warren> warren, const CoverSpec &spec,
                        std::vector<CoverHit> *hits,
                        std::string *error = nullptr);

// Fetch the full body of the row whose :docno equals `docid`. Sets *found=false
// (not an error) when no such row exists. Returns false only on a hard error.
bool jsonl_get(std::shared_ptr<Warren> warren, const std::string &docid,
               std::string *text, bool *found, std::string *error = nullptr);

// Count the :item rows that match `spec` (AND of the terms for text mode, the
// expression for gcl mode; honors spec.stem) — no ranking. Returns false only on
// a hard error (malformed gcl, or --stem against a non-stemmed burrow).
bool jsonl_count(std::shared_ptr<Warren> warren, const QuerySpec &spec,
                 long *count, std::string *error = nullptr);

struct ExplainLeaf {
  std::string term;
  addr df = 0;
  std::string stream = "exact"; // which stream df came from: "exact" | "stemmed"
};

struct ExplainResult {
  bool parsed_ok = false;
  std::string error;
  std::vector<ExplainLeaf> leaves;
};

// Dry run: validate the query and return per-leaf document frequencies. Cheap
// (no ranking); df comes from idx()->count().
ExplainResult jsonl_explain(std::shared_ptr<Warren> warren,
                            const QuerySpec &spec);

} // namespace jsonl
} // namespace cottontail
#endif // COTTONTAIL_APPS_JSONL_CORE_H_
