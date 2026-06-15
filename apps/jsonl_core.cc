#include "apps/jsonl_core.h"

#include <algorithm>
#include <filesystem>
#include <string>
#include <vector>

#include "src/builder.h"
#include "src/nlohmann.h"
#include "src/ranking.h"
#include "src/recipe.h"
#include "src/simple_builder.h"
#include "src/stemmer.h"

namespace cottontail {
namespace jsonl {

namespace {
namespace fs = std::filesystem;

bool has_suffix(const std::string &s, const std::string &suffix) {
  return s.size() >= suffix.size() &&
         s.compare(s.size() - suffix.size(), suffix.size(), suffix) == 0;
}

// All *.jsonl / *.jsonl.gz under root, sorted for deterministic ordering.
std::vector<std::string> find_shards(const std::string &root) {
  std::vector<std::string> files;
  std::error_code ec;
  for (auto it = fs::recursive_directory_iterator(root, ec);
       !ec && it != fs::recursive_directory_iterator(); it.increment(ec)) {
    if (!it->is_regular_file(ec))
      continue;
    const std::string p = it->path().string();
    if (has_suffix(p, ".jsonl") || has_suffix(p, ".jsonl.gz"))
      files.push_back(p);
  }
  std::sort(files.begin(), files.end());
  return files;
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

std::string trim(const std::string &s) {
  size_t b = s.find_first_not_of(" \t\r\n");
  if (b == std::string::npos)
    return "";
  size_t e = s.find_last_not_of(" \t\r\n");
  return s.substr(b, e - b + 1);
}

// Truncate to at most n bytes, then step back so the result never ends inside a
// multi-byte UTF-8 character. A mid-character split leaves invalid UTF-8, which
// the JSON serializer rejects (type_error.316). n is a byte budget and snippets
// are short previews, so dropping the final partial character is fine.
std::string truncate(std::string s, size_t n) {
  if (s.size() <= n)
    return s;
  s.resize(n);
  // Walk back over UTF-8 continuation bytes (10xxxxxx) to the lead byte, then
  // drop the whole sequence if the lead's expected length runs past the cut.
  size_t i = s.size();
  while (i > 0 && (static_cast<unsigned char>(s[i - 1]) & 0xC0) == 0x80)
    --i;
  if (i > 0) {
    unsigned char lead = static_cast<unsigned char>(s[i - 1]);
    size_t need = lead < 0x80 ? 1 : lead < 0xE0 ? 2 : lead < 0xF0 ? 3 : 4;
    if (s.size() - (i - 1) < need)
      s.resize(i - 1);
  }
  return s;
}

// "(^ a b ...)" for >=2 terms, the lone term for 1, "" for none.
std::string all_of(const std::vector<std::string> &terms) {
  if (terms.empty())
    return "";
  if (terms.size() == 1)
    return terms[0];
  std::string e = "(^";
  for (const auto &t : terms)
    e += " " + t;
  return e + ")";
}

bool is_gcl_operator(const std::string &t) {
  return t == "^" || t == "+" || t == "..." || t == "<>" || t == "<<" ||
         t == ">>";
}

// True for things in a GCL expression that are not bare query terms: operators
// and structural tags (":item", ":docno", ...). These are left untouched when
// rewriting a query for stemming.
bool is_gcl_nonterm(const std::string &t) {
  return is_gcl_operator(t) || (!t.empty() && t[0] == ':');
}

// If the burrow was built with a stemmed stream, return the matching stemmer
// (reconstructed from the tokenizer recipe). Returns nullptr for a plain index.
std::shared_ptr<Stemmer> burrow_stemmer(std::shared_ptr<Warren> warren) {
  if (warren->tokenizer()->name() != "stemming")
    return nullptr;
  std::map<std::string, std::string> parameters;
  if (!cook(warren->tokenizer()->recipe(), &parameters))
    return nullptr;
  std::string name, recipe;
  if (!name_and_recipe(parameters, "stemmer", &name, &recipe))
    return nullptr;
  return Stemmer::make(name, recipe);
}

// Stem one query term into the GCL atom that addresses the stemmed stream. When
// the stemmer reports it did nothing (short/non-alpha term), the stemmer returns
// the surface form unchanged, which addresses the exact stream -- the correct
// symmetric fallback (so e.g. --stem "ox" still matches "ox").
std::string stem_atom(std::shared_ptr<Stemmer> stemmer,
                      const std::string &term) {
  return stemmer->stem(term);
}

// Rewrite a GCL expression, replacing every bare term with its stemmed atom and
// leaving operators, parens, whitespace, and ":tags" untouched. Quoted phrases
// are passed through verbatim (not stemmed term-by-term).
std::string stem_gcl(const std::string &gcl,
                     std::shared_ptr<Stemmer> stemmer) {
  std::string out, tok;
  bool in_phrase = false;
  auto flush = [&]() {
    if (tok.empty())
      return;
    if (is_gcl_nonterm(tok))
      out += tok;
    else
      out += stem_atom(stemmer, tok);
    tok.clear();
  };
  for (char c : gcl) {
    if (c == '"') { // phrase delimiter: emit the quoted span unchanged
      flush();
      out += c;
      in_phrase = !in_phrase;
    } else if (!in_phrase &&
               (c == '(' || c == ')' || c == ' ' || c == '\t' || c == '\n')) {
      flush();
      out += c;
    } else {
      tok.push_back(c);
    }
  }
  flush();
  return out;
}

// The GCL whose :item-containment defines "matches" for a query (used by count):
// all-of the terms for text mode, the expression for gcl mode, stemmed if asked.
// Empty *out means "no terms" (zero matches).
bool build_match_gcl(std::shared_ptr<Warren> warren, const QuerySpec &spec,
                     std::string *out, std::string *error) {
  if (spec.stem) {
    auto stemmer = burrow_stemmer(warren);
    if (stemmer == nullptr) {
      safe_error(error) =
          "--stem requested but this burrow has no stemmed stream "
          "(rebuild the index with --stem)";
      return false;
    }
    if (spec.is_gcl) {
      *out = stem_gcl(spec.query, stemmer);
    } else {
      std::vector<std::string> atoms;
      for (const auto &t : warren->tokenizer()->split(spec.query))
        atoms.push_back(stem_atom(stemmer, t));
      *out = all_of(atoms);
    }
  } else if (spec.is_gcl) {
    *out = spec.query;
  } else {
    *out = all_of(warren->tokenizer()->split(spec.query));
  }
  return true;
}

// Candidate term atoms in a GCL expression: drop operators, parens, and
// structural tags (":...") so --explain can report leaf document frequencies.
std::vector<std::string> gcl_terms(const std::string &gcl) {
  std::vector<std::string> out;
  std::string tok;
  auto flush = [&]() {
    if (tok.empty())
      return;
    if (tok != "^" && tok != "+" && tok != "..." && tok != "<>" &&
        tok != "<<" && tok != ">>" && tok[0] != ':')
      out.push_back(tok);
    tok.clear();
  };
  for (char c : gcl) {
    if (c == '(' || c == ')' || c == ' ' || c == '\t' || c == '\n')
      flush();
    else
      tok.push_back(c);
  }
  flush();
  return out;
}
} // namespace

bool jsonl_index(const IndexOptions &opts, IndexSummary *summary,
                 std::string *error) {
  std::error_code ec;
  if (fs::exists(opts.burrow)) {
    if (!opts.overwrite) {
      safe_error(error) =
          "burrow already exists (use --overwrite): " + opts.burrow;
      return false;
    }
    fs::remove_all(opts.burrow, ec);
  }
  std::vector<std::string> files = find_shards(opts.input);

  // Pick the inner token model. ascii is byte-level (ASCII only); utf8 is
  // Unicode-aware (case folding, accents, CJK) and is the default for the UTF-8
  // corpus. The query tool needs no matching flag -- it reconstructs whichever
  // tokenizer this is from the burrow dna.
  std::string inner_name, inner_recipe;
  if (opts.tokenizer == "ascii") {
    inner_name = "ascii";
    inner_recipe = "noxml";
  } else if (opts.tokenizer == "utf8") {
    inner_name = "utf8";
    inner_recipe = "";
  } else {
    safe_error(error) =
        "unknown --tokenizer (want ascii|utf8): " + opts.tokenizer;
    return false;
  }

  auto working = Working::mkdir(opts.burrow, error);
  auto featurizer = Featurizer::make("hashing", "", error, working);
  std::shared_ptr<Tokenizer> tokenizer;
  if (opts.stemmer.empty()) {
    tokenizer = Tokenizer::make(inner_name, inner_recipe, error);
  } else {
    // Wrap the chosen tokenizer with the named stemmer so the index carries a
    // co-located stemmed stream alongside the exact one (see docs/stemming.md).
    std::string recipe = "[ tokenizer:[ name:\"" + inner_name + "\", recipe:\"" +
                         inner_recipe + "\" ], stemmer:[ name:\"" +
                         opts.stemmer + "\", recipe:\"\" ], ]";
    tokenizer = Tokenizer::make("stemming", recipe, error);
  }
  if (working == nullptr || featurizer == nullptr || tokenizer == nullptr)
    return false;
  auto builder = SimpleBuilder::make(working, featurizer, tokenizer, error,
                                     opts.buffer, opts.buffer);
  if (builder == nullptr)
    return false;
  builder->verbose(opts.verbose);

  addr t0 = now();
  size_t rows = 0, skipped = 0, files_seen = 0;
  for (const auto &file : files) {
    if (opts.limit >= 0 && static_cast<long>(rows) >= opts.limit)
      break;
    files_seen++;
    if (opts.verbose)
      std::cerr << "indexing: " << file << "\n";
    auto everything = inhale(file, error);
    if (everything == nullptr) {
      if (opts.strict)
        return false;
      safe_error(error) = "";
      continue;
    }
    std::string::size_type sp = 0, nl;
    while ((nl = everything->find('\n', sp)) != std::string::npos) {
      if (opts.limit >= 0 && static_cast<long>(rows) >= opts.limit)
        break;
      std::string line = everything->substr(sp, nl - sp);
      sp = nl + 1;
      if (trim(line).empty())
        continue;
      std::string docid, contents;
      try {
        json j = json::parse(line);
        if (!j.contains(opts.docid_field) || !j.contains(opts.contents_field) ||
            !j[opts.docid_field].is_string() ||
            !j[opts.contents_field].is_string()) {
          skipped++;
          if (opts.strict) {
            safe_error(error) = "row missing/!string " + opts.docid_field +
                                "/" + opts.contents_field + " in " + file;
            return false;
          }
          continue;
        }
        docid = j[opts.docid_field].get<std::string>();
        contents = j[opts.contents_field].get<std::string>();
      } catch (...) {
        skipped++;
        if (opts.strict) {
          safe_error(error) = "malformed JSON line in " + file;
          return false;
        }
        continue;
      }
      addr p_id, q_id, p_body, q_body;
      if (!builder->add_text(docid, &p_id, &q_id, error) ||
          !builder->add_annotation(":docno", p_id, q_id, 0.0, error) ||
          !builder->add_text(contents, &p_body, &q_body, error) ||
          !builder->add_annotation(":item", p_id, q_body, 0.0, error))
        return false;
      rows++;
    }
  }
  if (!builder->finalize(error))
    return false;

  if (summary != nullptr) {
    summary->burrow = opts.burrow;
    summary->files_seen = files_seen;
    summary->rows_indexed = rows;
    summary->rows_skipped = skipped;
    summary->elapsed_seconds = (now() - t0) / 1000.0;
    summary->burrow_bytes = dir_bytes(opts.burrow);
    summary->tokenizer = opts.tokenizer;
    summary->stemmer = opts.stemmer;
  }
  return true;
}

std::shared_ptr<Warren> open_burrow(const std::string &burrow,
                                    std::string *error) {
  auto warren = Warren::make("simple", burrow, error);
  if (warren == nullptr)
    return nullptr;
  warren->start();
  warren->set_default_container(":item", error);
  return warren;
}

bool jsonl_query(std::shared_ptr<Warren> warren, const QuerySpec &spec,
                 std::vector<Hit> *hits, std::string *error) {
  const std::string container = ":item";
  std::vector<RankingResult> ranked;
  if (spec.stem) {
    // Stemmed retrieval: rewrite the query into stemmed-stream atoms and rank
    // with ssr (cover density). Uniform for --text and --gcl; the engine's
    // rankers don't stem on their own, so we target the stemmed features here.
    auto stemmer = burrow_stemmer(warren);
    if (stemmer == nullptr) {
      safe_error(error) =
          "--stem requested but this burrow has no stemmed stream "
          "(rebuild the index with --stem)";
      return false;
    }
    std::string query;
    if (spec.is_gcl) {
      query = stem_gcl(spec.query, stemmer);
    } else {
      std::vector<std::string> terms = warren->tokenizer()->split(spec.query);
      std::vector<std::string> atoms;
      for (const auto &t : terms)
        atoms.push_back(stem_atom(stemmer, t));
      query = all_of(atoms);
    }
    if (!query.empty()) {
      auto check = warren->hopper_from_gcl(query, error);
      if (check == nullptr)
        return false;
      ranked = ssr_ranking(warren, query, container, spec.top_k);
    }
  } else if (spec.is_gcl) {
    // Validate the expression up front so a bad --gcl is a reported error,
    // not a silent empty result.
    auto check = warren->hopper_from_gcl(spec.query, error);
    if (check == nullptr)
      return false;
    ranked = ssr_ranking(warren, spec.query, container, spec.top_k);
  } else {
    std::vector<std::string> terms = warren->tokenizer()->split(spec.query);
    if (terms.empty()) {
      // nothing to rank
    } else if (spec.ranker == "tiered") {
      ranked = tiered_ranking(warren, spec.query, container, spec.top_k);
    } else if (spec.ranker == "ssr") {
      ranked = ssr_ranking(warren, all_of(terms), container, spec.top_k);
    } else { // icover (default): cover-density needs >=2 terms; for a single
             // term fall back to ssr so one-word "grep" queries still rank.
      if (terms.size() >= 2)
        ranked = icover_ranking(warren, spec.query, container, spec.top_k);
      else
        ranked = ssr_ranking(warren, terms[0], container, spec.top_k);
    }
  }

  auto docno = warren->hopper_from_gcl(":docno", error);
  hits->clear();
  int rank = 1;
  for (const auto &r : ranked) {
    Hit h;
    h.rank = rank++;
    h.score = r.score();
    addr dp = 0, dq = -1;
    if (docno != nullptr) {
      docno->tau(r.container_p(), &dp, &dq);
      h.docid = trim(warren->txt()->translate(dp, dq));
    }
    h.best_passage.start = r.p();
    h.best_passage.end = r.q();
    h.best_passage.text =
        truncate(warren->txt()->translate(r.p(), r.q()), spec.snippet_chars);
    if (spec.full_text) {
      addr body_start = (dq >= 0 ? dq + 1 : r.container_p());
      h.full_text = warren->txt()->translate(body_start, r.container_q());
      h.has_full_text = true;
    }
    hits->push_back(std::move(h));
  }
  return true;
}

bool jsonl_get(std::shared_ptr<Warren> warren, const std::string &docid,
               std::string *text, bool *found, std::string *error) {
  *found = false;
  text->clear();
  std::vector<std::string> terms = warren->tokenizer()->split(docid);
  if (terms.empty())
    return true; // nothing to match on -> not found
  // Find an :item whose :docno contains the docid's token sequence, then verify
  // the recovered docid string matches exactly (guards against a docid whose
  // tokens are a subset of another's).
  std::string phrase = terms[0];
  if (terms.size() > 1) {
    phrase = "(...";
    for (const auto &t : terms)
      phrase += " " + t;
    phrase += ")";
  }
  std::string gcl = "(>> :item (>> :docno " + phrase + "))";
  auto hopper = warren->hopper_from_gcl(gcl, error);
  if (hopper == nullptr)
    return false;
  auto docno = warren->hopper_from_gcl(":docno", error);
  if (docno == nullptr)
    return false;
  addr p, q;
  for (hopper->tau(minfinity + 1, &p, &q); p < maxfinity;
       hopper->tau(p + 1, &p, &q)) {
    addr dp = 0, dq = -1;
    docno->tau(p, &dp, &dq);
    if (trim(warren->txt()->translate(dp, dq)) == docid) {
      *found = true;
      *text = warren->txt()->translate(dq + 1, q); // body after the :docno span
      return true;
    }
  }
  return true;
}

bool jsonl_count(std::shared_ptr<Warren> warren, const QuerySpec &spec,
                 long *count, std::string *error) {
  *count = 0;
  std::string match;
  if (!build_match_gcl(warren, spec, &match, error))
    return false;
  if (match.empty())
    return true; // no terms -> 0 matches
  std::string gcl = "(>> :item " + match + ")";
  auto hopper = warren->hopper_from_gcl(gcl, error);
  if (hopper == nullptr)
    return false; // e.g. malformed --gcl
  addr p, q;
  long n = 0;
  for (hopper->tau(minfinity + 1, &p, &q); p < maxfinity;
       hopper->tau(p + 1, &p, &q))
    n++;
  *count = n;
  return true;
}

ExplainResult jsonl_explain(std::shared_ptr<Warren> warren,
                            const QuerySpec &spec) {
  ExplainResult out;
  std::vector<std::string> terms;
  if (spec.is_gcl) {
    std::string err;
    auto check = warren->hopper_from_gcl(spec.query, &err);
    if (check == nullptr) {
      out.parsed_ok = false;
      out.error = err;
      return out;
    }
    out.parsed_ok = true;
    terms = gcl_terms(spec.query);
  } else {
    out.parsed_ok = true;
    terms = warren->tokenizer()->split(spec.query);
  }
  std::shared_ptr<Stemmer> stemmer;
  if (spec.stem) {
    stemmer = burrow_stemmer(warren);
    if (stemmer == nullptr) {
      out.parsed_ok = false;
      out.error = "--stem requested but this burrow has no stemmed stream "
                  "(rebuild the index with --stem)";
      return out;
    }
  }
  for (const auto &t : terms) {
    ExplainLeaf leaf;
    leaf.term = t;
    if (spec.stem) {
      // The stemmed atom addresses the stemmed stream; if the term is
      // unstemmable the stemmer returns the surface form (exact stream).
      bool stemmed = false;
      std::string atom = stemmer->stem(t, &stemmed);
      leaf.stream = stemmed ? "stemmed" : "exact";
      leaf.df = warren->idx()->count(warren->featurizer()->featurize(atom));
    } else {
      leaf.stream = "exact";
      leaf.df = warren->idx()->count(warren->featurizer()->featurize(t));
    }
    out.leaves.push_back(leaf);
  }
  return out;
}

} // namespace jsonl
} // namespace cottontail
