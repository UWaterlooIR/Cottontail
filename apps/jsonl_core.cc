#include "apps/jsonl_core.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <set>
#include <string>
#include <vector>

#include "src/builder.h"
#include "src/content_index.h"
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
  // The full prefix-operator set the parser accepts (src/parse.cc:19), so cover
  // rewriting and atom-count leaf enumeration never mistake an operator for a term.
  return t == "^" || t == "+" || t == "..." || t == "<>" || t == "<<" ||
         t == ">>" || t == "!<" || t == "!>" || t == "#" || t == "@";
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

// ---- cover_search helpers (TASK-5.1 / A1) ---------------------------------

// The SINGLE place a word* marker becomes a feature atom (A2's atom_counts
// reuses this). `word` is the bare word WITHOUT the trailing '*'. Resolves
// through the burrow's own Porter, so bear -> porter:bear (the symmetric stemmed
// stream) and an unstemmable word -> the exact surface form (ox -> ox).
std::string resolve_family_atom(std::shared_ptr<Stemmer> stemmer,
                                const std::string &word) {
  return stem_atom(stemmer, word);
}

// Translate one bareword token under the word* rules into *out. Operators and
// :tags pass verbatim; a token with a single TRAILING '*' becomes its family
// atom; any other '*' (mid-token, repeated, or a lone '*') is a hard error.
bool emit_cover_term(const std::string &t, std::shared_ptr<Stemmer> stemmer,
                     std::string *out, std::string *error) {
  if (t.empty())
    return true;
  if (is_gcl_nonterm(t)) {
    *out += t;
    return true;
  }
  auto star = t.find('*');
  if (star == std::string::npos) {
    *out += t; // bare term -> exact
    return true;
  }
  if (star == t.size() - 1 && star > 0 && t.find('*') == t.rfind('*')) {
    *out += resolve_family_atom(stemmer, t.substr(0, star));
    return true;
  }
  safe_error(error) =
      "invalid '*' in term '" + t +
      "': the family marker must be a single trailing '*' (e.g. bear*)";
  return false;
}

// Rewrite a cover query, translating word* markers to stemmed-stream atoms. Bare
// terms stay exact; operators/:tags are untouched. A quoted phrase that uses
// word* is desugared HERE (before the normal expand_phrases pass) into the
// explicit (>> (# n) (... ...)) form with each word translated -- splitting the
// phrase on WHITESPACE so a trailing '*' survives (the tokenizer would drop it).
// A star-free phrase is left quoted for the standard pass. Returns false on a
// malformed '*' or an unterminated phrase.
bool cover_rewrite(const std::string &gcl, std::shared_ptr<Stemmer> stemmer,
                   std::string *out, std::string *error) {
  out->clear();
  std::string tok, phrase;
  bool in_phrase = false;
  auto flush = [&]() -> bool {
    bool ok = emit_cover_term(tok, stemmer, out, error);
    tok.clear();
    return ok;
  };
  auto emit_phrase = [&]() -> bool {
    if (phrase.find('*') == std::string::npos) { // star-free: keep quoted
      *out += '"';
      *out += phrase;
      *out += '"';
      return true;
    }
    std::vector<std::string> words;
    std::string w;
    for (char c : phrase) {
      if (c == ' ' || c == '\t' || c == '\n') {
        if (!w.empty()) {
          words.push_back(w);
          w.clear();
        }
      } else {
        w.push_back(c);
      }
    }
    if (!w.empty())
      words.push_back(w);
    std::vector<std::string> atoms;
    for (const auto &word : words) {
      std::string a;
      if (!emit_cover_term(word, stemmer, &a, error))
        return false;
      atoms.push_back(a);
    }
    if (atoms.empty())
      return true;
    if (atoms.size() == 1) {
      *out += atoms[0];
      return true;
    }
    *out += "(>> (# " + std::to_string(atoms.size()) + ") (...";
    for (const auto &a : atoms)
      *out += " " + a;
    *out += "))";
    return true;
  };
  for (char c : gcl) {
    if (c == '"') {
      if (!in_phrase) {
        if (!flush())
          return false;
        in_phrase = true;
        phrase.clear();
      } else {
        if (!emit_phrase())
          return false;
        in_phrase = false;
      }
    } else if (in_phrase) {
      phrase.push_back(c);
    } else if (c == '(' || c == ')' || c == ' ' || c == '\t' || c == '\n') {
      if (!flush())
        return false;
      *out += c;
    } else {
      tok.push_back(c);
    }
  }
  if (in_phrase) {
    safe_error(error) = "unterminated phrase quote in cover query";
    return false;
  }
  return flush();
}

