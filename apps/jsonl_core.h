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
  std::string stemmer = "";           // "" = none; "porter" = add a stemmed stream
};

struct IndexSummary {
  std::string burrow;
  size_t files_seen = 0;
  size_t rows_indexed = 0;
  size_t rows_skipped = 0;
  double elapsed_seconds = 0.0;
  uintmax_t burrow_bytes = 0;
  std::string stemmer = ""; // stemmer baked into the index ("" = none)
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
