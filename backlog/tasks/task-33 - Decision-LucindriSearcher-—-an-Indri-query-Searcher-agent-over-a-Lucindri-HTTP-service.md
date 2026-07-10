---
id: TASK-33
title: LucindriSearcher — an Indri-query Searcher agent over a Lucindri HTTP service
status: To Do
assignee: []
created_date: '2026-07-07 16:05'
updated_date: '2026-07-10 01:03'
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
4. Identity: DOCNO ON THE WIRE -- the agent pipeline (controller, judger, run-output, traces) keys on the docno string (Hit.id, an opaque str) for BOTH engines. The Cottontail engine translates cp<->docno internally via a memoized DocnoMap (config = base_url + burrow), keeping cp private to the C++ server + burrow; the Lucindri engine is docno-native (URL-only). run_output needs no id mapper (see Notes).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Go/no-go decision recorded for a LucindriSearcher, with the identity choice pinned (synthetic-int-per-docno vs docno->cp map)
- [x] #2 A prompt-validity scout is planned (oracle = Lucindri parser/service) as the gating de-risk step before committing to the adapter/searcher/prompt build
- [x] #3 Dependency on the Lucindri HTTP service (Lucindri TASK-0019) and the agreed minimal wire contract are captured: /search {query,count,summaries} -> [{docno,score,summary?}] (ISJ sets summaries=true), /document {docno} -> {fulltext}
- [ ] #4 Docno-on-the-wire refactor: Hit.cp -> Hit.id (str); HttpSearchEngine owns a memoized bidirectional DocnoMap (base_url + burrow); run_output drops its docno_map; the existing Cottontail test suite stays green.
- [ ] #5 Config-selected engine: an [engine] section (class + base_url [+ burrow for Cottontail]) constructs one engine at startup; the controller is unchanged.
- [ ] #6 Directable prompt: BaseSearcher takes an optional prompt-file override (fail-loud if missing) via [agents.<role>].prompt; covered by a test.
- [ ] #7 LucindriQuery (Queryable, tool submit_query) + LucindriSearcher (BaseSearcher) shipping lucindri_searcher.md (= vDefault); unit-tested.
- [ ] #8 LucindriSearchEngine (search + read) to the finalized TASK-0019 wire contract: client-side exclude/paging (re-request), summaries=true, negative scores preserved, 400->EngineError, 200-empty->empty result, 404-doc->None, /healthz startup poll (fail-fast), optional counts omitted; unit-tested with mocked httpx.
- [ ] #9 (gated) live end-to-end run + A/B vs cover/multitext by docs-judged, against a running Lucindri server + a Lucindri-built index of the same corpus.
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
DETAILED IMPLEMENTATION PLAN (LucindriSearcher). Status: FOR REVIEW. Live end-to-end is
GATED on a running Lucindri service + a Lucindri-built index of the same corpus; everything
below is buildable + unit-testable WITHOUT a live server (mocked httpx). See OPEN QUESTIONS
at the end -- several need a decision before coding.

PHASE 0 -- DOCNO ON THE WIRE (rename cp->id + push the cp<->docno shim into the Cottontail
engine) [REFACTORS the live Cottontail path -- existing tests are the regression gate]
  - The agent pipeline keys on the DOCNO STRING for both engines. cp is confined to the
    Cottontail engine and below (C++ server + burrow) and never reaches the controller.
  - protocol/search.py: rename Hit.cp -> Hit.id, typed str (an opaque doc id); fix the comments
    (docno IS the id now; no int on the agent wire).
  - engine/base.py (Protocol): exclude: Sequence[str]; read(id: str). queryable.py: execute(
    exclude: Sequence[str]) + the 3 concrete signatures.
  - controller.py: mechanical rename cp -> id (h.cp -> h.id; judged/seen/again keyed on str;
    emit(..., id=...)); logic unchanged (already id-agnostic).
  - engine/http.py (HttpSearchEngine = the Cottontail adapter): construct from base_url + burrow;
    open a bidirectional, MEMOIZED DocnoMap (<burrow>/docno-cp.sqlite). search(): map each C++
    hit cp -> docno, return Hit(id=docno). read(id): docno -> cp -> get_document. exclude=
    [docnos]: docno -> cp before cover_search. An in-process memo dict makes recurring docs +
    the exclude translation ~free.
  - run_output.py: DELETE the docno_map param + resolve()/_rewrite_cp machinery; the ids are
    already docnos for every engine -> write them directly (on-disk field: docno). cli.py drops
    build_docno_map + the write_run(docno_map=) wiring.
  - This shifts the Cottontail run/trace on-disk id from cp -> docno uniformly (the portable
    form we always wanted). Regression gate: update + keep green the tests that asserted int cps.

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
      * synthesize SearchResponse: results -> Hit(rank, score, id=docno, summary). Lucindri
        returns no counts, so total_matches / unjudged_matches are SYNTHESIZED (see OPEN Q3)
        and atom_counts = [] (Lucindri has none; the prompt must not promise them).
      * negative Dirichlet-LM scores pass through as-is; preserve server rank order.
  - read(id): POST /document {docno: id}; 200 -> fulltext (incl "" for an empty body);
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
    A mismatched engine<->searcher pairing is the operator's responsibility (no guard).
    Identity resolution lives INSIDE each engine (Phase 0): the Cottontail engine is built from
    base_url + burrow and owns a memoized DocnoMap (cp<->docno); the Lucindri engine takes just
    base_url and is docno-native. Nothing downstream (controller, run_output) maps ids.
    LucindriSearchEngine implements search()+read(); tiered_search/multitext_search are
    Cottontail-only and are stubbed (never called for a LucindriQuery).
  - run_output.py: no id mapping (removed in Phase 0 -- ids are docnos for all engines).
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

