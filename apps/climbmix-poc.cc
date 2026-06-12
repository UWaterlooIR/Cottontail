// climbmix-poc.cc — "powerful grep" probe for the ClimbMix JSONL corpus.
//
// Builds a static, disk-based SimpleWarren over gzip'd JSONL shards (one row =
// one document; only `docid` and `contents` are used) and then exercises the
// capabilities an agent actually wants from a structured-search tool — WITHOUT
// the BM25 statistics precompute (`tf_idf_annotations`), which we found to be
// the only part that does not scale.
//
// On the bare index (token inverted index + :item/:docno structural
// annotations + stored text) this demonstrates, with timings:
//   (a) instant term document-frequencies (corpus stats on demand),
//   (b) icover_ranking — cover-density document ranking (Clarke & Terra 2004),
//   (c) ssr_ranking over "(^ term...)" — proximity-ranked Boolean AND,
//   (d) structured containment counting "(>> :item (^ term...))" — how many /
//       which documents match an AND query (grep++),
//   (e) an arbitrary GCL expression via --gcl (phrase/proximity/containment).
// BM25 (which needs the expensive per-(doc,term) tf precompute) is opt-in via
// --bm25, purely for comparison. The Hazel path is gone (Hazel is not ready).

#include <cstdio>
#include <filesystem>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

#include <sys/resource.h>

#include "src/builder.h"
#include "src/cottontail.h"
#include "src/nlohmann.h"
#include "src/ranking.h"
#include "src/simple_builder.h"

namespace {
namespace fs = std::filesystem;

long peak_rss_kb() {
  struct rusage ru;
  getrusage(RUSAGE_SELF, &ru);
  return ru.ru_maxrss;
}

uintmax_t dir_bytes(const std::string &path) {
  uintmax_t total = 0;
  std::error_code ec;
  for (auto it = fs::recursive_directory_iterator(path, ec);
       !ec && it != fs::recursive_directory_iterator(); it.increment(ec))
    if (it->is_regular_file(ec))
      total += it->file_size(ec);
  return total;
}

std::string shard_path(const std::string &dir, int i) {
  char buf[64];
  std::snprintf(buf, sizeof(buf), "shard_%05d.jsonl.gz", i);
  return dir + "/" + buf;
}

std::string oneline(std::string s, size_t n) {
  for (auto &c : s)
    if (c == '\n' || c == '\t' || c == '\r')
      c = ' ';
  if (s.size() > n)
    s = s.substr(0, n) + "...";
  return s;
}
} // namespace

