---
id: TASK-33
title: >-
  Decision: LucindriSearcher — an Indri-query Searcher agent over a Lucindri
  HTTP service
status: To Do
assignee: []
created_date: '2026-07-07 16:05'
updated_date: '2026-07-07 22:04'
labels: []
dependencies: []
priority: medium
ordinal: 47000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
DECISION + scoping task (do we build this, and what's the sketch?). Add a fourth interchangeable ISJ Searcher that queries UWaterloo's Lucindri (Indri query language on Lucene 8.10, Java) instead of Cottontail's GCL engine. Motivation: a genuinely different retrieval model (Indri Dirichlet LM + structured Indri operators) as an A/B alternative to cover/tiered/multitext.

Enabling facts (from a 2026-07-07 deep read of the cloned Lucindri repo, /home/smucker/git-repos/Lucindri, read-only):
- The agent seam already exists (Queryable + SearchEngine Protocol, TASK-18): a new searcher = new Queryable + BaseSearcher subclass + prompt, ZERO base/controller changes (we've done it 3x).
- Docno alignment is FREE: Lucindri's ClimbmixJsonlDocumentParser maps docid->externalId and contents->fulltext -- the SAME docid/contents JSONL schema our indexer reads. Index the same corpus in both -> identical docnos, no mapping layer.
- Lucindri can serve summaries natively (UnifiedHighlighter query-biased passages; recipe in Lucindri docs/query-biased-summaries.md) AND full documents by docno (owner-approved 2026-07-07). So a Lucindri-backed searcher is FULLY SELF-CONTAINED on the Lucindri index -- it needs NO Cottontail burrow for ranking OR text.
- Depends on the Lucindri HTTP service (Lucindri tasks/TASK-0019, Draft): POST /search {query,count}->[{docno,score,summary}], POST /document {docno}->{fulltext}, /healthz. Malformed query -> 4xx with the parser message (maps to our compile-bounce).

Cottontail-side scope (if yes):
1. LucindriQuery(Queryable): tool takes {query: indri string}; execute -> engine.lucindri_search(...); trace/query_string forms.
2. LucindriSearcher(BaseSearcher): prompt teaches the Indri language (quoted terms; #combine, #weight/#wand, #or, #not, #wsum, #max, #syn, proximity #N/#uwN, #token verbatim). Note: #token maps neatly onto the hi-tech/u.s.a. tokenization issues we hit in GCL.
3. LucindriSearchEngine (implements SearchEngine): search() -> POST /search WITH summaries=true (the endpoint's summaries flag is opt-in/default-off per Lucindri TASK-0019; ISJ wants summaries, so the adapter requests them); read() -> POST /document (Lucindri serves full text, so NO delegation to the Cottontail server, NO docno-cp.sqlite dependency); paging/exclude client-side (Lucindri has no exclude -- over-fetch + drop judged); atom_counts dropped (or omitted from the Indri prompt's feedback contract). Share HttpSearchEngine plumbing (httpx, 1h timeout, error->EngineError).
4. Identity: Lucindri speaks docno (string); our controller keys on cp (int). DECISION to record: (a) assign a stable synthetic int id per docno in the adapter (controller unchanged, run-output emits the real docno) -- recommended, keeps the Lucindri searcher decoupled from any Cottontail index; or (b) map docno->cp via a Cottontail sqlite map (only if we want cross-system cp comparability, reintroduces a burrow dependency). doc-5/doc-8 already bless docno-on-the-wire.

GATING STEP before the full build: a prompt-validity SCOUT (like TASK-26 for MultiText) -- can gpt-oss-120b write valid Indri queries? Lucindri's parser / the /search endpoint is the validity oracle. Cheap, and it de-risks the whole thing; if the model can't author Indri reliably, that changes the plan.

Deliverable of THIS task: a go/no-go decision + the pinned identity choice + a scout plan. Implementation (adapter, searcher, prompt, A/B vs cover/multitext) is follow-on work, sequenced after the Lucindri service exists.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Go/no-go decision recorded for a LucindriSearcher, with the identity choice pinned (synthetic-int-per-docno vs docno->cp map)
- [ ] #2 A prompt-validity scout is planned (oracle = Lucindri parser/service) as the gating de-risk step before committing to the adapter/searcher/prompt build
- [ ] #3 Dependency on the Lucindri HTTP service (Lucindri TASK-0019) and the agreed minimal wire contract are captured: /search {query,count,summaries} -> [{docno,score,summary?}] (ISJ sets summaries=true), /document {docno} -> {fulltext}
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Adapter design notes from reviewing the Lucindri service spec (TASK-0019) + docno-lookup fix (TASK-0020), 2026-07-07:
- NO exclude parameter on Lucindri /search. Its wire contract is {query,count,summaries} only. The LucindriSearchEngine must do exclude/paging CLIENT-SIDE: over-fetch (count > needed) and drop already-judged docnos before handing results to the controller. (The controller passes the full judged/exclude set each call; the adapter filters it out itself, since Lucindri is stateless and deterministic.)
- SCORES ARE NEGATIVE. Indri returns Dirichlet-LM negative log-probabilities, best-first (least-negative first). The adapter/controller must NOT assume positive scores. Preserve the server's returned rank order; do not naively re-sort assuming higher-positive-is-better without accounting for sign. RankedEntry.score just carries the value through, which is fine.
- Docno round-trip is exact/verbatim (TASK-0020 makes externalId a non-analyzed keyword), including ClimbMix's shard_NNNNN_MMM underscores; the docno /search returns is exactly what /document accepts. Identity plumbing (synthetic-int-per-docno per this task's decision) is unaffected.

LUCINDRI QUERY LANGUAGE + SEARCHER PROMPT (owner-decided 2026-07-07)

Structure: the LucindriSearcher authors ONE full valid Indri query per turn (a single query string, NOT tiers) — structurally like the plain cover Searcher's loop, not the tiered/multitext ones. Queryable: LucindriQuery {query: str}; LLM tool: submit_indri_query({query}); LucindriSearcher(BaseSearcher) with query_types=[LucindriQuery]; no base/controller changes.

Taught operator subset (deliberately narrow — omit the unintuitive ones):
- Belief/ranking: #combine, #weight, #scoreif, #scoreifnot. OMIT #or, #not, #wsum, #max (strange/unintuitive).
- Concept/proximity: #syn, #1 (teach #1 as THE way to write a phrase), #N, #uwN, #band.
- OMIT #token: the agent never sees the index's surface tokens, so verbatim lookup is useless; an analyzed quoted literal already handles punctuation consistently with the index (same analyzer query-side and index-side).
- All text quoted; Indri escapes are \" and \\ only.
- Critical semantic rule taught: a multi-word quoted literal is a BAG OF SEPARATE WORDS (not a phrase). Use #1("...") for a phrase; INSIDE #syn, wrap any multi-word variant in #1, else its words merge as synonyms of each other.

Prompt is modeled on the MultiTextTieredSearcher librarian (multi-turn, feedback-driven) but emits one full Indri query. Before committing to the build, scout prompt validity like TASK-26 (can gpt-oss author valid Indri?), oracle = the Lucindri parser / /search endpoint.

DRAFT PROMPT (becomes isj/isj_agent/agents/lucindri_searcher.md when built):
----------------------------------------------------------------------
You are an expert research librarian searching a large general-web text collection to find EVERY
document relevant to ONE information need, over several turns.

Each turn you write ONE query in the Indri structured query language and submit it with the
`submit_indri_query` tool. The engine ranks documents by your query and returns the top ones, each with
a short summary; an assessor grades each (0-3) with a reason and hands them back. Documents you have
already seen are excluded automatically. If your query fails to parse you get the parser error back --
fix it and resubmit. Use the feedback to author the next query, and keep going until you have covered
the need. Output ONLY the tool call -- no preamble, no explanation.

THE INDRI QUERY LANGUAGE (the subset you use)

ALL text is QUOTED -- write "climate", never climate. A quoted "..." holds ANALYZED text: a MULTI-WORD
literal is a BAG OF SEPARATE WORDS, not a phrase ("climate change" = the words climate and change,
anywhere). For a PHRASE use #1 (below). Escapes inside a quote are \" and \\, needed only if your
search text itself contains a " or \.

Operators that RANK documents -- use these at the top level:
  #combine("a" "b" ...)   the workhorse: rank documents by how well they match ALL operands.
  #weight(w1 X w2 Y ...)  like #combine but weighted, e.g. #weight(0.7 X 0.3 Y) (weights are numbers).
  #scoreif(C S)           REQUIRE: keep only documents matching C, rank them by S. Wrap your whole
                          query to force a must-have: #scoreif("vaccine" #combine(...)).
  #scoreifnot(C S)        REJECT: keep only documents NOT matching C, rank by S -- to exclude a sense.

Ways to express ONE concept -- use these as operands of the ranking operators (they do not rank alone):
  #syn(X Y ...)           SYNONYMS/variants treated as one term: #syn("car" "automobile" "vehicle").
  #1("word word ...")     exact PHRASE (adjacent, in order): #1("time restricted eating"). THIS is how
                          you write a phrase.
  #N("a" "b")             ordered window: a ... b in order within N tokens (#1 is tightest = phrase).
  #uwN("a" "b" ...)       unordered window: all operands within N tokens, any order -- #uw8("mountain" "rescue").
  #band("a" "b" ...)      Boolean AND: every operand must appear somewhere in the document.

KEY RULE -- phrases inside #syn: a multi-word variant must be wrapped in #1, because a bare multi-word
literal would merge its words as synonyms of each other. Single words go bare:
  #syn(#1("intermittent fasting") #1("time restricted eating") "fasting").

HOW TO BUILD A QUERY
  - One FACET per concept. Make each facet a #syn of that concept's variants; combine the facets with
    #combine (or #weight when some facets matter more).
  - Fixed phrase or name -> #1("..."). "These words near each other" -> #uwN.
  - Must-have term -> wrap everything in #scoreif("term" #combine(...)). Exclude a sense -> #scoreifnot.
  - No special punctuation handling: "u.s.a." is analyzed exactly as the documents were, so it matches.

EXAMPLE

Need: the health effects of intermittent fasting on adults.

#combine(
  #syn(#1("intermittent fasting") #1("time restricted eating") #1("alternate day fasting") #1("5:2 diet"))
  #syn("health" "effect" "benefit" "risk" #1("weight loss") "metabolic")
  #syn("adult" "adults" "participant")
)

Now write the Indri query for the need you are given and submit it with one `submit_indri_query` tool
call. Each following turn, read the results and submit an ADAPTED query.
----------------------------------------------------------------------
<!-- SECTION:NOTES:END -->