======================= DECISIONS (all resolved, owner 2026-07-10) =======================
Q1 (engine selection) -- RESOLVED (owner, 2026-07-10): config-selected engine. An [engine]
   section names the class + its base_url; cli.py constructs that one engine at startup; the
   controller is untouched (already talks only to the SearchEngine interface). Each engine
   takes just a URL. No pairing guard (see Q2).
Q2 (searcher<->engine pairing) -- RESOLVED (owner, 2026-07-10): NO guard. A mismatched
   engine<->searcher config is the operator's responsibility, out of our hands.
Q3 (missing counts) -- RESOLVED: make total_matches, unjudged_matches, AND atom_counts all
   OPTIONAL (None). The Lucindri adapter OMITS all three; the controller guards on presence and,
   when absent, neither fakes nor surfaces them (not in the trace, not in the Searcher feedback).
   Safe: none drive control flow, and the Lucindri prompts never describe the return JSON.
   Change: optional fields on SearchResponse + presence guards in controller/_summarize/emit.
Q4 (paging/dry model) -- RESOLVED: stateless re-request. The paging LOOP is already the agent's
   (fetch fetch_k=200 -> wave through in memory -> refill per batch); the adapter only replicates
   the per-fetch part: request count = |consumed| + top_k, drop consumed, return the next top_k;
   dry = fewer than top_k fresh. Requery cost is amortized by the 200-batch (re-rank per batch,
   not per wave) -- parity with Cottontail, no regression.
Q5 (run-output field naming) -- RESOLVED (owner, 2026-07-10): moot under Option B. run_output
   has no mapper; the ids are docnos for every engine, written directly (on-disk field: docno).
Q6 (server lifecycle) -- RESOLVED: operator-launched. The ISJ config points
   [lucindri_http_json_server] base_url at an already-running server; the adapter polls /healthz on
   startup and, if it is not reachable/ready, FAILS FAST with a clear message and quits (no
   auto-spawn, no silent degradation).
Q7 (task scoping) -- RESOLVED: implement UNDER TASK-33. It ceased to be a decision task -- it IS
   the implementation task now (retitled; implementation ACs added; the original decision ACs stay
   checked as completed preliminaries). One task, with the live end-to-end + A/B as a GATED final
   AC (needs a running Lucindri server + a Lucindri-built index of the same corpus).
Q8 (id design) -- RESOLVED (owner, 2026-07-10): DOCNO ON THE WIRE (Option B). The agent id is
   a uniform str docno; rename Hit.cp->Hit.id; the cp<->docno shim moves INTO the Cottontail
   engine (memoized DocnoMap, base_url+burrow); run_output loses its mapper. This REFACTORS the
   live Cottontail path (run/trace id shifts cp->docno) -- existing tests are the regression gate.
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

IDENTITY (pinned -- AC#1): DOCNO ON THE WIRE at the agent layer. The whole agent pipeline
(controller, judger, run-output, traces) keys on the DOCNO STRING for BOTH engines; the id
field is a plain str -- rename Hit.cp -> Hit.id (an opaque doc id; no int on the agent wire).
Each engine owns its native id space and translates at its OWN boundary:
  - Cottontail (HttpSearchEngine): holds a bidirectional, MEMOIZED DocnoMap opened from the
    burrow's docno-cp.sqlite. It maps cp->docno on search results, and docno->cp on read() and
    on the exclude list, before/after calling the C++ server (which still speaks cp). cp is a
    PRIVATE detail of this engine and below (a cheap int in the hot path) and never reaches the
    controller. Cottontail engine config = base_url + burrow.
  - Lucindri (LucindriSearchEngine): docno-native already; URL-only (base_url); no map.
Consequence: run_output needs NO id resolver/rewriter -- the ids are already docnos for every
engine, so it writes them directly (on-disk field: docno). This is the docno-on-the-wire design
retrofitted at the right layer: cp stays where it is cheap (C++ server + burrow), docno is used
where it is meaningful (the agent).
SUPERSEDES the earlier synthetic-int pin AND its int|str-union refinement: the agent id is
uniformly a str docno, and the cp<->docno translation lives INSIDE the Cottontail engine, not in
run_output. Implementation: (a) rename Hit.cp->Hit.id (str) across protocol / controller /
queryable / tests; (b) HttpSearchEngine gains the memoized DocnoMap + burrow config and does the
translation; (c) run_output drops its docno_map param + resolve()/_rewrite_cp machinery. This
REFACTORS the live Cottontail path (its run/trace on-disk id shifts cp->docno uniformly) --
existing tests are the regression gate.
doc-5 / doc-8 already bless docno-on-the-wire.

FOLLOW-ON (implementation, gated on the Lucindri TASK-0019 service): build LucindriQuery /
LucindriSearcher / LucindriSearchEngine per the scope, wire the directable-prompt config,
and A/B vs cover / multitext.
<!-- SECTION:NOTES:END -->
