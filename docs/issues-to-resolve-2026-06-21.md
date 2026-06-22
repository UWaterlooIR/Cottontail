# Issues to Resolve — June 21, 2026

Output of a deep semantic read of the open **cp-native** specifications (decision
**doc-6**; `docs/indexing.md`; TASK-5 umbrella + subtasks; TASK-6.1/6.2/6.3) after
the cp-native re-spec. These are logic gaps, cross-task contract mismatches, and
implementability concerns — not the stale-term issues already fixed.

Status legend: 🔴 needs a decision · 🟠 spec defect (fixable) · 🟡 under-specified ·
⚪ gap / confirmation.

---

## ✅ 1. How does C2 (the Python client) reach the SQLite map? — RESOLVED (2026-06-21)

The biggest one. doc-6 moved the `cp → docno` rewrite to **C2** (client-side
Python), but the `cp ↔ docno` SQLite map is built **next to the burrow**, where the
indexer/server live. C2/C3 reach the engine as an **HTTP server (by URL)** — they
do not inherently know the burrow path, and **if the server runs on another machine
the client cannot read the server's SQLite file at all**.

The "C++ SQLite-free, Python rewrites" split therefore silently assumes the client
and the map are **co-located on one filesystem**. That assumption is stated nowhere,
and the map path is not threaded into C3/C2 config.

**Decision needed:** either
- (a) assume co-location and put the map path in the C3 config (the client opens the
  same SQLite file the indexer produced), or
- (b) add a `resolve_docnos(cps) -> docnos` boundary endpoint (which reintroduces a
  server-side map read — in tension with "C++ SQLite-free," though it could be a
  Python sidecar service rather than the C++ engine).

This is a direct consequence of the cp-native pivot that the specs do not yet
confront. (Under doc-5/docno-on-the-wire the server owned the map and this did not
arise.)

**Resolved (2026-06-21): option (a) — co-location.** For this project the corpus is
read, the burrow + SQLite map are built, and the agent(s) run **on one machine with
a shared filesystem**, so the client opens the same SQLite file the indexer produced.

- The HTTP/JSON server exists to keep the burrow **warm** (pooled `warren` clones, no
  per-call warmup) and to serve **many agents concurrently**; it stays **SQLite-free**.
- The `cp ↔ docno` map is **built once at index time, then read-only forever** —
  SQLite's ideal case. **Concurrent readers are unlimited and lock-free** (the
  locking caveats are about *writers*, of which there are none post-build), so
  multiple agents reading the map at once is fine with no coordination.
- The 6.3 reader opens the map **read-only** (`file:<map>?mode=ro`, or `?immutable=1`
  since the file never changes), **one connection per process/thread** (the OS page
  cache shares the file across readers).
- No `resolve_docnos` endpoint is needed; C++ never touches SQLite.

The two concurrency stories stay separate: the **server** handles concurrent *search*
via its thread pool; the **SQLite map** handles concurrent *cp→docno* reads via
read-only connections.

**Spec follow-through (mechanical):** thread the map path into the **C3 config**
(alongside the server URL), and have **C2** open it read-only — folded into fixes
#3/#5/#7 below.

## ✅ 2. Does the trace carry document identities, or just counts? — RESOLVED (2026-06-21)

Three specs disagree:
- The **TASK-5 umbrella** says C2 rewrites `cp → docno` in **results *and* trace**.
- **B2 (5.6) AC #8** trace taxonomy is **all counts** — `exclude_count`, `returned`,
  `total/unjudged_matches` — with **no `cp`s**.
- **C2 (5.8) AC #10** rewrites only `RankedEntry.cp` (the RankedList), **not the
  trace**.

For a "research artifact for later statistics," you usually want to know *which*
documents were returned/judged, not just how many — which argues the trace **should**
carry `cp`s (rewritten to docno on persist, per doc-6). 

