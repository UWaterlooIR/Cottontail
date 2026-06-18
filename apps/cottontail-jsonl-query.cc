// cottontail-jsonl-query — query a SimpleWarren burrow built by
// cottontail-jsonl-index. Cover-density / proximity ranking + GCL structured
// search; no precomputed statistics. See docs/cottontail-jsonl-cli-spec.md.
//
// Results -> stdout as JSON; progress/errors -> stderr.

#include <iostream>
#include <string>
#include <vector>

#include "apps/jsonl_core.h"
#include "apps/jsonl_json.h"
#include "src/nlohmann.h"

namespace {
using cottontail::jsonl::count_json;
using cottontail::jsonl::cover_results_json;
using cottontail::jsonl::CoverHit;
using cottontail::jsonl::CoverResponse;
using cottontail::jsonl::CoverSpec;
using cottontail::jsonl::describe_json;
using cottontail::jsonl::explain_json;
using cottontail::jsonl::ExplainResult;
using cottontail::jsonl::get_json;
using cottontail::jsonl::Hit;
using cottontail::jsonl::QuerySpec;
using cottontail::jsonl::results_json;

void usage(const char *prog) {
  std::cerr << "usage:\n"
            << "  " << prog << " --burrow <path> --text \"<words>\" [options]\n"
            << "  " << prog << " --burrow <path> --gcl \"<expr>\" [options]\n"
            << "  " << prog << " --burrow <path> --cover \"<cover query>\" [--top-k N]\n"
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
  std::string text, gcl, get_docid, cover;
  bool have_text = false, have_gcl = false, batch = false, explain = false;
  bool have_get = false, count = false, describe = false, have_cover = false;
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
    else if (a == "--cover")
      cover = next(), have_cover = true;
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
              (batch ? 1 : 0) + (have_cover ? 1 : 0);
  if (modes != 1) {
    std::cerr
        << "supply exactly one of --text / --gcl / --cover / --get / --batch\n";
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

  if (have_cover) {
    CoverSpec spec;
    spec.query = cover;
    spec.top_k = base.top_k;
    CoverResponse resp;
    if (!cottontail::jsonl::jsonl_cover_search(warren, spec, &resp, &error))
      die(error, "cover_search");
    std::cout << cover_results_json(resp).dump(format == "jsonl" ? -1 : 2)
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
