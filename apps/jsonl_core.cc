#include "apps/jsonl_core.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <set>
#include <string>
#include <unordered_set>
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
// max_words (0 = uncapped) caps the WHOLE summary to that many tokens: a window
// wider than the cap is anchored at its cover's START (not centered) and the total
// is bounded across covers; any cut extent ends with " ...". Capping the token
// extents before translate() avoids materializing a huge cover span.
std::string cover_summary(std::shared_ptr<Warren> warren,
                          const std::vector<std::pair<addr, addr>> &covers,
                          addr body_start, addr body_end, addr W, addr max_words) {
  if (covers.empty() || body_end < body_start)
    return "";
  std::vector<std::pair<addr, addr>> wins;
  std::vector<bool> cut; // this window was truncated -> show a trailing " ..."
  for (const auto &c : covers) {
    addr p = c.first, q = c.second;
    addr cover_len = q - p + 1;
    addr T = std::max<addr>(W, cover_len);
    if (max_words > 0 && T > max_words) {
      // Too long for the cap: anchor at the COVER START and show max_words tokens,
      // marking it truncated (the rest of the cover is cut).
      addr start = p;
      addr end = std::min<addr>(p + max_words - 1, body_end);
      wins.emplace_back(start, end);
      cut.push_back(true);
      continue;
    }
    // Fits: a T-token window centered on the cover, shifted inward at the edges.
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
    cut.push_back(false);
  }
  std::vector<std::pair<addr, addr>> merged;
  std::vector<bool> merged_cut;
  for (size_t i = 0; i < wins.size(); i++) {
    if (!merged.empty() && wins[i].first <= merged.back().second + 1) {
      merged.back().second = std::max(merged.back().second, wins[i].second);
      merged_cut.back() = merged_cut.back() || cut[i];
    } else {
      merged.push_back(wins[i]);
      merged_cut.push_back(cut[i]);
    }
  }
  // Cap the WHOLE summary to max_words tokens across the merged extents (applied to
  // the token extents, before translate(), so a huge cover is never materialized).
  if (max_words > 0) {
    addr budget = max_words;
    size_t keep = 0;
    bool dropped = false;
    while (keep < merged.size()) {
      addr len = merged[keep].second - merged[keep].first + 1;
      if (len <= budget) {
        budget -= len;
        keep++;
        if (budget == 0 && keep < merged.size()) {
          dropped = true;
          break;
        }
      } else { // cut this extent to fit the remaining budget
        merged[keep].second = merged[keep].first + budget - 1;
        merged_cut[keep] = true;
        keep++;
        dropped = (keep < merged.size());
        break;
      }
    }
    if (dropped)
      merged_cut[keep - 1] = true;
    merged.resize(keep);
    merged_cut.resize(keep);
  }
  std::string out;
  for (size_t i = 0; i < merged.size(); i++) {
    if (i)
      out += " . . . ";
    out += trim(warren->txt()->translate(merged[i].first, merged[i].second));
    if (merged_cut[i])
      out += " ...";
  }
  return out;
}

// ---- cover_search ranking (cp-native, one pass: rank + match counts) -------

// A ranked :item container: its cp (start), cq (end), and ssr cover-density score.
struct CoverRanked {
  addr cp = 0;
  addr cq = 0;
  double score = 0.0;
};