**Decision needed:** pick one and align all three:
- (a) trace carries doc identities → B2's trace events gain `cp`-bearing fields
  (e.g. `search.returned = [cp...]`, `judge = [{cp, grade}...]`) and **C2 rewrites
  `cp → docno` in the trace too**; or
- (b) trace stays counts-only → drop "+ trace" from the umbrella's C2 line and leave
  C2's rewrite scoped to the RankedList.

**Resolved (2026-06-21): option (a) — the trace carries document identifiers and is
detailed.** The trace must be *reconstructable*: it records the agent's **requests**
(the search query + top_k/window + the `cp`s excluded), the **results received** (the
returned hits, each with its `cp` + score + summary), the **judgements made** (each
`{cp, grade, reason}`), plus bounces and stops — **each timestamped**. Counts alone
cannot reconstruct a run.

This was the original intent — see the turn-by-turn trace in
`docs/searcher-agent-lessons-June-16-2026.md` §2 ("The loop, concretely — a
turn-by-turn trace") and the `judge` tool recording "a whole search's worth of
verdicts." B2's AC #8 had simplified the doc-bearing fields to counts
(`exclude_count`, `returned`, `recorded count`); that loses the detail. Timestamps
are already specified — each `TraceEvent` carries `ts` (epoch seconds) **and**
`duration_ms` (B2 AC #8) — so the timestamping ask is met; keep it.

**Spec follow-through (mechanical):**
- **B2 (5.6) AC #8** — record the *content*, not counts: the `search` event carries
  the query + top_k + window + the **excluded `cp`s** + total/unjudged_matches +
  atom_counts + the **returned hits (`cp`, score, summary)** + engine latency; the
  `judge` event carries the **actual judgements (`cp`, grade, reason)**.
- **C2 (5.8)** — the `cp → docno` rewrite covers the **trace events too** (expand AC
  #10 beyond `RankedEntry`), so the persisted `intent-NN.trace.jsonl` carries docnos.
  This makes the umbrella's "results **and** trace" correct.

---

## ✅ 3. C2's `write_run` signature cannot do its job — DONE (2026-06-22, commit e4493f5)

C2 (5.8) AC #1/#8 give `write_run` `(Intents, outcomes)`; AC #10 requires it to
rewrite `cp → docno` via the TASK-6.3 SQLite reader — but **nothing passes it the
reader or the map path**. Fix: `write_run` must accept the `cp → docno` map (or an
injected reader). (Ties to #1 — the map path has to come from somewhere.)

## ✅ 4. C2 AC #5 contradicts AC #10 — DONE (2026-06-22, commit e4493f5)

- #5: "C2 is pure (filesystem only)… it persists **whatever** RankedList + events it
  is given." (passthrough)
- #10: "Before persisting, C2 **rewrites** each RankedEntry cp to its docno…"
  (transform)

Reword #5: C2 reads the SQLite map and rewrites `cp → docno`; it is otherwise pure
(no network, no LLM, no Searcher logic, no trace generation).

## ✅ 5. Missing dependencies — DONE (2026-06-22, commit e4493f5)

- **C2 (5.8) → TASK-6.3** (C2 uses the 6.3 SQLite reader).
- **C3 (5.9) → TASK-6.3** (C3's live gate needs a burrow + map built by 6.3, and it
  drives C2's rewrite).

The current dependency graph stops at B2 (5.6) for both.

---

## ✅ 6. Flat-file path convention (6.2 ↔ 6.3) is unpinned — DONE (2026-06-22, commit e4493f5)

TASK-6.2 dumps the flat `(docid, cp)` file "alongside the burrow"; TASK-6.3 reads
"the flat file." They must agree on a concrete name/location. Pin it in both.

## ✅ 7. TASK-6.3's location is vague — DONE (2026-06-22, commit e4493f5)

"the isj uv project **or** a tooling module" — and that choice decides whether C2 can
simply `import` the SQLite reader. Pin where the reader module lives so C2's import
is unambiguous.

---

## ✅ 8. The human "fetch-by-docno" tool is described but unassigned — RESOLVED (2026-06-21)

doc-6 / indexing.md promise "a human/external `docno → cp` fetch is a Python step
(SQLite `docno → cp`) then the C++ get-by-`cp`," and the pieces exist (the 6.3 reader
+ A3's get-by-`cp`), but **no task builds the actual command**. Relatedly, A3's
`cottontail-jsonl-query --get <cp>` is now **cp-only** — useless to a human who only
has a docno — which is by design, but only usable once that Python wrapper exists.

**Decision/scope:** assign the fetch-by-docno helper to a task (a small addition to
6.3, or a new task), or explicitly defer it.

**Resolved (2026-06-21): the CLI reads the map directly.** `cottontail-jsonl-query
--get` accepts a **docno** (the human case) — it reads the `cp ↔ docno` SQLite map
(`docno → cp`) and `translate`s by `cp` — and may also accept a bare `cp` for
programmatic use. This needs only a **read-only SQLite dependency in the C++ build**,
used solely by this boundary fetch; the **hot path (`cover_search`, exclusion) stays
map-free**. The co-located map (issue #1) gives the CLI filesystem access.

- **Owner:** A3 (5.12) — it owns the CLI/server query path; it gains the read-only
  SQLite read for `--get <docno>`. No separate Python wrapper; resolves the gap with
  no new task.
- **doc-6 / indexing.md refine (not reverse):** "C++ stays SQLite-free" becomes "the
  **hot path** stays map-free; the boundary `get_document`-by-docno reads the SQLite
  map." The invariant (hot path off the map) holds.
- **Open sub-question (deferred):** whether `cottontail-jsonl-server` also exposes a
  `get_document`-by-docno *boundary* tool for external docno-only clients (occasional,
  concurrent-read-safe). The agent itself uses get-by-`cp`, so it is a nice-to-have,
  not required — left for later.

## ✅ 9. Confirm: the LLM now juggles bare `cp` integers as the doc handle — CONFIRMED (2026-06-21)

Under cp-native the Searcher's LLM sees results as `{rank, score, cp, summary}` and
references documents by `cp` in its `judge` / `exclude` calls. It follows from doc-6
(cp on the wire) and works — the model reasons from the **summary**; `cp` is just an
opaque token — but it is a conscious UX choice worth a nod: a 64-bit integer is a
clunkier handle for a model than a short docno. (Showing docno to the model would
reintroduce docno on the wire, which cp-native rejects.)

**Confirmed (2026-06-21): accepted.** `cp` as the LLM-facing document handle is fine
— the model reasons from the summary; `cp` is an opaque token for `judge` / `exclude`.
No change.

---

## Suggested handling

**All resolved and applied (commit e4493f5, 2026-06-22).** Decisions 1, 2, 8 and the
mechanical fixes 3-7 (+ all decision follow-throughs) are in the specs. Below is the
record of what was applied:

- **Fix the defects:** 3 (C2 `write_run` takes the map/reader), 4 (C2 #5 vs #10),
  5 (deps C2→6.3, C3→6.3), 6 (pin the flat-file path 6.2↔6.3), 7 (pin 6.3's reader
  location).
- **Apply the decision follow-throughs:**
  - #1 — thread the map path into **C3 config**; **C2** opens it read-only/immutable.
  - #2 — **B2 AC #8** records content (returned hits with `cp`; judgements `{cp,
    grade, reason}`; excluded `cp`s) not counts; **C2** rewrites `cp→docno` in the
    **trace** too.
  - #8 — **A3 (5.12)** gains the read-only SQLite read so `--get <docno>` works;
    **doc-6 / indexing.md** refine "C++ SQLite-free" → "hot-path map-free; the
    boundary get_document-by-docno reads the map."
- **Only open item (deferred):** whether the *server* also exposes a
  `get_document`-by-docno boundary tool (issue #8) — nice-to-have, not required.
