#ifndef COTTONTAIL_SRC_IDX_H_
#define COTTONTAIL_SRC_IDX_H_

#include <memory>
#include <set>
#include <string>

#include "src/core.h"
#include "src/hopper.h"
#include "src/working.h"

namespace cottontail {

class Idx {
public:
  static std::shared_ptr<Idx> make(const std::string &name,
                                   const std::string &recipe,
                                   std::string *error = nullptr,
                                   std::shared_ptr<Working> working = nullptr);
  static bool check(const std::string &name, const std::string &recipe,
                    std::string *error = nullptr);
  inline std::string recipe() { return recipe_(); }
  inline std::string name() { return name_; }

  inline std::unique_ptr<Hopper> hopper(addr feature) {
    return hopper_(feature);
  };
  inline addr count(addr feature) { return count_(feature); };
  inline addr vocab() { return vocab_(); }
  inline void reset(){reset_();};

  // Posting-memory budget (TASK-47). posting_bytes returns the decompressed byte
  // cost of materializing `feature` (0 for a non-cache Idx). posting_budget is the
  // per-query byte ceiling this Idx enforces (0 = unbounded / no guard).
  // set_posting_budget sets it. reserve(needed) evicts idle (not-in-`needed`) cache
  // to make room for `needed`'s working set, or fails (with *error) if that set
  // alone would exceed the budget; a non-cache Idx accepts everything.
  inline addr posting_bytes(addr feature) { return posting_bytes_(feature); }
  inline addr posting_budget() { return posting_budget_(); }
  inline void set_posting_budget(addr bytes) { set_posting_budget_(bytes); }
  inline bool reserve(const std::set<addr> &needed, std::string *error = nullptr) {
    return reserve_(needed, error);
  }

  virtual ~Idx(){};
  Idx(const Idx &) = delete;
  Idx &operator=(const Idx &) = delete;
  Idx(Idx &&) = delete;
  Idx &operator=(Idx &&) = delete;

protected:
  Idx(){};
  std::shared_ptr<Working> working_;

private:
  virtual std::string recipe_() = 0;
  virtual std::unique_ptr<Hopper> hopper_(addr feature) = 0;
  virtual addr count_(addr feature);
  virtual addr vocab_() = 0;
  virtual void reset_(){};
  // Budget hooks default to "no budget": a plain Idx materializes nothing extra,
  // reports an unbounded budget, and admits every reservation.
  virtual addr posting_bytes_(addr /*feature*/) { return 0; }
  virtual addr posting_budget_() { return 0; }
  virtual void set_posting_budget_(addr /*bytes*/) {}
  virtual bool reserve_(const std::set<addr> & /*needed*/, std::string * /*error*/) {
    return true;
  }
  std::string name_ = "";
};
} // namespace cottontail
#endif // COTTONTAIL_SRC_IDX_H_
