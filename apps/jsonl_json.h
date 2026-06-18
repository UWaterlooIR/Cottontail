#ifndef COTTONTAIL_APPS_JSONL_JSON_H_
#define COTTONTAIL_APPS_JSONL_JSON_H_

// Shared JSON serialization for the search tool surface. Both the
// cottontail-jsonl-query CLI and the cottontail-jsonl-server use these, so the
// wire contract is identical by construction (see docs/cottontail-search-server-spec.md
// §2). The shapes are documented in docs/cottontail-jsonl-cli-spec.md §4 and
// docs/cottontail-search-agent-spec.md §§3-4.

#include <string>
#include <vector>

#include "apps/jsonl_core.h"
#include "src/nlohmann.h"

namespace cottontail {
namespace jsonl {

// Ranked search results (search_text / search_gcl), including result_count and
// the cheap `truncated` heuristic.
json results_json(const QuerySpec &spec, const std::vector<Hit> &hits,
                  double elapsed_ms);

// Dry-run diagnostics: per-leaf df + stream (exact|stemmed).
json explain_json(const QuerySpec &spec, const ExplainResult &ex);

// A row fetched by docid: {docid, found, text}.
json get_json(const std::string &docid, bool found, const std::string &text);

// Selectivity: {query, query_mode, stemmed, match_count}.
json count_json(const QuerySpec &spec, long count);

// cover_search results (TASK-5.1 / A1): {results:[{rank,score,docid,summary}]}.
// A2 adds total_matches / unjudged_matches / atom_counts to the CoverResponse.
json cover_results_json(const CoverResponse &resp);

// The agent tool schema (OpenAI/Anthropic function shape) as a JSON array.
json describe_json();

} // namespace jsonl
} // namespace cottontail
#endif // COTTONTAIL_APPS_JSONL_JSON_H_
