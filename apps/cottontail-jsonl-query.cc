// cottontail-jsonl-query — query a SimpleWarren burrow built by
// cottontail-jsonl-index. Cover-density / proximity ranking + GCL structured
// search; no precomputed statistics. See docs/cottontail-jsonl-cli-spec.md.
//
// Results -> stdout as JSON; progress/errors -> stderr.

#include <iostream>
#include <string>
#include <vector>

#include "apps/jsonl_core.h"
#include "src/nlohmann.h"

namespace {
using cottontail::jsonl::ExplainResult;
using cottontail::jsonl::Hit;
using cottontail::jsonl::QuerySpec;

void usage(const char *prog) {
  std::cerr << "usage:\n"
            << "  " << prog << " --burrow <path> --text \"<words>\" [options]\n"
            << "  " << prog << " --burrow <path> --gcl \"<expr>\" [options]\n"
            << "  " << prog << " --burrow <path> --explain --gcl \"<expr>\"\n"
            << "  " << prog << " --burrow <path> --count --text \"<words>\"\n"
            << "  " << prog << " --burrow <path> --get <docid>\n"
            << "  " << prog << " --describe   (print the agent tool schema as JSON)\n"
            << "  ... --batch   (one query object per stdin line -> JSONL)\n"
            << "options: --ranker icover|ssr|tiered  --top-k N  --full-text\n"
            << "         --snippet-chars N  --format json|jsonl  --stem\n"
            << "  --stem   match the stemmed stream (index must be built --stem;\n"
            << "           ranks via cover density over stemmed terms)\n"
            << "  --count  report match_count for --text/--gcl instead of ranking\n"
            << "  --get <docid>  fetch one row's full body by docid\n"
            << "  --describe     emit the LLM tool schema (no burrow needed)\n"
            << "note: structured/precise queries are fast at any scale; a broad\n"
            << "      common-term ranked query can be second-scale on a very\n"
            << "      large corpus (cover-density touches the query terms'\n"
            << "      postings). No BM25 (it needs a stats precompute).\n";
}

json hit_json(const Hit &h) {
  json r;
  r["rank"] = h.rank;
  r["score"] = h.score;
  r["docid"] = h.docid;
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

json get_json(const std::string &docid, bool found, const std::string &text) {
  json o;
  o["docid"] = docid;
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

// The agent tool schema (OpenAI/Anthropic function shape). The example agent
// loads this verbatim; a future server exposes the identical schema.
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
      "Use first for broad recall. Returns ranked rows with docid, score and a "
      "best-passage snippet; result_count and truncated indicate if there may be "
      "more.",
      st, {"query"}));

  json sg;
  sg["query"] = strp(
      "A GCL S-expression. Operators: (^ a b) smallest span containing BOTH; "
      "(+ a b) EITHER; (... a b) a then b in order/proximity; (>> :item (^ a b)) "
      "rows CONTAINING both terms; (<< a :item) a contained in a row. Tags: :item "
      "= a whole row, :docno = its id. Example: (>> :item (^ elephant vaccine)).");
  sg["top_k"] = intp("Max rows to return (default 10).");
  sg["stem"] = boolp("Stem bare terms for recall.");
  sg["full_text"] = boolp("Return the whole row body instead of a snippet.");
  tools.push_back(tool(
      "search_gcl",
      "Structured search for precision: Boolean, phrase, proximity, containment. "
      "Use when bag-of-words is too noisy. Same ranked output as search_text.",
      sg, {"query"}));

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
  gd["docid"] = strp("A docid from a prior search result.");
  tools.push_back(tool(
      "get_document",
      "Read the full body of one row by its docid (e.g. to read a candidate "
      "before answering). Returns {docid, found, text}.",
      gd, {"docid"}));

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

[[noreturn]] void die(const std::string &msg, const std::string &where) {
  json e;
  e["error"] = msg;
  e["where"] = where;
  std::cerr << e.dump() << "\n";
  std::exit(2);
}
} // namespace

