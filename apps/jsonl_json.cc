#include "apps/jsonl_json.h"

#include <string>
#include <vector>

#include "apps/jsonl_core.h"
#include "src/nlohmann.h"

namespace cottontail {
namespace jsonl {

namespace {
json hit_json(const Hit &h) {
  json r;
  r["rank"] = h.rank;
  r["score"] = h.score;
  r["cp"] = h.cp;
  json bp;
  bp["start"] = h.best_passage.start;
  bp["end"] = h.best_passage.end;
  bp["text"] = h.best_passage.text;
  r["best_passage"] = bp;
  if (h.has_full_text)
    r["text"] = h.full_text;
  else
    r["text"] = nullptr;
  return r;
}
} // namespace

json results_json(const QuerySpec &spec, const std::vector<Hit> &hits,
                  double elapsed_ms) {
  json o;
  o["query"] = spec.query;
  o["query_mode"] = spec.is_gcl ? "gcl" : "text";
  // --stem ranks via cover density over stemmed atoms (ssr), regardless of mode.
  o["ranker"] = spec.stem ? std::string("ssr")
                          : (spec.is_gcl ? std::string("ssr") : spec.ranker);
  o["stemmed"] = spec.stem;
  o["top_k"] = spec.top_k;
  o["elapsed_ms"] = elapsed_ms;
  json arr = json::array();
  for (const auto &h : hits)
    arr.push_back(hit_json(h));
  o["results"] = arr;
  o["result_count"] = hits.size();
  // Cheap "there may be more" signal: the result set was at least as large as the
  // slice asked for. Approximate by design; call count_matches for an exact number.
  o["truncated"] = (hits.size() == spec.top_k);
  return o;
}

json explain_json(const QuerySpec &spec, const ExplainResult &ex) {
  json o;
  o["query"] = spec.query;
  o["query_mode"] = spec.is_gcl ? "gcl" : "text";
  o["parsed_ok"] = ex.parsed_ok;
  if (!ex.parsed_ok) {
    o["error"] = ex.error;
  } else {
    json leaves = json::array();
    for (const auto &l : ex.leaves) {
      json le;
      le["term"] = l.term;
      le["df"] = l.df;
      le["stream"] = l.stream;
      leaves.push_back(le);
    }
    o["leaves"] = leaves;
  }
  return o;
}

json get_json(addr cp, bool found, const std::string &text) {
  json o;
  o["cp"] = cp;
  o["found"] = found;
  o["text"] = found ? text : std::string("");
  return o;
}

json count_json(const QuerySpec &spec, long count) {
  json o;
  o["query"] = spec.query;
  o["query_mode"] = spec.is_gcl ? "gcl" : "text";
  o["stemmed"] = spec.stem;
  o["match_count"] = count;
  return o;
}

json cover_results_json(const CoverResponse &resp) {
  // EXACTLY these four keys (B1's SearchResponse is extra="forbid"): no query
  // echo, no elapsed_ms, no result_count/truncated.
  json o;
  o["total_matches"] = resp.total_matches;
  o["unjudged_matches"] = resp.unjudged_matches;
  json atoms = json::array();
  for (const auto &a : resp.atom_counts) {
    json e;
    e["term"] = a.term;
    e["count"] = a.count;
    atoms.push_back(e);
  }
  o["atom_counts"] = atoms;
  json arr = json::array();
  for (const auto &h : resp.results) {
    json r;
    r["rank"] = h.rank;
    r["score"] = h.score;
    r["docid"] = h.docid;
    r["summary"] = h.summary;
    arr.push_back(r);
  }
  o["results"] = arr;
  return o;
}

// The agent tool schema (OpenAI/Anthropic function shape). The example agent and
// the server's /describe both emit this verbatim.
json describe_json() {
  auto strp = [](const std::string &d) {
    json p;
    p["type"] = "string";
    p["description"] = d;
    return p;
  };
  auto intp = [](const std::string &d) {
    json p;
    p["type"] = "integer";
    p["description"] = d;
    return p;
  };
  auto boolp = [](const std::string &d) {
    json p;
    p["type"] = "boolean";
    p["description"] = d;
    return p;
  };
  auto tool = [](const std::string &name, const std::string &desc, json props,
                 std::vector<std::string> required) {
    json params;
    params["type"] = "object";
    params["properties"] = props;
    params["required"] = required;
    json fn;
    fn["name"] = name;
    fn["description"] = desc;
    fn["parameters"] = params;
    json t;
    t["type"] = "function";
    t["function"] = fn;
    return t;
  };

  json tools = json::array();

  json st;
  st["query"] = strp("Natural-language words to find.");
  st["top_k"] = intp("Max rows to return (default 10).");
  st["stem"] = boolp("Also match morphological variants (run<->running); trades "
                     "precision for recall.");
  st["full_text"] = boolp("Return the whole row body instead of a snippet.");
  tools.push_back(tool(
      "search_text",
      "Ranked full-text search over the corpus (cover-density proximity ranking). "
      "Use first for broad recall. Returns ranked rows with cp, score and a "
      "best-passage snippet; result_count and truncated indicate if there may be "
      "more.",
      st, {"query"}));

  json sg;
  sg["query"] = strp(
      "A GCL S-expression. Operators: (^ a b) smallest span containing BOTH; "
      "(+ a b) EITHER; (... a b) a then b in order/proximity; (>> :item (^ a b)) "
      "rows CONTAINING both terms; (<< a :item) a contained in a row. Tag :item "
      "= a whole row. Example: (>> :item (^ elephant vaccine)).");
  sg["top_k"] = intp("Max rows to return (default 10).");
  sg["stem"] = boolp("Stem bare terms for recall.");
  sg["full_text"] = boolp("Return the whole row body instead of a snippet.");
  tools.push_back(tool(
      "search_gcl",
      "Structured search for precision: Boolean, phrase, proximity, containment. "
      "Use when bag-of-words is too noisy. Same ranked output as search_text.",
      sg, {"query"}));

  json cs;
  cs["query"] = strp(
      "A GCL cover query. Build it as a COVER: one facet per concept, AND-ed "
      "with ^, e.g. (^ black bear* attack*). A bare word matches EXACTLY (use "
      "for proper nouns / defining words). A word followed by * matches that "
      "word AND its whole family (bear* -> bear, bears; write the FULL word "
      "then *, never a shortened stem). (+ a b) is for SYNONYMS. \"a b\" is an "
      "exact phrase (a trailing * is honored inside it too).");
  cs["top_k"] = intp("Max documents to return (default 10).");
  {
    json items;
    items["type"] = "string";
    json arrp;
    arrp["type"] = "array";
    arrp["items"] = items;
    arrp["description"] =
        "docids already judged, to carve out of this search (the engine skips "
        "them so top_k fills with new documents).";
    cs["exclude_docids"] = arrp;
  }
  cs["window"] = intp("Summary window size in tokens, centered on each cover "
                      "(default 75).");
  tools.push_back(tool(
      "cover_search",
      "Ranked cover-density search for the ISJ agent. Ranks documents by "
      "proximity of the query's facets and returns, per document, a "
      "cover-biased extractive summary to read and judge. Use the word* family "
      "marker for ordinary content words so you need not enumerate inflections.",
      cs, {"query"}));

  json ex;
  ex["query"] = strp("The query to analyze.");
  ex["is_gcl"] = boolp("Treat the query as a GCL expression.");
  ex["stem"] = boolp("Resolve terms against the stemmed stream.");
  tools.push_back(tool(
      "explain",
      "Dry-run a query WITHOUT ranking: returns each term's document frequency "
      "(df) and which stream it hit (exact|stemmed). Use to check a term isn't "
      "zero-hit before spending a real search.",
      ex, {"query"}));

  json gd;
  gd["cp"] = intp("A cp from a prior search result.");
  tools.push_back(tool(
      "get_document",
      "Read the full body of one row by its cp (e.g. to read a candidate "
      "before answering). Returns {cp, found, text}.",
      gd, {"cp"}));

  json cm;
  cm["query"] = strp("The query to count.");
  cm["is_gcl"] = boolp("Treat the query as a GCL expression.");
  cm["stem"] = boolp("Count against the stemmed stream.");
  tools.push_back(tool(
      "count_matches",
      "Count how many rows match a query (no ranking) to gauge selectivity. For "
      "words this is an AND of the terms; for GCL it's the expression. Returns "
      "{query, match_count}.",
      cm, {"query"}));

  return tools;
}

} // namespace jsonl
} // namespace cottontail
