---
id: TASK-33
title: >-
  Decision: LucindriSearcher — an Indri-query Searcher agent over a Lucindri
  HTTP service
status: To Do
assignee: []
created_date: '2026-07-07 16:05'
updated_date: '2026-07-10 00:07'
labels: []
dependencies: []
priority: medium
ordinal: 47000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add a fourth interchangeable ISJ Searcher (alongside cover / tiered / multitext) that queries UWaterloo's Lucindri -- a structured-query-language search engine on Lucene 8.10 (Java; Indri-derived, Dirichlet LM) -- instead of Cottontail's GCL engine. Motivation: a genuinely different retrieval model as an A/B alternative.

DECISION: GO. Build it. Prompt strategy, prompt-configurability, and identity are all decided (see Implementation Notes). The prompt-validity scout is DONE: gpt.oss.120b reliably authors valid queries under the shipped prompt. Implementation is follow-on, gated on the Lucindri HTTP service (Lucindri TASK-0019).

Enabling facts (2026-07-07 read of the cloned Lucindri repo, /home/smucker/git-repos/Lucindri, read-only):
- The agent seam already exists (Queryable + SearchEngine Protocol, TASK-18): a new searcher = new Queryable + BaseSearcher subclass + prompt, with ZERO base/controller changes (done 3x already).
- Docno alignment is FREE: Lucindri's ClimbmixJsonlDocumentParser maps docid->externalId and contents->fulltext -- the SAME docid/contents JSONL schema our indexer reads. Index the same corpus in both -> identical docnos, no mapping layer.
- Lucindri is self-contained on its own index: it serves query-biased summaries (UnifiedHighlighter) AND full documents by docno, so a Lucindri-backed searcher needs NO Cottontail burrow for ranking OR text.
- The Lucindri HTTP service (Lucindri TASK-0019) is IMPLEMENTED (JDK HttpServer + Gson, 13/13 conformance): POST /search {query,count,summaries} -> {results:[{docno,score,summary?}]}, POST /document {docno} -> {docno,fulltext}, GET /healthz. The final wire contract + HTTP-status/error mapping + server startup config are captured in the Implementation Notes -- talk to it exactly per those.

Cottontail-side scope (follow-on build):
1. LucindriQuery(Queryable): tool submit_query takes {query: a full query string}; execute -> engine.lucindri_search(...).
2. LucindriSearcher(BaseSearcher): query_types=[LucindriQuery]; the prompt teaches the query language SELF-CONTAINED and NEVER names "Indri" to the model. Prompt content + configurability: see Implementation Notes.
3. LucindriSearchEngine (implements SearchEngine): search() -> POST /search with summaries=true; read() -> POST /document (Lucindri serves full text, so NO Cottontail server, NO docno-cp.sqlite); paging/exclude CLIENT-SIDE (Lucindri has no exclude -- over-fetch + drop judged); atom_counts omitted. Share HttpSearchEngine plumbing (httpx, 1h timeout, error->EngineError).
4. Identity: an OPAQUE id (int | str) -- the controller keys on a hashable id, not an int per se. Cottontail uses cp (int); Lucindri uses the docno string directly, so results/traces carry docnos with no resolver (see Notes).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Go/no-go decision recorded for a LucindriSearcher, with the identity choice pinned (synthetic-int-per-docno vs docno->cp map)
- [x] #2 A prompt-validity scout is planned (oracle = Lucindri parser/service) as the gating de-risk step before committing to the adapter/searcher/prompt build
- [x] #3 Dependency on the Lucindri HTTP service (Lucindri TASK-0019) and the agreed minimal wire contract are captured: /search {query,count,summaries} -> [{docno,score,summary?}] (ISJ sets summaries=true), /document {docno} -> {fulltext}
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DETAILED IMPLEMENTATION PLAN (LucindriSearcher). Status: FOR REVIEW. Live end-to-end is
GATED on a running Lucindri service + a Lucindri-built index of the same corpus; everything
below is buildable + unit-testable WITHOUT a live server (mocked httpx). See OPEN QUESTIONS
at the end -- several need a decision before coding.

