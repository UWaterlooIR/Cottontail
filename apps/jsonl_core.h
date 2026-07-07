#ifndef COTTONTAIL_APPS_JSONL_CORE_H_
#define COTTONTAIL_APPS_JSONL_CORE_H_

// Shared logic for the cottontail-jsonl-index / cottontail-jsonl-query CLIs.
// The CLIs are thin argv/JSON wrappers over these functions so the behavior is
// unit-testable without spawning processes (see docs/cottontail-jsonl-cli-spec.md
// §11). The index is a static, disk-based SimpleWarren with one document per JSON
// row: it stores the text plus one ":item" annotation over the body, and nothing
// else (no docno tokenization, no ":docno"). The unique internal id is the
// ":item" start address (cp); jsonl_index pairs each docno with its cp in a flat
// <burrow>/docno-cp.tsv dump, from which the index CLI (TASK-6.3) builds the
// cp<->docno SQLite map. See docs/indexing.md (decision doc-6, cp-native, and the
// docno/text naming, doc-7). The query side is cp-native throughout (the
// TASK-5.12 / A3 cutover): results carry cp, and docno<->cp mapping is
// Python-only (doc-8).

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_set>
#include <vector>

#include "src/cottontail.h"

namespace cottontail {
namespace jsonl {

struct IndexOptions {
  std::string input;                  // root directory to recurse
  std::string burrow;                 // output burrow path
  std::string docno_field = "docid";    // JSON field name holding the docno
  std::string text_field = "contents";  // JSON field name holding the text
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
  addr cp = 0; // the document's working identity (:item container start)
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
  size_t rank_threads = 1;       // threads INSIDE one ranking call (TASK-25);
                                 // 0 = allowed_threads cap. Set by the binary's
                                 // policy (CLI flag / server auto-budget), never
                                 // from the wire.
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
  std::vector<addr> exclude; // judged cp integers to skip (A2; direct cp post-filter)
  size_t window = 75;        // summary window in tokens (A2)
  size_t max_covers = 1;     // summary is built from the best K=max_covers covers
  size_t max_words = 150;    // cap the whole summary to this many tokens (0 = uncapped)
  size_t rank_threads = 1;   // threads INSIDE the ranking pass (TASK-25); 0 =
                             // allowed_threads cap. Binary policy, never wire.
};

struct CoverHit {
  int rank = 0;        // 1-based position within this response
  double score = 0.0;  // ssr cover-density score (sum over covers of 1/(K+q-p))
  addr cp = 0;         // the document's working identity (:item container start)
  std::string summary; // cover-biased extractive summary (replaces best_passage)
};

// Per query-leaf occurrence count (A2 populates atom_counts). count = total
// OCCURRENCES of the resolved feature in the corpus (collection frequency).
struct AtomCount {
  std::string term;  // the atom AS WRITTEN (e.g. bear*), never the porter: form
  long count = 0;
};

// The cover_search response aggregate (mirrors B1's SearchResponse, TASK-5.5).
// A1 fills only `results`; A2 fills total_matches / unjudged_matches / atom_counts.
struct CoverResponse {
  long total_matches = 0;              // A2: documents matching the query in :item
  long unjudged_matches = 0;           // A2: matches not in exclude_docids
  std::vector<AtomCount> atom_counts;  // A2: per query-leaf occurrence counts
  std::vector<CoverHit> results;       // ranked documents (rank/score/docid/summary)
};

// Rank a cover query by ssr cover density within :item and return, per returned
// document, a cover-biased extractive summary. `word*` atoms resolve to the
// burrow's stemmed stream (parity with the index's own Porter). Returns false
// (with *error) on a hard failure: malformed GCL, a non-trailing '*' in a term,
// or a word* query against a burrow with no stemmed stream (no silent fallback
// to exact).
bool jsonl_cover_search(std::shared_ptr<Warren> warren, const CoverSpec &spec,
                        CoverResponse *out, std::string *error = nullptr);

// A ranked :item container: its cp (start), cq (end), and ssr cover-density score.
struct CoverRanked {
  addr cp = 0;
  addr cq = 0;
  double score = 0.0;
};

// The cover_search/tiered ranking pass (TASK-25): rank `query` by ssr cover
// density within :item, keeping the top `depth` containers, and count
// total_matches / unjudged_matches (vs the read-only `exclude` cp set) as a
// byproduct. threads > 1 splits the shard's token span into contiguous ranges
// of at least `min_range_tokens` (a container belongs to the range holding its
// cp, so scores and counts are exactly those of the sequential pass) and ranks
// the ranges on warren->clone() workers; threads == 1 is the sequential pass;
// threads == 0 means the allowed_threads cap. `min_range_tokens` is a parameter
// only so unit tests can exercise the multi-range merge on a tiny fixture.
bool parallel_cover_ranking(std::shared_ptr<Warren> warren,
                            const std::string &query, size_t depth,
                            const std::unordered_set<addr> &exclude,
                            std::vector<CoverRanked> *ranked,
                            long *total_matches, long *unjudged_matches,
                            std::string *error, size_t threads = 1,
                            addr min_range_tokens = 1000000);

// ---- tiered_query_search: an ordered cascade of cover tiers (TASK-19) ------
// The ISJ agent's SECOND search tool. `tiers` is an ordered list of GCL cover
// queries, most precise first and broadest last, run as a de-duplicated CASCADE:
// each tier ranks the collection, cross-tier duplicates are dropped, and tighter
// tiers outrank broader ones. Same word*/summary rules as cover_search, and the
// SAME CoverResponse shape (reuse cover_results_json). Built entirely from the
// cover_search helpers -- no new ranking math, no native src/ranking.cc call.
struct TieredSpec {
  std::vector<std::string> tiers;  // ordered cover queries, tightest first
  size_t top_k = 10;
  std::vector<addr> exclude; // judged/consumed cp integers to skip (cp post-filter)
  size_t window = 75;        // summary window in tokens
  size_t max_covers = 1;     // summary is built from the best K covers
  size_t max_words = 150;    // cap the whole summary to this many tokens (0 = uncapped)
  size_t rank_threads = 1;   // threads INSIDE each tier's ranking pass (TASK-25);
                             // 0 = allowed_threads cap. Binary policy, never wire.
};

// Run the tiers as a de-duplicated cascade and return the merged ranked list with,
// per document, a summary built against the TIER THAT SURFACED IT (faithful
// per-tier biasing). atom_counts is the UNION of every tier's leaves; total_matches
// / unjudged_matches are the EXACT distinct union across tiers (0 iff every tier is
// dry). The merged score is tier-monotonic so precise->broad order survives the
// caller's later (grade, score) tiebreak; a single-tier cascade reduces exactly to
// cover_search. Returns false (with *error, NAMING the offending tier) on a
// malformed tier, or a word* tier against a burrow with no stemmed stream --
// WHOLE-REQUEST-FAIL: one bad tier rejects the whole call (a count-0 atom does not,
// it simply goes dry).
bool jsonl_tiered_query_search(std::shared_ptr<Warren> warren,
                               const TieredSpec &spec, CoverResponse *out,
                               std::string *error = nullptr);

// ---- multitext_tiered_search: a MultiText DSL program front end (TASK-22) --
// The MultiTextTieredSearcher's tool. `program` is a MultiText DSL program --
// `name = expr` macro definitions (one per line) ending in one `@rank t0 t1 ...`
// line naming the tier macros, most precise first. The program is compiled
// server-side with a fresh cottontail::Mt (gcl/mt.h; the statement walk mirrors
// apps/mt-compile.cc, including tolerating a legacy numeric topic label after
// @rank and skipping blank/#/;; lines); the compiled tier s-expressions feed the
// SAME jsonl_tiered_query_search cascade above, so ranking, summaries, and
// atom_counts behave identically to the JSON-tiers tool. Returns false on ANY
// compile problem with *error carrying the per-statement diagnostics (one per
// line, mt-compile style) -- the server returns them as the HTTP 400 body and
// the agent controller bounces them to the model for self-correction.
struct MtSpec {
  std::string program;       // the full MultiText program text
  size_t top_k = 10;
  std::vector<addr> exclude; // judged/consumed cp integers to skip
  size_t window = 75;        // summary window in tokens
  size_t max_covers = 1;     // summary is built from the best K covers
  size_t max_words = 150;    // cap the whole summary to this many tokens (0 = uncapped)
  size_t rank_threads = 1;   // threads INSIDE each tier's ranking pass (TASK-25);
                             // 0 = allowed_threads cap. Binary policy, never wire.
};

bool jsonl_multitext_tiered_search(std::shared_ptr<Warren> warren,
                                   const MtSpec &spec, CoverResponse *out,
                                   std::string *error = nullptr);

// Fetch the full body of the document at `cp` (the :item container start, as
// returned by search). Sets *found=false (not an error) when `cp` is not an :item
// start. Returns false only on a hard error. cp-native: no docno, no map.
bool jsonl_get(std::shared_ptr<Warren> warren, addr cp, std::string *text,
               bool *found, std::string *error = nullptr);

// Count the :item rows that match `spec` (AND of the terms for text mode, the
// expression for gcl mode; honors spec.stem) — no ranking. Returns false only on
// a hard error (malformed gcl, or --stem against a non-stemmed burrow).
bool jsonl_count(std::shared_ptr<Warren> warren, const QuerySpec &spec,
                 long *count, std::string *error = nullptr);

} // namespace jsonl
} // namespace cottontail
#endif // COTTONTAIL_APPS_JSONL_CORE_H_