int main(int argc, char **argv) {
  std::string corpus = "/share/corpora/climbmix-400b-corpus-jsonl";
  std::string burrow = "Scrapheap/climbmix.burrow";
  std::string query = "influenza vaccination";
  std::string gcl = "";
  int limit = 20;
  size_t buffer = 256UL * 1024 * 1024;
  bool do_bm25 = false;

  std::vector<std::string> pos;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    if (a == "--limit" && i + 1 < argc)
      limit = std::stoi(argv[++i]);
    else if (a == "--buffer" && i + 1 < argc)
      buffer = std::stoull(argv[++i]);
    else if (a == "--gcl" && i + 1 < argc)
      gcl = argv[++i];
    else if (a == "--bm25")
      do_bm25 = true;
    else if (a == "--help") {
      std::cerr << "usage: " << argv[0]
                << " [corpus_dir] [burrow] [query] [--limit N] [--buffer R]"
                   " [--gcl EXPR] [--bm25]\n";
      return 0;
    } else
      pos.push_back(a);
  }
  if (pos.size() > 0)
    corpus = pos[0];
  if (pos.size() > 1)
    burrow = pos[1];
  if (pos.size() > 2)
    query = pos[2];

  std::string error;
  std::error_code ec;
  fs::remove_all(burrow, ec);

  std::vector<std::string> shards;
  for (int i = 0; i < limit; i++) {
    std::string p = shard_path(corpus, i);
    if (fs::exists(p))
      shards.push_back(p);
  }
  if (shards.empty()) {
    std::cerr << "no shards found under " << corpus << "\n";
    return 1;
  }
  std::cerr << "shards: " << shards.size() << "   buffer(records): " << buffer
            << "\n";

  // ---- Build phase: static SimpleWarren burrow, NO stats precompute ----
  auto working = cottontail::Working::mkdir(burrow, &error);
  auto featurizer = cottontail::Featurizer::make("hashing", "", &error, working);
  auto tokenizer = cottontail::Tokenizer::make("ascii", "noxml", &error);
  if (working == nullptr || featurizer == nullptr || tokenizer == nullptr) {
    std::cerr << "construction: " << error << "\n";
    return 1;
  }
  auto builder = cottontail::SimpleBuilder::make(working, featurizer, tokenizer,
                                                 &error, buffer, buffer);
  if (builder == nullptr) {
    std::cerr << "builder: " << error << "\n";
    return 1;
  }
  builder->verbose(true);

  cottontail::addr t0 = cottontail::now();
  size_t rows = 0, skipped = 0;
  for (auto &shard : shards) {
    auto everything = cottontail::inhale(shard, &error);
    if (everything == nullptr) {
      std::cerr << "inhale: " << error << "\n";
      return 1;
    }
    std::string::size_type sp = 0, nl;
    while ((nl = everything->find('\n', sp)) != std::string::npos) {
      std::string line = everything->substr(sp, nl - sp);
      sp = nl + 1;
      if (line.empty())
        continue;
      std::string docid, contents;
      try {
        json j = json::parse(line);
        if (!j.contains("docid") || !j.contains("contents")) {
          skipped++;
          continue;
        }
        docid = j["docid"].get<std::string>();
        contents = j["contents"].get<std::string>();
      } catch (...) {
        skipped++;
        continue;
      }
      cottontail::addr p_id, q_id, p_body, q_body;
      if (!builder->add_text(docid, &p_id, &q_id, &error) ||
          !builder->add_annotation(":docno", p_id, q_id, 0.0, &error) ||
          !builder->add_text(contents, &p_body, &q_body, &error) ||
          !builder->add_annotation(":item", p_id, q_body, 0.0, &error)) {
        std::cerr << "add: " << error << "\n";
        return 1;
      }
      rows++;
    }
    std::cerr << "  ingested " << shard << "   rows so far: " << rows << "\n";
  }
  if (!builder->finalize(&error)) {
    std::cerr << "finalize: " << error << "\n";
    return 1;
  }
  cottontail::addr t_built = cottontail::now();
  uintmax_t burrow_bytes = dir_bytes(burrow);

  // ---- Open read-only and run the "powerful grep" demonstrations ----
  auto warren = cottontail::Warren::make("simple", burrow, &error);
  if (warren == nullptr) {
    std::cerr << "open: " << error << "\n";
    return 1;
  }
  warren->start();
  warren->set_default_container(":item", &error);

  std::vector<std::string> terms = warren->tokenizer()->split(query);
  std::string allof;
  if (terms.size() >= 2) {
    allof = "(^";
    for (auto &t : terms)
      allof += " " + t;
    allof += ")";
  } else if (terms.size() == 1) {
    allof = terms[0];
  }

  auto docno_id = [&](cottontail::addr at) -> std::string {
    auto h = warren->hopper_from_gcl(":docno", &error);
    if (h == nullptr)
      return "?";
    cottontail::addr dp, dq;
    h->tau(at, &dp, &dq);
    return oneline(warren->txt()->translate(dp, dq), 64);
  };
  auto show = [&](const std::string &label,
                  const std::vector<cottontail::RankingResult> &res,
                  cottontail::addr ms) {
    std::cout << "\n[" << label << "]  hits=" << res.size() << "   (" << ms
              << " ms)\n";
    for (size_t i = 0; i < res.size() && i < 5; i++) {
      std::string snip =
          oneline(warren->txt()->translate(res[i].p(), res[i].q()), 130);
      std::cout << "  " << (i + 1) << "  score=" << res[i].score()
                << "  docid=" << docno_id(res[i].container_p()) << "\n      "
                << snip << "\n";
    }
  };

  std::cout << "query: \"" << query << "\"   tokens:";
  for (auto &t : terms)
    std::cout << " " << t;
  std::cout << "\n\n(a) term document frequencies (instant, no precompute):\n";
  for (auto &t : terms)
    std::cout << "    " << t << "\t"
              << warren->idx()->count(warren->featurizer()->featurize(t))
              << "\n";

  // (b) cover-density document ranking
  cottontail::addr b0 = cottontail::now();
  auto icover = cottontail::icover_ranking(warren, query, ":item", 10);
  cottontail::addr b1 = cottontail::now();
  show("icover (cover-density ranking)", icover, b1 - b0);

  // (c) proximity-ranked Boolean AND
  if (!allof.empty()) {
    cottontail::addr c0 = cottontail::now();
    auto ssr = cottontail::ssr_ranking(warren, allof, ":item", 10);
    cottontail::addr c1 = cottontail::now();
    show("ssr proximity AND " + allof, ssr, c1 - c0);
  }

  // (d) structured containment counting: which/how many docs match the AND
  if (!allof.empty()) {
    std::string contain = "(>> :item " + allof + ")";
    cottontail::addr d0 = cottontail::now();
    auto h = warren->hopper_from_gcl(contain, &error);
    long n = 0;
    std::vector<std::string> sample;
    if (h != nullptr) {
      cottontail::addr p, q;
      for (h->tau(cottontail::minfinity + 1, &p, &q); p < cottontail::maxfinity;
           h->tau(p + 1, &p, &q)) {
        n++;
        if (sample.size() < 5)
          sample.push_back(docno_id(p));
      }
    }
    cottontail::addr d1 = cottontail::now();
    std::cout << "\n(d) documents containing ALL terms  " << contain << "\n    "
              << n << " matching documents   (" << (d1 - d0) << " ms)\n";
    for (auto &s : sample)
      std::cout << "      " << s << "\n";
  }

  // (e) arbitrary GCL passthrough
  if (!gcl.empty()) {
    cottontail::addr e0 = cottontail::now();
    auto h = warren->hopper_from_gcl(gcl, &error);
    long n = 0;
    std::vector<std::string> sample;
    if (h == nullptr) {
      std::cout << "\n(e) --gcl parse error: " << error << "\n";
    } else {
      cottontail::addr p, q;
      for (h->tau(cottontail::minfinity + 1, &p, &q); p < cottontail::maxfinity;
           h->tau(p + 1, &p, &q)) {
        n++;
        if (sample.size() < 5)
          sample.push_back(oneline(warren->txt()->translate(p, q), 110));
      }
      cottontail::addr e1 = cottontail::now();
      std::cout << "\n(e) --gcl " << gcl << "\n    " << n << " solutions   ("
                << (e1 - e0) << " ms)\n";
      for (auto &s : sample)
        std::cout << "      " << s << "\n";
    }
  }

  // (optional) BM25, which requires the expensive tf precompute
  cottontail::addr bm25_precompute_ms = -1, bm25_rank_ms = -1;
  if (do_bm25) {
    auto porter = cottontail::Stemmer::make("porter", "", &error);
    if (porter != nullptr)
      warren->set_stemmer(porter);
    cottontail::addr s0 = cottontail::now();
    if (!cottontail::tf_idf_annotations(warren, &error)) {
      std::cerr << "tf_idf_annotations: " << error << "\n";
    } else {
      cottontail::addr s1 = cottontail::now();
      bm25_precompute_ms = s1 - s0;
      auto r = cottontail::bm25_ranking(warren, query);
      cottontail::addr s2 = cottontail::now();
      bm25_rank_ms = s2 - s1;
      show("bm25 (after precompute)", r, bm25_rank_ms);
    }
  }
  warren->end();

  // ---- Summary ----
  std::cerr << "\n==== SUMMARY ====\n";
  std::cerr << "shards:            " << shards.size() << "\n";
  std::cerr << "rows indexed:      " << rows << "\n";
  std::cerr << "rows skipped:      " << skipped << "\n";
  std::cerr << "build ms:          " << (t_built - t0) << "\n";
  std::cerr << "burrow bytes:      " << burrow_bytes << "  (no stats precompute)\n";
  if (do_bm25) {
    std::cerr << "bm25 precompute ms:" << bm25_precompute_ms << "\n";
    std::cerr << "bm25 rank ms:      " << bm25_rank_ms << "\n";
  }
  std::cerr << "peak RSS KB:       " << peak_rss_kb() << "\n";
  return 0;
}