PHASE 0 -- Opaque id (int | str) [shared; touches the live Cottontail path -- keep it green]
  - protocol/search.py: Hit.cp -> Id where `Id = int | str` (a shared alias). Use a STRICT
    pydantic union so a numeric-looking docno is never coerced to int (StrictInt | StrictStr).
  - engine/base.py (SearchEngine Protocol): widen exclude: Sequence[int] -> Sequence[Id] on
    search/tiered_search/multitext_search, and read(cp: int) -> read(cp: Id).
  - protocol/queryable.py: Queryable.execute(exclude: Sequence[Id]); update the 3 concrete
    execute() signatures.
  - controller.py: annotate judged: dict[Id, Verdict], seen: set[Id], again: list[tuple[Id,int]]
    -- ANNOTATIONS ONLY; the logic is already id-agnostic (membership + pass-through).
  - Cottontail path is unaffected at runtime (cp stays int). Regression gate: the full
    existing test suite stays green.

PHASE 1 -- Directable prompt [generalizes to ALL searchers]
  - agents/searcher.py BaseSearcher.__init__: add prompt: str | Path | None = None. If set,
    read the file (resolve a relative path against repo root) and set the INSTANCE
    system_prompt (shadowing the class default); if None, keep the bundled <role>.md.
    FAIL LOUD (raise) if a named prompt file is missing -- no silent fallback.
  - cli.py _build_agent whitelist: add "prompt" for the searcher role; resolve it against
    _REPO_ROOT before passing.
  - config.example.toml: document the optional [agents.searcher] prompt field.
  - Test: prompt=path overrides system_prompt; prompt=None uses the bundled default; a
    missing path raises.

PHASE 2 -- LucindriQuery + LucindriSearcher
  - protocol/queryable.py: LucindriQuery(Queryable), frozen dataclass {query: str},
    tool_name = "submit_query" (NOT "indri"). tool_schema: one string param `query`.
    from_tool_arguments: require a non-empty str (else raise -> BaseSearcher bounces).
    execute -> engine.search(self.query, top_k=, exclude=, window=) (window is ignored by
    the Lucindri engine). trace_arguments {"query": ...}; query_string -> the query.
  - agents/lucindri_searcher.py: LucindriSearcher(BaseSearcher) with
    query_types=[LucindriQuery] and system_prompt loaded from the bundled
    agents/lucindri_searcher.md (already committed = the vDefault prompt). No base changes.
  - Test: schema shape; from_tool_arguments happy/malformed; execute routes to engine.search.