// One cp-native pass (doc-6 section 4): walk the query hopper and the :item
// container hopper once over the PUBLIC Hopper API -- mirroring ssr's recurrence
// (score += 1/(K + q - p), K = ssr's default 42) -- keeping the top `depth`
// containers by score (over-fetched for the exclude cp post-filter), and counting
// matches as a BYPRODUCT of the same pass: total_matches as each matching
// container closes, unjudged_matches for those whose cp is not in `exclude`. Does
// NOT call ssr_ranking and touches no src/ file. Ranked containers are returned
// in score-descending order.
bool cover_ranking(std::shared_ptr<Warren> warren, const std::string &query,
                   size_t depth, const std::unordered_set<addr> &exclude,
                   std::vector<CoverRanked> *ranked, long *total_matches,
                   long *unjudged_matches, std::string *error) {
  const double K = 42.0; // ssr default (smoothed 1/(K + q - p))
  ranked->clear();
  *total_matches = 0;
  *unjudged_matches = 0;
  auto hopper = warren->hopper_from_gcl(query, error);
  if (hopper == nullptr)
    return false;
  auto chopper = warren->hopper_from_gcl(":item", error);
  if (chopper == nullptr)
    return false;
  // Bounded min-heap (smallest score on top) of the top `depth` containers.
  auto lower_score = [](const CoverRanked &a, const CoverRanked &b) {
    return a.score > b.score;
  };
  std::vector<CoverRanked> heap;
  auto close_container = [&](addr cp, addr cq, double score) {
    if (score <= 0.0)
      return; // not a matching container (no cover accumulated)
    (*total_matches)++;
    if (exclude.find(cp) == exclude.end())
      (*unjudged_matches)++;
    if (depth == 0)
      return;
    if (heap.size() < depth) {
      heap.push_back({cp, cq, score});
      std::push_heap(heap.begin(), heap.end(), lower_score);
    } else if (score > heap.front().score) {
      std::pop_heap(heap.begin(), heap.end(), lower_score);
      heap.back() = {cp, cq, score};
      std::push_heap(heap.begin(), heap.end(), lower_score);
    }
  };
  addr p, q, cp, cq;
  hopper->tau(minfinity + 1, &p, &q);
  chopper->rho(q, &cp, &cq);
  double score = 0.0;
  while (p < maxfinity && cq < maxfinity) {
    if (p < cp) {
      hopper->tau(cp, &p, &q);
    } else if (q > cq) {
      close_container(cp, cq, score);
      score = 0.0;
      chopper->rho(q, &cp, &cq);
    } else {
      score += 1.0 / (K + q - p);
      hopper->tau(p + 1, &p, &q);
    }
  }
  close_container(cp, cq, score); // flush the last open container
  std::sort(heap.begin(), heap.end(),
            [](const CoverRanked &a, const CoverRanked &b) {
              return a.score > b.score; // descending by score
            });
  *ranked = std::move(heap);
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
  // as text + one ":item" annotation and hands back its cp. It does NOT tokenize
  // the docno and creates no ":docno"; instead the docno is paired with cp in a
  // flat (docno<TAB>cp) dump written alongside the burrow, from which the index
  // CLI (TASK-6.3) builds the cp<->docno SQLite map.
  auto indexer = ContentIndexer::make(builder, error);
  if (indexer == nullptr)
    return false;
  std::string flat_name = working->make_name("docno-cp.tsv");
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
      std::string docno, text;
      try {
        json j = json::parse(line);
        if (!j.contains(opts.docno_field) || !j.contains(opts.text_field) ||
            !j[opts.docno_field].is_string() ||
            !j[opts.text_field].is_string()) {
          skipped++;
          if (opts.strict) {
            safe_error(error) = "row missing/!string " + opts.docno_field +
                                "/" + opts.text_field + " in " + file;
            return false;
          }
          continue;
        }
        docno = j[opts.docno_field].get<std::string>();
        text = j[opts.text_field].get<std::string>();
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
      if (!indexer->add_document(text, &cp, &row_error)) {
        // A contentless row -- empty text, or text with no indexable tokens --
        // is handled like a malformed row: skipped, fatal only under --strict.
        // A duplicate docno is NOT detected here; docno uniqueness is enforced
        // when the index CLI builds the SQLite map (TASK-6.3).
        skipped++;
        if (opts.strict) {
          safe_error(error) = row_error + " in " + file;
          return false;
        }
        continue;
      }
      flat_out << docno << '\t' << cp << '\n';
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

  hits->clear();
  int rank = 1;
  for (const auto &r : ranked) {
    Hit h;
    h.rank = rank++;
    h.score = r.score();
    h.cp = r.container_p(); // cp-native: the document's working identity
    h.best_passage.start = r.p();
    h.best_passage.end = r.q();
    h.best_passage.text =
        truncate(warren->txt()->translate(r.p(), r.q()), spec.snippet_chars);
    if (spec.full_text) {
      h.full_text = warren->txt()->translate(r.container_p(), r.container_q());
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
  // ONE cp-native pass (doc-6 section 4): rank plain :item -- over-fetching
  // depth = top_k + |exclude| so the exclude cp post-filter still fills top_k --
  // and count total_matches / unjudged_matches as a byproduct of the same pass.
  std::unordered_set<addr> exclude(spec.exclude.begin(), spec.exclude.end());
  std::vector<CoverRanked> ranked;
  if (!cover_ranking(warren, rewritten, spec.top_k + exclude.size(), exclude,
                     &ranked, &out->total_matches, &out->unjudged_matches, error))
    return false;
  // cp POST-FILTER: drop excluded hits, keep top_k survivors, build summaries.
  int rank = 1;
  for (const auto &r : ranked) {
    if (out->results.size() >= spec.top_k)
      break;
    if (exclude.find(r.cp) != exclude.end())
      continue;
    CoverHit h;
    h.rank = rank++;
    h.score = r.score;
    h.cp = r.cp;
    // PHASE 2: recover THIS document's covers (cover_ranking returns only the
    // container span) by walking the query hopper within [cp,cq]. This is a
    // localized re-walk over the survivors only -- NOT a second corpus pass.
    std::vector<std::pair<addr, addr>> covers;
    auto qh = warren->hopper_from_gcl(rewritten, error);
    if (qh != nullptr) {
      addr p, q;
      for (qh->tau(r.cp, &p, &q); p < maxfinity && q <= r.cq;
           qh->tau(p + 1, &p, &q))
        if (p >= r.cp)
          covers.emplace_back(p, q);
    }
    // Summarize only the BEST K covers (K = max_covers, >= 1): the K tightest
    // (smallest span q-p; ties -> earlier position), then put them back in document
    // order so the snippet reads left to right. K=1 gives a single focused window;
    // K>1 reuses cover_summary's overlap-merge and " . . . " join over just those K.
    size_t k = std::max<size_t>(1, spec.max_covers);
    if (covers.size() > k) {
      auto tighter = [](const std::pair<addr, addr> &a,
                        const std::pair<addr, addr> &b) {
        addr sa = a.second - a.first, sb = b.second - b.first;
        return sa != sb ? sa < sb : a.first < b.first;
      };
      std::nth_element(covers.begin(), covers.begin() + k, covers.end(), tighter);
      covers.resize(k);
      std::sort(covers.begin(), covers.end()); // back to document order
    }
    h.summary = cover_summary(warren, covers, r.cp, r.cq, (addr)spec.window,
                              (addr)spec.max_words);
    out->results.push_back(std::move(h));
  }
  return true;
}

// tiered_query_search: run an ordered list of cover tiers as a de-duplicated
// cascade, reusing the cover_search helpers (cover_rewrite / cover_leaves /
// cover_ranking / cover_summary) -- no new ranking math, no native src/ranking.cc
// call. atom_counts is the UNION of every tier's leaves; total/unjudged are the
// EXACT distinct union across tiers; each summary is built against the tier that
// surfaced its document; the merged score is tier-monotonic. A single-tier cascade
// reduces exactly to cover_search.
bool jsonl_tiered_query_search(std::shared_ptr<Warren> warren,
                               const TieredSpec &spec, CoverResponse *out,
                               std::string *error) {
  out->results.clear();
  out->atom_counts.clear();
  out->total_matches = 0;
  out->unjudged_matches = 0;
  if (spec.tiers.empty())
    return true; // no tiers -> empty response (parity with an empty cover query)

  // A stemmer is needed if ANY tier uses the word* family marker.
  std::shared_ptr<Stemmer> stemmer;
  bool need_stem = false;
  for (const auto &t : spec.tiers)
    if (t.find('*') != std::string::npos) {
      need_stem = true;
      break;
    }
  if (need_stem) {
    stemmer = burrow_stemmer(warren);
    if (stemmer == nullptr) {
      safe_error(error) =
          "tiered_query_search uses the word* family marker but this burrow has "
          "no stemmed stream (rebuild the index with --stem porter)";
      return false;
    }
  }

  // WHOLE-REQUEST-FAIL: rewrite + validate EVERY tier up front. A GCL syntax error
  // (or a bad '*') in ANY tier rejects the whole request, NAMING the tier, so the
  // agent fixes the right one. (A count-0 atom is NOT an error: it parses and the
  // tier simply goes dry -- that is what atom_counts=0 diagnoses.)
  std::vector<std::string> rewritten(spec.tiers.size());
  for (size_t i = 0; i < spec.tiers.size(); i++) {
    std::string rw, inner;
    if (!cover_rewrite(spec.tiers[i], stemmer, &rw, &inner)) {
      safe_error(error) =
          "tier " + std::to_string(i) + " (" + spec.tiers[i] + "): " + inner;
      return false;
    }
    if (!rw.empty()) {
      auto check = warren->hopper_from_gcl(rw, &inner);
      if (check == nullptr) {
        safe_error(error) =
            "tier " + std::to_string(i) + " (" + spec.tiers[i] + "): " + inner;
        return false;
      }
    }
    rewritten[i] = rw;
  }

  // atom_counts: the UNION of every tier's content-term leaves, deduped by term
  // (first-seen order), each with its corpus occurrence count. Present on every
  // call regardless of results, so a count of 0 unambiguously means a dead atom.
  std::set<std::string> seen_terms;
  for (const auto &tier : spec.tiers) {
    for (const auto &leaf : cover_leaves(tier)) {
      if (!seen_terms.insert(leaf).second)
        continue;
      std::string atom;
      auto star = leaf.find('*');
      if (star != std::string::npos && star == leaf.size() - 1 && star > 0 &&
          stemmer != nullptr)
        atom = resolve_family_atom(stemmer, leaf.substr(0, star));
      else
        atom = leaf;
      AtomCount ac;
      ac.term = leaf;
      ac.count =
          (long)warren->idx()->count(warren->featurizer()->featurize(atom));
      out->atom_counts.push_back(std::move(ac));
    }
  }

  std::unordered_set<addr> exclude(spec.exclude.begin(), spec.exclude.end());

  // total_matches / unjudged_matches = the EXACT distinct union across tiers: one
  // depth=0 counting pass over the OR of the (non-empty) rewritten tiers. 0 iff
  // every tier is dry. (Not the per-tier sum, which double-counts overlap.)
  std::vector<std::string> nonempty;
  for (const auto &rw : rewritten)
    if (!rw.empty())
      nonempty.push_back(rw);
  if (!nonempty.empty()) {
    std::string orq;
    if (nonempty.size() == 1) {
      orq = nonempty[0];
    } else {
      orq = "(+";
      for (const auto &rw : nonempty)
        orq += " " + rw;
      orq += ")";
    }
    std::vector<CoverRanked> discard;
    long tm = 0, um = 0;
    if (!cover_ranking(warren, orq, 0, exclude, &discard, &tm, &um, error))
      return false;
    out->total_matches = tm;
    out->unjudged_matches = um;
  }

  // The CASCADE: run each tier in order; drop cps in `exclude` and cross-tier
  // duplicates; keep the surfacing tier + that tier's own density per survivor.
  struct Surfaced {
    addr cp = 0;
    addr cq = 0;
    size_t tier = 0;
    double density = 0.0; // the surfacing tier's ssr cover-density score
  };
  std::vector<Surfaced> merged;
  std::unordered_set<addr> merged_cps;
  for (size_t ti = 0; ti < rewritten.size(); ti++) {
    const std::string &rw = rewritten[ti];
    if (rw.empty())
      continue;
    // Over-fetch depth = top_k + |exclude| so the cp post-filter still fills top_k
    // (parity with cover_search paging). Per-tier counts are discarded (the exact
    // union counts were computed above). ALL tiers run every call -- the caller
    // pages by re-invoking with a grown exclude, and atom_counts must stay complete.
    std::vector<CoverRanked> ranked;
    long tm = 0, um = 0;
    if (!cover_ranking(warren, rw, spec.top_k + exclude.size(), exclude, &ranked,
                       &tm, &um, error))
      return false;
    for (const auto &r : ranked) {
      if (exclude.find(r.cp) != exclude.end())
        continue;
      if (!merged_cps.insert(r.cp).second)
        continue; // cross-tier duplicate: an earlier (tighter) tier already had it
      merged.push_back({r.cp, r.cq, ti, r.score});
    }
  }

  // Cap to top_k, then build each hit with a tier-monotonic score and a summary
  // biased to the SURFACING tier's covers (faithful per-tier). Score = density +
  // (last_tier - tier) * TIER_STRIDE, with TIER_STRIDE far larger than any real
  // density, so tier order dominates (tighter tiers score higher) and precise->broad
  // survives the caller's (grade, score) tiebreak; within a tier the density orders
  // docs. A single tier reduces to exactly the density -> identical to cover_search.
  const double TIER_STRIDE = 1e6; // >> any ssr density (a sum of 1/(42+span) terms)
  size_t last = spec.tiers.size() - 1;
  int rank = 1;
  size_t n = std::min(merged.size(), spec.top_k);
  for (size_t i = 0; i < n; i++) {
    const Surfaced &s = merged[i];
    CoverHit h;
    h.rank = rank++;
    h.cp = s.cp;
    h.score = s.density + (double)(last - s.tier) * TIER_STRIDE;
    // Recover the surfacing tier's covers within [cp,cq] (a localized re-walk over
    // this survivor only, NOT a corpus pass) -- exactly cover_search's phase 2.
    std::vector<std::pair<addr, addr>> covers;
    auto qh = warren->hopper_from_gcl(rewritten[s.tier], error);
    if (qh != nullptr) {
      addr p, q;
      for (qh->tau(s.cp, &p, &q); p < maxfinity && q <= s.cq;
           qh->tau(p + 1, &p, &q))
        if (p >= s.cp)
          covers.emplace_back(p, q);
    }
    size_t k = std::max<size_t>(1, spec.max_covers);
    if (covers.size() > k) {
      auto tighter = [](const std::pair<addr, addr> &a,
                        const std::pair<addr, addr> &b) {
        addr sa = a.second - a.first, sb = b.second - b.first;
        return sa != sb ? sa < sb : a.first < b.first;
      };
      std::nth_element(covers.begin(), covers.begin() + k, covers.end(), tighter);
      covers.resize(k);
      std::sort(covers.begin(), covers.end());
    }
    h.summary = cover_summary(warren, covers, s.cp, s.cq, (addr)spec.window,
                              (addr)spec.max_words);
    out->results.push_back(std::move(h));
  }
  return true;
}

bool jsonl_get(std::shared_ptr<Warren> warren, addr cp, std::string *text,
               bool *found, std::string *error) {
  *found = false;
  text->clear();
  // cp-native: cp is an :item container start (from search). Recover the span end
  // cq from the :item container at cp, then translate the whole body. No docno.
  auto item = warren->hopper_from_gcl(":item", error);
  if (item == nullptr)
    return false;
  addr p, q;
  item->tau(cp, &p, &q);
  if (p != cp || p >= maxfinity)
    return true; // cp is not an :item start -> not found (not an error)
  *found = true;
  *text = warren->txt()->translate(cp, q);
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
