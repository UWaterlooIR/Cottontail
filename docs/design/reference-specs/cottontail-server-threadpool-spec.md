# Specification: concurrent request handling for `cottontail-jsonl-server`

**Audience:** an implementing agent with full access to this repository.
**Goal:** let the server answer **multiple requests concurrently** by handing each
in-flight request its own cloned `Warren` from a pool, instead of serializing all
queries on one shared `Warren`.

This is the concrete realization of `docs/cottontail-search-server-spec.md` §5
("single-threaded now, pool-ready"). It changes **one class** (`WarrenProvider`)
plus a little startup wiring; **no engine changes and no request-handler changes**.

## 0. Where we are today

`apps/cottontail-jsonl-server.cc` holds one started `Warren` and runs every query
under a global mutex (`WarrenProvider::with` takes a `lock_guard` around the whole
call). cpp-httplib already dispatches requests on a worker-thread pool, so the
mutex is the *only* thing currently serializing them. Removing that serialization
— safely — is the entire task.

## 1. Why clone-per-thread is safe (verified against the code)

The read path was built for concurrency; a `Warren::clone()` is a cheap,
independent, thread-safe **read** handle:

- **`Warren::clone()`** (`src/warren.h`; impl `SimpleWarren::clone_` in
  `src/simple_warren.cc`) shares the safe-to-share members — `working_`,
  `featurizer_`, `tokenizer_`, `idx_` — **clones** `txt_` (so each handle has its
  own translate buffers), nulls the annotator/appender (read-only), and
  **auto-`start()`s when the parent is started**.
- **`SimpleIdx`** is shared across clones via `idx_`, and it is **internally
  synchronized**: a `std::mutex cache_lock_` (`src/simple_idx.h:57`) guards its LRU
  posting cache (`cache_`/`counts_`/`ages_`), and `load_cache()`
  (`src/simple_idx.cc:304`) holds it for the whole fetch — including the disk read
  of a posting on a miss (decompression is offloaded off-lock). So concurrent
  posting access from many clones is safe, and the large (~1 GB, `large_limit_`)
  cache is **shared, not duplicated** per thread.
- **`Txt` / `SimpleTxtIO`** reads via a **`std::fstream` + `seekg`**
  (`src/simple_txt_io.cc`), which is *stateful* and therefore **not shareable**
  across threads — which is exactly why `clone()` gives each handle its **own**
  `Txt` (its own fstream). Text translation thus runs **in parallel** across the
  pool, with no shared mutable state.

> Note: `src/read_gate.h` (an `open`+`pread` reader gate) is **Hazel-only** and is
> *not* on this SimpleWarren path — don't reason about concurrency from it here.