// Build a cover-biased extractive summary from a document's covers (in document
// order). Per cover: a window of max(W, cover_length) tokens centered on the
// cover, shifted inward at the body edges to keep the width (clamped to the body
// when it is shorter). Overlapping or touching windows merge; non-contiguous
// extents join with " . . . ". Translates the token extents to text.
std::string cover_summary(std::shared_ptr<Warren> warren,
                          const std::vector<std::pair<addr, addr>> &covers,
                          addr body_start, addr body_end, addr W) {
  if (covers.empty() || body_end < body_start)
    return "";
  std::vector<std::pair<addr, addr>> wins;
  for (const auto &c : covers) {
    addr p = c.first, q = c.second;
    addr cover_len = q - p + 1;
    addr T = std::max<addr>(W, cover_len);
    addr start = p + cover_len / 2 - T / 2;
    addr end = start + T - 1;
    if (end > body_end) {
      start -= (end - body_end);
      end = body_end;
    }
    if (start < body_start) {
      start = body_start;
      end = start + T - 1;
      if (end > body_end)
        end = body_end;
    }
    wins.emplace_back(start, end);
  }
  std::vector<std::pair<addr, addr>> merged;
  for (const auto &w : wins) {
    if (!merged.empty() && w.first <= merged.back().second + 1)
      merged.back().second = std::max(merged.back().second, w.second);
    else
      merged.push_back(w);
  }
  std::string out;
  for (size_t i = 0; i < merged.size(); i++) {
    if (i)
      out += " . . . ";
    out += trim(warren->txt()->translate(merged[i].first, merged[i].second));
  }
  return out;
}

// ---- cover_search enrichment helpers (TASK-5.2 / A2) ----------------------

// The :docno match phrase for one docid -- the SAME form jsonl_get builds: a
// single token, or (... t1 t2 ...) for a multi-token id. (Containment match per
// the A2 Q1 decision, NOT a verified-exact match; documented in the specs.)
std::string docid_phrase(std::shared_ptr<Warren> warren,
                         const std::string &docid) {
  std::vector<std::string> terms = warren->tokenizer()->split(docid);
  if (terms.empty())
    return "";
  if (terms.size() == 1)
    return terms[0];
  std::string p = "(...";
  for (const auto &t : terms)
    p += " " + t;
  p += ")";
  return p;
}

// The ranking/counting container: plain ":item" when nothing is excluded, else
// :item rows that do NOT contain any excluded docid's :docno -- carved DURING
// ranking so excluded rows never appear and top_k fills.
std::string exclusion_container(std::shared_ptr<Warren> warren,
                                const std::vector<std::string> &exclude) {
  std::vector<std::string> parts;
  for (const auto &d : exclude) {
    std::string ph = docid_phrase(warren, d);
    if (!ph.empty())
      parts.push_back("(>> :docno " + ph + ")");
  }
  if (parts.empty())
    return ":item";
  std::string excl;
  if (parts.size() == 1) {
    excl = parts[0];
  } else {
    excl = "(+";
    for (const auto &p : parts)
      excl += " " + p;
    excl += ")";
  }
  return "(!> :item " + excl + ")";
}

