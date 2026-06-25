// cottontail-jsonl-index — index a directory tree of *.jsonl / *.jsonl.gz into a
// static SimpleWarren burrow. Each document is stored as its text plus one
// ":item" annotation (no ":docno", no docno tokens); each docno is paired with
// its cp in a flat <burrow>/docno-cp.tsv dump, from which the index CLI
// (TASK-6.3) builds the cp<->docno SQLite map. See docs/indexing.md (doc-6,
// doc-7) and docs/cottontail-jsonl-cli-spec.md.
//
// Progress/warnings -> stderr; the final summary -> stdout as JSON.

#include <iostream>
#include <string>

#include "apps/jsonl_core.h"
#include "src/nlohmann.h"

namespace {
void usage(const char *prog) {
  std::cerr
      << "usage: " << prog << " --input <dir> --burrow <path> [options]\n"
      << "  --docno-field <name>     JSON field holding the docno (default docid)\n"
      << "  --text-field <name>      JSON field holding the text (default contents)\n"
      << "  --buffer <records>       builder buffer size (default 268435456)\n"
      << "  --overwrite              replace an existing burrow\n"
      << "  --limit <n>              index at most n rows\n"
      << "  --strict                 make skipped lines fatal\n"
      << "  --tokenizer <ascii|utf8> token model (default utf8: Unicode-aware)\n"
      << "  --stem <name>            also build a stemmed stream (e.g. porter)\n"
      << "  --verbose                per-file progress to stderr\n";
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
  cottontail::jsonl::IndexOptions opts;
  bool have_input = false, have_burrow = false;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    auto next = [&](const char *flag) -> std::string {
      if (i + 1 >= argc) {
        usage(argv[0]);
        std::exit(1);
      }
      (void)flag;
      return argv[++i];
    };
    if (a == "--input")
      opts.input = next("--input"), have_input = true;
    else if (a == "--burrow")
      opts.burrow = next("--burrow"), have_burrow = true;
    else if (a == "--docno-field")
      opts.docno_field = next("--docno-field");
    else if (a == "--text-field")
      opts.text_field = next("--text-field");
    else if (a == "--buffer")
      opts.buffer = std::stoull(next("--buffer"));
    else if (a == "--limit")
      opts.limit = std::stol(next("--limit"));
    else if (a == "--overwrite")
      opts.overwrite = true;
    else if (a == "--strict")
      opts.strict = true;
    else if (a == "--tokenizer")
      opts.tokenizer = next("--tokenizer");
    else if (a == "--stem")
      opts.stemmer = next("--stem");
    else if (a == "--verbose")
      opts.verbose = true;
    else if (a == "--help") {
      usage(argv[0]);
      return 0;
    } else {
      std::cerr << "unknown argument: " << a << "\n";
      usage(argv[0]);
      return 1;
    }
  }
  if (!have_input || !have_burrow) {
    usage(argv[0]);
    return 1;
  }

  cottontail::jsonl::IndexSummary summary;
  std::string error;
  if (!cottontail::jsonl::jsonl_index(opts, &summary, &error))
    die(error, "index");

  json out;
  out["burrow"] = summary.burrow;
  out["files_seen"] = summary.files_seen;
  out["rows_indexed"] = summary.rows_indexed;
  out["rows_skipped"] = summary.rows_skipped;
  out["elapsed_seconds"] = summary.elapsed_seconds;
  out["burrow_bytes"] = summary.burrow_bytes;
  out["tokenizer"] = summary.tokenizer;
  if (summary.stemmer.empty())
    out["stemmer"] = nullptr;
  else
    out["stemmer"] = summary.stemmer;
  std::cout << out.dump(2) << "\n";
  return 0;
}
