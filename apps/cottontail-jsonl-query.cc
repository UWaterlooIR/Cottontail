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
            << "  ... --batch   (one query object per stdin line -> JSONL)\n"
            << "options: --ranker icover|ssr|tiered  --top-k N  --full-text\n"
            << "         --snippet-chars N  --format json|jsonl  --stem\n"
            << "  --stem  match the stemmed stream (index must be built --stem;\n"
            << "          ranks via cover density over stemmed terms)\n"
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
  std::string text, gcl;
  bool have_text = false, have_gcl = false, batch = false, explain = false;
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

  if (burrow.empty()) {
    usage(argv[0]);
    return 1;
  }
  int modes = (have_text ? 1 : 0) + (have_gcl ? 1 : 0) + (batch ? 1 : 0);
  if (modes != 1) {
    std::cerr << "supply exactly one of --text / --gcl / --batch\n";
    usage(argv[0]);
    return 1;
  }

  std::string error;
  auto warren = cottontail::jsonl::open_burrow(burrow, &error);
  if (warren == nullptr)
    die(error, "open");

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

  std::vector<Hit> hits;
  cottontail::addr t0 = cottontail::now();
  if (!cottontail::jsonl::jsonl_query(warren, spec, &hits, &error))
    die(error, "query");
  json out = results_json(spec, hits, cottontail::now() - t0);
  std::cout << out.dump(format == "jsonl" ? -1 : 2) << "\n";
  warren->end();
  return 0;
}