PHASE 3 -- LucindriSearchEngine (the httpx adapter)
  - engine/lucindri.py: implements the SearchEngine Protocol. Shares HttpSearchEngine
    plumbing style (httpx client, configurable timeout, errors -> EngineError). Endpoints
    per the finalized TASK-0019 wire contract (see the task's WIRE CONTRACT note).
  - search(query, top_k, exclude, window):
      * paging/exclude CLIENT-side (Lucindri has no exclude, no cursor). exclude is the
        CURRENT query's consumed ids (per the corrected note). Request
        count = len(exclude) + top_k (Lucindri is stateless/deterministic, so the top
        (len(exclude)+top_k) by rank contain the next top_k unseen), POST /search with
        summaries=true, drop the ids in exclude, keep top_k. "Dry" = fewer than top_k fresh
        returned (list exhausted -> controller breaks on empty results).
      * synthesize SearchResponse: results -> Hit(rank, score, cp=docno, summary). Lucindri
        returns no counts, so total_matches / unjudged_matches are SYNTHESIZED (see OPEN Q3)
        and atom_counts = [] (Lucindri has none; the prompt must not promise them).
      * negative Dirichlet-LM scores pass through as-is; preserve server rank order.
  - read(cp): POST /document {docno: cp}; 200 -> fulltext (incl "" for an empty body);
    404 {error:"unknown docno"} -> None (per the read contract).
  - error mapping: malformed query -> 400 {error} -> EngineError(msg) (controller bounces to
    the LLM). A degenerate/null parse is 200 {results:[]} -> a VALID EMPTY result, NOT an
    error. 405/404-route/400-bad-JSON -> EngineError (adapter bugs). Parse the JSON {error}.
  - startup: poll GET /healthz (200 {ok:true}) before the first search (see OPEN Q6).
  - tiered_search / multitext_search: stub -> raise NotImplementedError (a LucindriQuery
    never calls them; present only for Protocol conformance).
  - Test (mock httpx / a tiny local stub server): search happy path + client-side
    exclude/paging + summaries=true; 400 -> EngineError; 200 empty -> empty result;
    read hit/404; negative scores preserved.

PHASE 4 -- Engine selection + run-output + config
  - Engine selection (RESOLVED): the controller already talks ONLY to the SearchEngine
    interface (queryable.execute(engine) + one engine.read()), so it needs no change.
    Make the engine CONFIG-SELECTED: an [engine] section names the class + its base_url
    (host:port [+ optional timeout_s / api_key_env]); cli.py constructs that ONE engine at
    startup (replacing the hardcoded build_search_engine(config["cottontail_http_json_server"])).
    Each engine is an HTTP/JSON client taking just base_url. A mismatched engine<->searcher
    pairing is the operator's responsibility (no guard). The docno-map asymmetry is NOT an
    engine concern: for a Cottontail engine, build the docno_map from the burrow; for a
    Lucindri engine, docno_map = None (ids already are docnos). LucindriSearchEngine
    implements search()+read(); tiered_search/multitext_search are Cottontail-only and are
    stubbed (never called for a LucindriQuery).
  - run_output.py: for an already-docno id, write it under the `docno` key WITHOUT a
    DocnoMap (see OPEN Q5 for the mechanism). Cottontail path (int cp + sqlite map)
    unchanged.
  - config.example.toml: add [lucindri_http_json_server] base_url (+ optional timeout_s,
    api_key_env); document the searcher/engine pairing.
  - Test: run_output writes docnos for a Lucindri-style (already-docno) outcome; CLI wires
    the Lucindri engine + no docno_map from a Lucindri config.

PHASE 5 -- Docs + finalize
  - running-the-search-stack.md: a Lucindri-searcher subsection (start the Lucindri server,
    point [lucindri_http_json_server] at it, run cottontail-isj with the Lucindri config).
  - bazel/pytest green; check ACs; task-finalization.

GATED (separate, needs the live Lucindri service + its index; outside-repo build/run not yet
authorized): end-to-end live run + the A/B vs cover/multitext by docs-judged.

======================= OPEN QUESTIONS / DECISIONS NEEDED =======================
Q1 (engine selection) -- RESOLVED (owner, 2026-07-10): config-selected engine. An [engine]
   section names the class + its base_url; cli.py constructs that one engine at startup; the
   controller is untouched (already talks only to the SearchEngine interface). Each engine
   takes just a URL. No pairing guard (see Q2).
Q2 (searcher<->engine pairing) -- RESOLVED (owner, 2026-07-10): NO guard. A mismatched
   engine<->searcher config is the operator's responsibility, out of our hands.
Q3 (missing counts): Lucindri /search returns no total_matches / unjudged_matches /
   atom_counts. Proposed: total_matches = hits returned before exclude, unjudged_matches =
   hits after client-side exclude, atom_counts = []. Confirm -- this drives the "N matches"
   the controller surfaces to the LLM and the trace; the Lucindri prompt must not reference
   atom_counts.
Q4 (paging/dry model): confirm the stateless re-request paging (count = |consumed| + top_k,
   drop consumed, dry when fewer than top_k fresh). Acceptable that each refill re-runs the
   query server-side (deterministic, so stable)?
Q5 (run-output field naming): mechanism to write an already-docno id under `docno` with no
   map -- an ids_are_docnos flag on write_run, or a trivial identity DocnoMap? Recommend the
   flag.
Q6 (startup + server lifecycle): assume the Lucindri server is operator-launched and give a
   base_url + a /healthz poll (like the Cottontail server), OR have the agent launch the
   server subprocess? Recommend operator-launched + health poll for v1.
Q7 (task scoping): TASK-33 is scoped as a DECISION task ("implementation is follow-on"). Do
   we execute the implementation UNDER TASK-33, or spin a new implementation task carrying
   this plan (TASK-33 stays the decision of record)? Recommend a new task.
Q8 (opaque-id blast radius): confirm we do the full int|str widening now (Phase 0), accepting
   it touches shared code on the live Cottontail path (kept green by the existing tests),
   rather than a narrower interim.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
STATUS: decision COMPLETE (GO); all three ACs met. Implementation is follow-on,
gated on the Lucindri TASK-0019 HTTP service. This note is the current design of
record. The earlier full-operator prompt draft was scouted and REJECTED (see PROMPT
DECISION); it survives only as scout arm v2 (isj/scouting/lucindri-query/lucindri_prompt_v2.txt)
and in git history -- it is NOT the design.

ADAPTER DESIGN (from the Lucindri service spec TASK-0019 + docno fix TASK-0020, 2026-07-07):
- NO exclude parameter on Lucindri /search (wire contract is {query,count,summaries}).
  The LucindriSearchEngine replicates Cottontail's SERVER-side exclude CLIENT-side:
  over-fetch (count > needed) and drop the ids in the passed `exclude`, returning top_k.
  IMPORTANT -- what `exclude` actually is: the controller passes only the CURRENT query's
  consumed ids (per-query paging dedup, so refills keep descending the ranking), NOT the
  global judged set. Cross-query "already judged" filtering is the CONTROLLER's job and is
  engine-agnostic (controller.py: `h.cp not in judged` gates the Judger; a re-encountered
  judged doc becomes a count-only "revisit") -- the engine/adapter never sees the global
  judged set and may freely re-return a judged doc. So the adapter only mirrors Cottontail's
  per-query paging exclude; Lucindri being stateless/deterministic, it filters deterministically.
- SCORES ARE NEGATIVE: Lucindri returns Dirichlet-LM negative log-probs, best-first
  (least-negative first). Do NOT assume positive scores; preserve the server's rank
  order, do not re-sort assuming higher-positive-is-better. RankedEntry.score carries
  the value through as-is.
- Docno round-trip is exact/verbatim (TASK-0020 makes externalId a non-analyzed keyword),
  including ClimbMix's shard_NNNNN_MMM underscores; the docno /search returns is exactly
  what /document accepts.

WIRE CONTRACT (final -- Lucindri TASK-0019 is IMPLEMENTED, 2026-07-08, 13/13 conformance;
JDK com.sun.net.httpserver + Gson. Code the adapter to these exact paths / methods / fields):
- POST /search  req {query: str, count: int, summaries: bool}. query + count REQUIRED; count
  must be a POSITIVE INTEGER (missing / non-positive / non-integer -> 400). NO server cap on
  count, so the client-side over-fetch for exclude is explicitly safe (Lucene caps its PQ to
  maxDoc). summaries is optional, DEFAULT FALSE -> the adapter MUST send summaries=true.
  Resp {results: [{docno: str, score: number, summary?: str}]}. summary present iff
  summaries=true; with summaries=true EVERY hit has a NON-EMPTY summary (no query-term match
  -> leading-sentence fallback; only an empty fulltext yields "").
- POST /document  req {docno: str} -> {docno: str, fulltext: str}. Unknown docno -> 404
  {error:"unknown docno"} => read() returns None (its contract). Matched-but-empty body ->
  200 {fulltext:""} => return "" (NOT None).
- GET /healthz  -> 200 {ok:true} once the index is open. The adapter/CLI must POLL this on
  startup before the first search (the server warms up while opening the index).
- STATUS -> ADAPTER MAPPING:
    * malformed query (syntax; QueryParseException) -> 400 {error:msg} => raise EngineError(msg);
      the controller bounces it to the LLM (our compile-bounce). Keep msg verbatim.
    * DEGENERATE / null parse (NOT a syntax error, e.g. all-stopword) -> 200 {results:[]} => a
      VALID EMPTY result, NOT an error. Never treat empty results as failure.
    * wrong method on a known path -> 405 (+Allow header); unknown route -> 404; bad JSON /
      missing field -> 400. Those would be adapter bugs (we send POST/GET + fields correctly)
      -> surface as EngineError. EVERY response (incl 400/404/405) carries a JSON {error} body.
- SUMMARIES are STARTUP-configured, not per-request: sentence UnifiedHighlighter, maxPassages
  default 4 (TASK-0022), joined by a single space, capped at --maxSummaryWords, term-based with
  a leading-sentence fallback. The adapter cannot vary passage count per query.
- OPS / CONFIG: the Lucindri server runs SEPARATELY, launched as
    java -jar LucindriServer-2.0-*.jar --index <TASK-0020-built index dir> --port <n>
       [--host 127.0.0.1] [--rule dirichlet:2000] [--stemmer kstem] [--removeStopwords true]
       [--ignoreCase true] [--maxPassages 4]
  The analysis flags (kstem / removeStopwords / ignoreCase) MUST match how that index was built;
  loopback by default; it logs "listening on host:port". ISJ side: add a
  [lucindri_http_json_server] base_url = "http://127.0.0.1:<port>" config key (mirrors
  [cottontail_http_json_server]). Prereqs TASK-0020 (keyword externalId docno) + TASK-0021
  (reactor / 2.0) are LANDED.

SEARCHER STRUCTURE:
- Authors ONE full valid query per turn (a single query string, NOT tiers) -- like the
  plain cover Searcher's loop. Queryable: LucindriQuery {query: str}; LLM tool:
  submit_query({query}); LucindriSearcher(BaseSearcher) with query_types=[LucindriQuery];
  no base/controller changes. (Internal Python names may keep "Lucindri"; only LLM-facing
  strings avoid "Indri".)
- NAMING (important): do NOT call this "Indri" in ANY LLM-facing text (prompt, tool name,
  tool description). The language is a VARIANT of Indri; naming "Indri" invites the model
  to import real-Indri behavior it should not. Teach it SELF-CONTAINED. In our own prose,
  noting it is Indri-derived is fine.

PROMPT DECISION (scout outcome, 2026-07-09) -- SIMPLE WINS:
- Scout: single-turn query-generation probe. gpt.oss.120b, reasoning=medium, temp=0,
  tool_choice=required, over TREC-8 (8 topics) + TREC-RAG-2026 RAG25 dev (22). Tool =
  submit_query({query}); a STRUCTURAL validator (balanced parens, known operators,
  #syn-parent classifier, filter-first counter). Harness + prompts + captured outputs in
  isj/scouting/lucindri-query/ (scout_lucindri_query.py; lucindri_prompt_v{1..5,Default}.txt;
  scout-output-*.txt; rag25-topics-dev.tsv). NOTE: validity here is STRUCTURAL, not the
  live Lucindri parser -- real-parser validation of generated queries is deferred to the
  /search endpoint at build time.
- Results (parse-clean; #syn-as-ranking-operand misuse; filter-first rate):
  - FULL-OPERATOR prompt (#combine/#weight/#scoreif/#syn/#uwN/#band; scout arm v2):
    TREC-8 6/8, RAG25 17/22; #syn misused 13; filter-first 8/8 + 16/22. REJECTED -- the
    model reflexively wraps everything in #scoreif(#band(...)) (a recall risk AND the main
    parse-failure source) and abuses #syn as a facet/ranking operand despite the ban.
  - v3 (facets + #weight core/expansion): TREC-8 8/8, RAG25 21/22.
  - v4 (proximity: #uwN of #syn sets): TREC-8 8/8, RAG25 22/22.
  - vDefault (SIMPLE: quoted words + #1 phrases + #combine; NO #weight/#syn/#uwN/#scoreif):
    TREC-8 8/8, RAG25 22/22. Zero #syn, zero filter-first, zero parse failures.
- DECISION: restrict the DEFAULT language to what the model wields reliably -- quoted
  words, #1 phrases, and #combine. This eliminates the #syn/#scoreif misuse and parse
  fragility by construction. Precision tools (#uwN / #scoreif) survive only as an OVERRIDE
  prompt (v4), never the default.
- SHIPPED DEFAULT: isj/isj_agent/agents/lucindri_searcher.md = the vDefault prompt (copied
  from isj/scouting/lucindri-query/lucindri_prompt_vDefault.txt on 2026-07-09; NOT kept in
  sync -- the package copy is the source of truth from here on). OVERRIDE prompts (owner
  selects via config): lucindri_prompt_v3.txt (facet/#weight), lucindri_prompt_v4.txt
  (proximity).

DIRECTABLE PROMPT (a per-searcher configurable prompt; generalizes to ALL searchers, not
just Lucindri):
- BaseSearcher.__init__ gains optional prompt: str | Path | None = None. If set, read the
  file (resolve relative paths against repo root) and set the INSTANCE system_prompt,
  shadowing the class default; if None, keep the bundled <role>.md (today's behavior --
  backward compatible). No Controller / Queryable change.
- config: [agents.<role>] optional prompt = "<path>" field. cli.py whitelists prompt for
  the searcher role and resolves it against _REPO_ROOT. FAIL LOUD at startup if the named
  prompt file is missing (no silent fallback). Add a test. ~3 files touched:
  agents/searcher.py (base __init__), cli.py, config.example.toml (document the field).

IDENTITY (pinned -- AC#1): OPAQUE id (int | str), NOT a synthetic int. The controller uses
the document id purely as a hashable key -- dict/set membership, the exclude list,
engine.read, and the trace/run-output -- and never does int arithmetic on it, so the id
type widens from int to `int | str` with NO controller LOGIC change. Cottontail keeps cp
(int); the Lucindri adapter sets Hit.cp = the docno STRING directly. Consequences:
  - no synthetic-int interner and no in-memory reverse map in the adapter;
  - the results/trace writers need NO resolver for Lucindri -- the id already IS the docno,
    so write_run persists it as-is; Cottontail is unchanged (cp -> docno via the sqlite
    DocnoMap at write time).
This SUPERSEDES the earlier synthetic-int-per-docno pin (AC#1's parenthetical names the two
options first weighed; opaque-id is strictly simpler and removes the write-time resolver
coupling that synthetic ints would force onto write_run and the trace log). Small edits it
implies:
  (a) type the id as `int | str` (a shared Id alias) on Hit.cp, the SearchEngine Protocol
      (search exclude=, read cp=), and the controller dict/set annotations -- annotations
      only. Use a STRICT union so pydantic never coerces a numeric-looking docno to int.
  (b) run_output currently renames cp->docno only when a DocnoMap is present; for an
      already-docno id, write it under the `docno` key with no map (a small ids_are_docnos
      flag or a trivial identity map).
doc-5 / doc-8 already bless docno-on-the-wire.

FOLLOW-ON (implementation, gated on the Lucindri TASK-0019 service): build LucindriQuery /
LucindriSearcher / LucindriSearchEngine per the scope, wire the directable-prompt config,
and A/B vs cover / multitext.
<!-- SECTION:NOTES:END -->
