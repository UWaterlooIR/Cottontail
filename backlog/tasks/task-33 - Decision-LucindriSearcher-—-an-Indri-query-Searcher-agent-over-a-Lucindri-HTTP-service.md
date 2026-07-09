---
id: TASK-33
title: >-
  Decision: LucindriSearcher — an Indri-query Searcher agent over a Lucindri
  HTTP service
status: To Do
assignee: []
created_date: '2026-07-07 16:05'
updated_date: '2026-07-09 23:15'
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

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
STATUS: decision COMPLETE (GO); all three ACs met. Implementation is follow-on,
gated on the Lucindri TASK-0019 HTTP service. This note is the current design of
record. The earlier full-operator prompt draft was scouted and REJECTED (see PROMPT
DECISION); it survives only as scout arm v2 (isj/scouting/lucindri-query/lucindri_prompt_v2.txt)
and in git history -- it is NOT the design.

ADAPTER DESIGN (from the Lucindri service spec TASK-0019 + docno fix TASK-0020, 2026-07-07):
- NO exclude parameter on Lucindri /search (wire contract is {query,count,summaries}).
  The LucindriSearchEngine does exclude/paging CLIENT-SIDE: over-fetch (count > needed)
  and drop already-judged docnos before returning to the controller. (The controller
  passes the full judged/exclude set each call; the adapter filters, since Lucindri is
  stateless and deterministic.)
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