// Count the DOCUMENTS in `container` that match `query` -- the :item-style rows
// containing a cover of the query. Exact (Q3): a full enumeration, since no
// precomputed document frequency exists for a cover query.
bool count_container_matches(std::shared_ptr<Warren> warren,
                             const std::string &container,
                             const std::string &query, long *count,
                             std::string *error) {
  *count = 0;
  std::string gcl = "(>> " + container + " " + query + ")";
  auto hopper = warren->hopper_from_gcl(gcl, error);
  if (hopper == nullptr)
    return false;
  addr p, q;
  long n = 0;
  for (hopper->tau(minfinity + 1, &p, &q); p < maxfinity;
       hopper->tau(p + 1, &p, &q))
    n++;
  *count = n;
  return true;
}

// The query's content-term LEAVES (bare words and word* markers), AS WRITTEN,
// deduped first-seen. Operators / parens / :tags are skipped; each word inside a
// quoted phrase is its own leaf. Used to build atom_counts. The query has already
// been validated by cover_rewrite, so no mid-token '*' reaches here.
std::vector<std::string> cover_leaves(const std::string &gcl) {
  std::vector<std::string> out;
  std::set<std::string> seen;
  auto add = [&](const std::string &t) {
    if (t.empty() || is_gcl_nonterm(t))
      return;
    if (seen.insert(t).second)
      out.push_back(t);
  };
  std::string tok, phrase;
  bool in_phrase = false;
  for (char c : gcl) {
    if (c == '"') {
      if (!in_phrase) {
        add(tok);
        tok.clear();
        in_phrase = true;
        phrase.clear();
      } else {
        std::string w;
        for (char pc : phrase) {
          if (pc == ' ' || pc == '\t' || pc == '\n') {
            if (!w.empty()) {
              add(w);
              w.clear();
            }
          } else {
            w.push_back(pc);
          }
        }
        if (!w.empty())
          add(w);
        in_phrase = false;
      }
    } else if (in_phrase) {
      phrase.push_back(c);
    } else if (c == '(' || c == ')' || c == ' ' || c == '\t' || c == '\n') {
      add(tok);
      tok.clear();
    } else {
      tok.push_back(c);
    }
  }
  if (!in_phrase)
    add(tok);
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
  // The cp-native content indexer (docs/indexing.md, doc-6) stores each document
  // as contents + one ":item" annotation and hands back its cp. It does NOT
  // tokenize the docid and creates no ":docno"; instead the docid is paired with
  // cp in a flat (docid<TAB>cp) dump written alongside the burrow, from which the
  // index CLI (TASK-6.3) builds the cp<->docno SQLite map.
  auto indexer = ContentIndexer::make(builder, error);
  if (indexer == nullptr)
    return false;
  std::string flat_name = working->make_name("docid-cp.tsv");
  std::ofstream flat_out(flat_name, std::ios::out | std::ios::trunc);
  if (flat_out.fail()) {
    safe_error(error) = "jsonl_index: cannot create " + flat_name;
    return false;
  }

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
      std::string row_error;
      addr cp;
      if (!indexer->add_document(contents, &cp, &row_error)) {
        // A contentless row -- empty contents, or contents with no indexable
        // tokens -- is handled like a malformed row: skipped, fatal only under
        // --strict. A duplicate docid is NOT detected here; docno uniqueness is
        // enforced when the index CLI builds the SQLite map (TASK-6.3).
        skipped++;
        if (opts.strict) {
          safe_error(error) = row_error + " in " + file;
          return false;
        }
        continue;
      }
      flat_out << docid << '\t' << cp << '\n';
      rows++;
    }
  }
  if (!indexer->finalize(error))
    return false;
  flat_out.close();
  if (flat_out.fail()) {
    safe_error(error) = "jsonl_index: flat dump write failure: " + flat_name;
    return false;
  }

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

