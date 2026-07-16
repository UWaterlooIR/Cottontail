#ifndef COTTONTAIL_SRC_SIMPLE_IDX_H_
#define COTTONTAIL_SRC_SIMPLE_IDX_H_

#include <condition_variable>
#include <fstream>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

#include "src/array_hopper.h"
#include "src/compressor.h"
#include "src/core.h"
#include "src/hopper.h"
#include "src/idx.h"
#include "src/simple.h"
#include "src/simple_posting.h"
#include "src/working.h"

namespace cottontail {

class SimpleIdx final : public Idx {
public:
  static std::shared_ptr<Idx> make(const std::string &recipe,
                                   std::shared_ptr<Working> working,
                                   std::string *error = nullptr);
  static bool check(const std::string &recipe, std::string *error = nullptr);
  std::map<fval, addr> feature_histogram();

  virtual ~SimpleIdx(){};
  SimpleIdx(const SimpleIdx &) = delete;
  SimpleIdx &operator=(const SimpleIdx &) = delete;
  SimpleIdx(SimpleIdx &&) = delete;
  SimpleIdx &operator=(SimpleIdx &&) = delete;

private:
  SimpleIdx(){};
  std::string recipe_() final;
  std::unique_ptr<Hopper> hopper_(addr feature) final;
  addr count_(addr feature) final;
  addr vocab_() final;
  void reset_();
  addr posting_bytes_(addr feature) final;
  addr posting_budget_() final;
  void set_posting_budget_(addr bytes) final;
  bool reserve_(const std::set<addr> &needed, std::string *error) final;
  std::shared_ptr<CacheRecord> load_cache(addr feature);
  // Bytes a feature will occupy if materialized, counted toward the budget only
  // when it is "large" (n > large_threshold_); 0 otherwise. Caller holds cache_lock_.
  addr feature_bytes_locked(addr feature);
  // Evict idle large features (in ages_, NOT in `protect`), oldest-first, until
  // large_bytes_ <= target_bytes. Caller holds cache_lock_.
  void evict_idle_locked(addr target_bytes, const std::set<addr> &protect);
  bool multithreaded_ = true;
  std::string posting_compressor_name_;
  std::string posting_compressor_recipe_;
  std::shared_ptr<Compressor> posting_compressor_;
  std::string fvalue_compressor_name_;
  std::string fvalue_compressor_recipe_;
  std::shared_ptr<Compressor> fvalue_compressor_;
  std::string idx_filename_;
  std::string pst_filename_;
  std::vector<IdxRecord> pst_map_;
  std::shared_ptr<Reader> pst_;
  std::mutex cache_lock_;
  std::map<addr, std::shared_ptr<CacheRecord>> cache_;
  std::map<addr, addr> counts_;
  // Posting-memory budget + LRU cache management (TASK-45 + TASK-47). Only "large"
  // features (n > large_threshold_) are tracked/evicted; small ones are negligible
  // and always kept. large_bytes_ is the total decompressed byte cost of the cached
  // large features; budget_bytes_ is the per-query ceiling (set from the server flag;
  // default ~24 GB). reserve() enforces it as admission control; load_cache keeps a
  // lazy byte backstop for any path that doesn't reserve.
  addr stamp_ = 0;
  std::map<addr, addr> ages_;              // LRU access stamp per cached large feature
  addr large_threshold_ = 1024;            // n <= this is "small": never tracked/evicted
  addr large_bytes_ = 0;                    // resident bytes of cached large features
  addr budget_bytes_ = 24000000000L;        // ~24 GB; set_posting_budget() overrides
};

bool interpret_simple_idx_recipe(const std::string &recipe,
                                 std::string *fvalue_compressor_name,
                                 std::string *fvalue_compressor_recipe,
                                 std::string *posting_compressor_name,
                                 std::string *posting_compressor_recipe,
                                 std::string *error = nullptr,
                                 size_t *add_file_size = nullptr);
} // namespace cottontail
#endif // COTTONTAIL_SRC_SIMPLE_IDX_H_