int main(int argc, char **argv) {
  std::string burrow;
  std::string text, gcl, get_docid;
  bool have_text = false, have_gcl = false, batch = false, explain = false;
  bool have_get = false, count = false, describe = false;
  QuerySpec base;
  std::string format = "json";

  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    auto next = [&]() -> std::string {
      if (i + 1 >= argc) {
        usage(argv[0]);
        std::exit(1);
      }
      return argv[++i];
    };
    if (a == "--burrow")
      burrow = next();
    else if (a == "--text")
      text = next(), have_text = true;
    else if (a == "--gcl")
      gcl = next(), have_gcl = true;
    else if (a == "--get")
      get_docid = next(), have_get = true;
    else if (a == "--count")
      count = true;
    else if (a == "--describe")
      describe = true;
    else if (a == "--batch")
      batch = true;
    else if (a == "--explain")
      explain = true;
    else if (a == "--ranker")
      base.ranker = next();
    else if (a == "--top-k")
      base.top_k = std::stoul(next());
    else if (a == "--full-text")
      base.full_text = true;
    else if (a == "--stem")
      base.stem = true;
    else if (a == "--snippet-chars")
      base.snippet_chars = std::stoul(next());
    else if (a == "--format")
      format = next();
    else if (a == "--help") {
      usage(argv[0]);
      return 0;
    } else {
      std::cerr << "unknown argument: " << a << "\n";
      usage(argv[0]);
      return 1;
    }
  }

  // --describe needs no burrow: emit the tool schema and exit.
  if (describe) {
    std::cout << describe_json().dump(2) << "\n";
    return 0;
  }

  if (burrow.empty()) {
    usage(argv[0]);
    return 1;
  }
  int modes = (have_text ? 1 : 0) + (have_gcl ? 1 : 0) + (have_get ? 1 : 0) +
              (batch ? 1 : 0);
  if (modes != 1) {
    std::cerr << "supply exactly one of --text / --gcl / --get / --batch\n";
    usage(argv[0]);
    return 1;
  }

  std::string error;
  auto warren = cottontail::jsonl::open_burrow(burrow, &error);
  if (warren == nullptr)
    die(error, "open");

  if (have_get) {
    std::string body;
    bool found = false;
    if (!cottontail::jsonl::jsonl_get(warren, get_docid, &body, &found, &error))
      die(error, "get");
    std::cout << get_json(get_docid, found, body).dump(format == "jsonl" ? -1 : 2)
              << "\n";
    warren->end();
    return 0;
  }

  if (batch) {
    std::string line;
    long input_index = 0;
    for (; std::getline(std::cin, line); input_index++) {
      if (line.empty())
        continue;
      json out;
      out["input_index"] = input_index;
      try {
        json in = json::parse(line);
        QuerySpec spec = base;
        spec.query = in.at("q").get<std::string>();
        spec.is_gcl = in.value("is_gcl", false);
        spec.top_k = in.value("top_k", base.top_k);
        spec.ranker = in.value("ranker", base.ranker);
        spec.full_text = in.value("full_text", base.full_text);
        spec.stem = in.value("stem", base.stem);
        std::vector<Hit> hits;
        std::string e;
        cottontail::addr t0 = cottontail::now();
        if (!cottontail::jsonl::jsonl_query(warren, spec, &hits, &e)) {
          out["error"] = e;
        } else {
          json r = results_json(spec, hits, cottontail::now() - t0);
          r["input_index"] = input_index;
          out = r;
        }
      } catch (const std::exception &ex) {
        out["error"] = std::string("bad input line: ") + ex.what();
      }
      std::cout << out.dump() << "\n";
    }
    warren->end();
    return 0;
  }

  QuerySpec spec = base;
  spec.is_gcl = have_gcl;
  spec.query = have_gcl ? gcl : text;

  if (explain) {
    ExplainResult ex = cottontail::jsonl::jsonl_explain(warren, spec);
    std::cout << explain_json(spec, ex).dump(2) << "\n";
    warren->end();
    return ex.parsed_ok ? 0 : 2;
  }

  if (count) {
    long n = 0;
    if (!cottontail::jsonl::jsonl_count(warren, spec, &n, &error))
      die(error, "count");
    std::cout << count_json(spec, n).dump(format == "jsonl" ? -1 : 2) << "\n";
    warren->end();
    return 0;
  }

  std::vector<Hit> hits;
  cottontail::addr t0 = cottontail::now();
  if (!cottontail::jsonl::jsonl_query(warren, spec, &hits, &error))
    die(error, "query");
  json out = results_json(spec, hits, cottontail::now() - t0);
  std::cout << out.dump(format == "jsonl" ? -1 : 2) << "\n";
  warren->end();
  return 0;
}