bool jsonl_cover_search(std::shared_ptr<Warren> warren, const CoverSpec &spec,
                        CoverResponse *out, std::string *error) {
  out->results.clear();
  out->atom_counts.clear();
  out->total_matches = 0;
  out->unjudged_matches = 0;
  // word* needs a stemmed stream; fail loudly (no silent fallback to exact).
  std::shared_ptr<Stemmer> stemmer;
  if (spec.query.find('*') != std::string::npos) {
    stemmer = burrow_stemmer(warren);
    if (stemmer == nullptr) {
      safe_error(error) =
          "cover_search query uses the word* family marker but this burrow has "
          "no stemmed stream (rebuild the index with --stem porter)";
      return false;
    }
  }
  std::string rewritten;
  if (!cover_rewrite(spec.query, stemmer, &rewritten, error))
    return false;
  if (rewritten.empty())
    return true; // nothing to search -> no hits, zero counts, no atoms
  // Validate up front so malformed GCL is a reported error, not a silent empty.
  auto check = warren->hopper_from_gcl(rewritten, error);
  if (check == nullptr)
    return false;
  // The exclude_docids carve lives in the CONTAINER (built once, reused for
  // ranking and the unjudged count) so excluded rows never appear and top_k fills.
  const std::string container = exclusion_container(warren, spec.exclude_docids);
  // Breadth/novelty signals (exact document counts, Q3). total ignores excludes;
  // unjudged = total - (excluded docids that ACTUALLY match the query) = the
  // query counted within the carved container (NOT total - len(exclude_docids), Q2).
  if (!count_container_matches(warren, ":item", rewritten, &out->total_matches,
                               error))
    return false;
  if (!count_container_matches(warren, container, rewritten,
                               &out->unjudged_matches, error))
    return false;
  // atom_counts: per query leaf, total OCCURRENCES of the feature it resolves to
  // (term shown AS WRITTEN; word* -> the family feature; bare -> exact). Q4.
  for (const auto &leaf : cover_leaves(spec.query)) {
    std::string atom;
    auto star = leaf.find('*');
    if (star != std::string::npos && star == leaf.size() - 1 && star > 0 &&
        stemmer != nullptr)
      atom = resolve_family_atom(stemmer, leaf.substr(0, star));
    else
      atom = leaf; // bare exact (validated: no mid-token '*')
    AtomCount ac;
    ac.term = leaf;
    ac.count =
        (long)warren->idx()->count(warren->featurizer()->featurize(atom));
    out->atom_counts.push_back(std::move(ac));
  }
  // PHASE 1: rank documents by ssr cover density within the (carved) container.
  std::vector<RankingResult> ranked =
      ssr_ranking(warren, rewritten, container, spec.top_k);
  auto docno = warren->hopper_from_gcl(":docno", error);
  int rank = 1;
  for (const auto &r : ranked) {
    CoverHit h;
    h.rank = rank++;
    h.score = r.score();
    addr cp = r.container_p(), cq = r.container_q();
    addr dp = 0, dq = -1;
    if (docno != nullptr) {
      docno->tau(cp, &dp, &dq);
      h.docid = trim(warren->txt()->translate(dp, dq));
    }
    addr body_start = (dq >= 0 ? dq + 1 : cp);
    // PHASE 2: recover THIS document's covers (ssr discards them, returning only
    // the container span) by walking the query hopper within [cp,cq]. This is a
    // localized re-walk over the top_k results -- NOT a second corpus pass.
    std::vector<std::pair<addr, addr>> covers;
    auto qh = warren->hopper_from_gcl(rewritten, error);
    if (qh != nullptr) {
      addr p, q;
      for (qh->tau(cp, &p, &q); p < maxfinity && q <= cq; qh->tau(p + 1, &p, &q))
        if (p >= cp)
          covers.emplace_back(p, q);
    }
    h.summary =
        cover_summary(warren, covers, body_start, cq, (addr)spec.window);
    out->results.push_back(std::move(h));
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