Net: sharing `idx_` is safe (one `cache_lock_` serializes posting fetches), and
everything per-request-mutable (`Txt`'s fstream, the hoppers created per query) is
per-clone. So N cloned warrens run queries in parallel — with posting *fetches*
funneling through `cache_lock_` (see §4) while text reads and ranking run
concurrently.

**Caveat to respect:** `Warren::clone()` itself is not guaranteed thread-safe to
call concurrently — **pre-clone the whole pool once at startup**, single-threaded,
before accepting requests. Never clone inside a request handler.

## 2. The change: `WarrenProvider` becomes a pool

Keep the existing accessor shape — `provider.with([&](auto &w){ ... })` — so **no
handler changes are needed**. Replace the single-Warren+global-mutex body with a
fixed pool of pre-cloned warrens that are checked out per request and returned
(via RAII, so a throwing handler still returns its warren). The mutex is held only
for the brief check-out / check-in, **not** around the query.

```cpp
#include <condition_variable>
#include <mutex>
#include <vector>

class WarrenProvider {
public:
  // Build a pool of `n` started read handles. The original counts as one; the
  // rest are clones. MUST be called at startup, single-threaded, after the
  // original Warren has been start()ed (clone() auto-starts a started parent).
  WarrenProvider(std::shared_ptr<cottontail::Warren> warren, size_t n) {
    free_.push_back(warren);
    for (size_t i = 1; i < n; ++i) {
      auto c = warren->clone();          // pre-clone once, here only
      if (c == nullptr)
        throw std::runtime_error("Warren::clone() failed building the pool");
      free_.push_back(c);
    }
  }

  // Borrow a warren for the duration of fn (blocking if all are in use), run fn
  // with exclusive access to it, and return it — even if fn throws.
  template <class F> auto with(F &&fn) {
    std::shared_ptr<cottontail::Warren> w;
    {
      std::unique_lock<std::mutex> g(mu_);
      cv_.wait(g, [&] { return !free_.empty(); });
      w = free_.back();
      free_.pop_back();
    }
    struct Return {
      WarrenProvider *p;
      std::shared_ptr<cottontail::Warren> w;
      ~Return() {
        {
          std::lock_guard<std::mutex> g(p->mu_);
          p->free_.push_back(w);
        }
        p->cv_.notify_one();
      }
    } ret{this, w};
    return fn(w);   // query runs WITHOUT holding mu_
  }

private:
  std::vector<std::shared_ptr<cottontail::Warren>> free_;
  std::mutex mu_;
  std::condition_variable cv_;
};
```

Notes:
- `with` returns `fn`'s result; the `Return` RAII object checks the warren back in
  when the function returns or throws. (The result object is constructed before
  `ret` is destroyed — fine for the by-value returns the handlers use.)
- If the pool is exhausted, callers **block** until a handle frees, rather than
  failing — backpressure, not errors.

**Pool sizing model — fixed, pre-cloned, not elastic.** The pool is a **fixed set
of `n` warrens, all cloned once at startup** (`n = --threads`); it does not grow or
shrink at runtime, and clones are never created on a request thread. This is
deliberate: `Warren::clone()` is only safe to call single-threaded (§1), so cloning
lazily under load would be a data race — every clone must be made up front. Fixed
size is also a fine default here because clones are **cheap** (they share the idx
cache; each just adds its own `Txt` fstream + buffers), so a fixed `n` gives
predictable memory and a hard concurrency cap. Beyond `n` concurrent requests,
callers **block** in `with()` until a handle frees (backpressure) — the server does
not spawn more warrens. (If you ever wanted "elastic" behavior, you would still
pre-clone a maximum at startup and merely vary how many of that fixed set are
handed out — never clone during a request.)

## 3. Server wiring

In `apps/cottontail-jsonl-server.cc` `main`:

1. **Flag:** add `--threads <n>` (default: a small fixed number, e.g. 4, or
   `std::thread::hardware_concurrency()`). Document it.
2. **Build the pool after `start()`:** `open_burrow()` (`apps/jsonl_core.cc`)
   already `start()`s the warren, so just
   `WarrenProvider provider(warren, threads);` at startup.
3. **Size cpp-httplib's worker pool to match** so the two don't fight:
   ```cpp
   svr.new_task_queue = [threads] {
     return new httplib::ThreadPool(threads);
   };
   ```
   If the httplib pool is larger than the warren pool, extra requests simply block
   in `with()` until a clone frees (correct, but caps real concurrency at
   `--threads`). Keeping them equal is the simple default.
4. Handlers are unchanged — they already call `provider.with(...)`.

## 4. Tuning & resource notes (document in `--help` / the spec)

- **The shared serialization point is `SimpleIdx::cache_lock_`, not `ReadGate`.**
  (`ReadGate` is *Hazel-only*; the SimpleWarren path this server uses never touches
  it — so its `DEFAULT_READERS` has no bearing here.) Every posting fetch goes
  through `SimpleIdx::load_cache` under a single `cache_lock_`
  (`src/simple_idx.cc:304`): a cache **hit** holds it only for a map lookup, but a
  **miss** holds it across the disk read of the compressed posting (decompression
  is offloaded to a detached thread, so that part is *off* the lock). So under
  load, posting fetches funnel through this one lock, while text translation
  (`SimpleTxtIO`, a *per-clone* `std::fstream`) and ranking CPU run in parallel.
  The levers are keeping the working set resident in the idx cache (so misses —
  and their under-lock disk reads — are rare) and scaling out stateless replicas;
  there is no per-file reader knob on this path.
- **Memory.** Clones **share** the big `SimpleIdx` posting cache, so the pool does
  *not* multiply the ~1 GB cache. Per-clone cost is the cloned `Txt` (its own
  `std::fstream` + modest buffers). So `--threads` is cheap memory-wise; size it
  for CPU/I/O, not RAM.
- **Pool size guidance:** start at `--threads = min(hardware_concurrency, ~4-8)`;
  beyond that, returns diminish as `cache_lock_` contention and disk I/O dominate.

## 5. Tests

Add a concurrency test (extend `test/jsonl_server.cc` or a sibling target):

- Start the server with `--threads 4` on a free port over the `test/jsonl/plain`
  burrow.
- Fire **many concurrent requests** (e.g. 50–100 across ~8 client threads using
  `httplib::Client`, mixing `search_text` / `get_document` / `count_matches`).
- Assert **every** response is `200` with the **expected** payload (e.g. the
  `elephants` search always returns `doc-004`; `count_matches "quick fox"` always
  returns 2) — i.e. results are correct and identical regardless of interleaving,
  and the server never crashes or deadlocks.
- Keep `bazel test //test:tests //test:hazel_test //test:jsonl_test
  //test:jsonl_server_test` green.

**Strongly recommended once:** run the concurrency test (or a small in-process
harness that shares one `idx_` across threads) under **ThreadSanitizer**
(`bazel test --config=tsan …`, or `--copt=-fsanitize=thread
--linkopt=-fsanitize=thread`) to confirm the shared-`idx_` path is race-free in
practice, not just by inspection. If TSan flags anything inside `SimpleIdx`/`Txt`,
that's an engine bug to fix or escalate before relying on the pool.

## 6. Acceptance

- `--threads N` runs N pre-cloned warrens; queries execute concurrently (the
  global per-query lock is gone — `with()` only locks check-out/check-in).
- The concurrency test passes; the full gate stays green; (ideally) TSan is clean.
- No changes to request handlers, the JSON contract, or the engine.

## 7. Gotchas

- **Clone only at startup**, single-threaded. Cloning in a handler is a data-race
  risk and defeats the pool.
- **Don't hold the pool mutex around the query** — only around the
  pop/push of the free-list. (The single-threaded v1 deliberately held it around
  the query; the whole point here is to stop doing that.)
- Ensure the original warren is **started before** the pool is built (it is, via
  `open_burrow`); clones inherit started state.
- Exhausted pool → callers **block** (backpressure). That's intended; don't turn
  it into an error unless you add an explicit timeout.
- Match the cpp-httplib worker count to `--threads` (step 3) so you don't allocate
  httplib workers that just block waiting for clones.
