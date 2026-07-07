---
id: TASK-33
title: >-
  Decision: LucindriSearcher — an Indri-query Searcher agent over a Lucindri
  HTTP service
status: To Do
assignee: []
created_date: '2026-07-07 16:05'
updated_date: '2026-07-07 22:46'
labels: []
dependencies: []
priority: medium
ordinal: 47000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
DECISION + scoping task (do we build this, and what's the sketch?). Add a fourth interchangeable ISJ Searcher that queries UWaterloo's Lucindri (a structured-query-language search engine on Lucene 8.10, Java; Indri-derived) instead of Cottontail's GCL engine. Motivation: a genuinely different retrieval model (Dirichlet LM + structured query operators) as an A/B alternative to cover/tiered/multitext.

Enabling facts (from a 2026-07-07 deep read of the cloned Lucindri repo, /home/smucker/git-repos/Lucindri, read-only):
- The agent seam already exists (Queryable + SearchEngine Protocol, TASK-18): a new searcher = new Queryable + BaseSearcher subclass + prompt, ZERO base/controller changes (we've done it 3x).
- Docno alignment is FREE: Lucindri's ClimbmixJsonlDocumentParser maps docid->externalId and contents->fulltext -- the SAME docid/contents JSONL schema our indexer reads. Index the same corpus in both -> identical docnos, no mapping layer.
- Lucindri can serve summaries natively (UnifiedHighlighter query-biased passages; recipe in Lucindri docs/query-biased-summaries.md) AND full documents by docno (owner-approved 2026-07-07). So a Lucindri-backed searcher is FULLY SELF-CONTAINED on the Lucindri index -- it needs NO Cottontail burrow for ranking OR text.
- Depends on the Lucindri HTTP service (Lucindri tasks/TASK-0019, Draft): POST /search {query,count}->[{docno,score,summary}], POST /document {docno}->{fulltext}, /healthz. Malformed query -> 4xx with the parser message (maps to our compile-bounce).

Cottontail-side scope (if yes):
1. LucindriQuery(Queryable): tool submit_query takes {query: a full Lucindri query string}; execute -> engine.lucindri_search(...); trace/query_string forms.
2. LucindriSearcher(BaseSearcher): the prompt teaches Lucindri's query language SELF-CONTAINED and NEVER names 'Indri' to the model (it's a variant; naming Indri risks the LLM importing wrong real-Indri behavior). Decided operator subset + drafted prompt are in the Implementation Notes: teach #combine/#weight/#scoreif/#scoreifnot and #syn/#1/#N/#uwN/#band; omit #or/#not/#wsum/#max and #token.
3. LucindriSearchEngine (implements SearchEngine): search() -> POST /search WITH summaries=true (the endpoint's summaries flag is opt-in/default-off per Lucindri TASK-0019; ISJ wants summaries, so the adapter requests them); read() -> POST /document (Lucindri serves full text, so NO delegation to the Cottontail server, NO docno-cp.sqlite dependency); paging/exclude client-side (Lucindri has no exclude -- over-fetch + drop judged); atom_counts dropped (or omitted from the Lucindri prompt's feedback contract). Share HttpSearchEngine plumbing (httpx, 1h timeout, error->EngineError).
4. Identity: Lucindri speaks docno (string); our controller keys on cp (int). DECISION to record: (a) assign a stable synthetic int id per docno in the adapter (controller unchanged, run-output emits the real docno) -- recommended, keeps the Lucindri searcher decoupled from any Cottontail index; or (b) map docno->cp via a Cottontail sqlite map (only if we want cross-system cp comparability, reintroduces a burrow dependency). doc-5/doc-8 already bless docno-on-the-wire.

GATING STEP before the full build: a prompt-validity SCOUT (like TASK-26 for MultiText) -- can gpt-oss-120b write valid Lucindri queries? Lucindri's parser / the /search endpoint is the validity oracle. Cheap, and it de-risks the whole thing; if the model can't author them reliably, that changes the plan.

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
- SCORES ARE NEGATIVE. Lucindri returns Dirichlet-LM negative log-probabilities, best-first (least-negative first). The adapter/controller must NOT assume positive scores. Preserve the server's returned rank order; do not naively re-sort assuming higher-positive-is-better without accounting for sign. RankedEntry.score just carries the value through, which is fine.
- Docno round-trip is exact/verbatim (TASK-0020 makes externalId a non-analyzed keyword), including ClimbMix's shard_NNNNN_MMM underscores; the docno /search returns is exactly what /document accepts. Identity plumbing (synthetic-int-per-docno per this task's decision) is unaffected.

LUCINDRI QUERY LANGUAGE + SEARCHER PROMPT (owner-decided 2026-07-07)

NAMING (important): do NOT call this "Indri" in ANY LLM-facing text — prompt, tool name, or tool description. Lucindri's language is a VARIANT of Indri (quote-only grammar, no field syntax, string-literal splices, etc.); naming "Indri" invites the model to import real-Indri behavior it shouldn't and get confused. Teach the language SELF-CONTAINED (as the MultiText librarian prompt does) so the prompt is the model's only source of truth. In our own prose it's fine to note the language is Indri-derived.

Structure: the LucindriSearcher authors ONE full valid query in Lucindri's query language per turn (a single query string, NOT tiers) — structurally like the plain cover Searcher's loop, not the tiered/multitext ones. Queryable: LucindriQuery {query: str}; LLM tool: submit_query({query}); LucindriSearcher(BaseSearcher) with query_types=[LucindriQuery]; no base/controller changes. (Internal Python names may keep "Lucindri"; only LLM-facing strings avoid "Indri".)

Taught operator subset (deliberately narrow — omit the unintuitive ones):
- Belief/ranking: #combine, #weight, #scoreif, #scoreifnot. OMIT #or, #not, #wsum, #max (strange/unintuitive).
- Concept/proximity: #syn, #1 (teach #1 as THE way to write a phrase), #N, #uwN, #band.
- OMIT #token: the agent never sees the index's surface tokens, so verbatim lookup is useless; an analyzed quoted literal already handles punctuation consistently with the index (same analyzer query-side and index-side).
- All text quoted; escapes are \" and \\ only.
- Three semantic rules taught explicitly: (1) a multi-word quoted literal is a BAG OF SEPARATE WORDS (not a phrase) -- use #1("...") for a phrase, and inside #syn wrap any multi-word variant in #1 or its words merge as synonyms; (2) #band is a SCORED proximity op (unordered window the size of the document; "all of these" for ranking) but NOT a hard filter on its own; (3) #scoreif/#scoreifnot's condition C must be a TERM or concept op (#syn/#1/#uwN/#band -- a "document contains it" match set) -- NOT a belief op (#combine/#weight), whose iterator is the UNION of its operands (DisjunctionDISIApproximation; confirmed in Lucindri code 2026-07-07, parser does NOT enforce it) so it becomes an accidental OR. Filter idioms: require-all = #scoreif(#band(...) S); require-any = #scoreif(#syn(...) S); require-one = #scoreif("term" S); exclude = #scoreifnot(C S).

Prompt is modeled on the MultiTextTieredSearcher librarian (multi-turn, feedback-driven) but emits one full query. Before committing to the build, scout prompt validity like TASK-26 (can gpt-oss author valid Lucindri queries?), oracle = the Lucindri parser / /search endpoint.

DRAFT PROMPT (becomes isj/isj_agent/agents/lucindri_searcher.md when built):
----------------------------------------------------------------------
You are an expert research librarian searching a large general-web text collection to find EVERY
document relevant to ONE information need, over several turns.

Each turn you write ONE query in the structured query language below and submit it with the
`submit_query` tool. The engine ranks documents by your query and returns the top ones, each with a
short summary; an assessor grades each (0-3) with a reason and hands them back. Documents you have
already seen are excluded automatically. If your query fails to parse you get the parser error back --
fix it and resubmit. Use the feedback to author the next query, and keep going until you have covered
the need. Output ONLY the tool call -- no preamble, no explanation.

THE QUERY LANGUAGE

ALL text is QUOTED -- write "climate", never climate. A quoted "..." holds ANALYZED text: a MULTI-WORD
literal is a BAG OF SEPARATE WORDS, not a phrase ("climate change" = the words climate and change,
anywhere). For a PHRASE use #1 (below). Escapes inside a quote are \" and \\, needed only if your
search text itself contains a " or \.

RANKING operators -- these score documents; use them at the top level:
  #combine("a" "b" ...)   the workhorse: rank documents by how well they match ALL operands. Soft -- a
                          document missing some operands still ranks (just lower), it is not excluded.
  #weight(w1 X w2 Y ...)  like #combine but weighted, e.g. #weight(0.7 X 0.3 Y) (weights are numbers).
  #scoreif(C S)           REQUIRE: keep only documents matching condition C, rank them by S. See FILTERS.
  #scoreifnot(C S)        EXCLUDE: keep only documents NOT matching C, rank them by S. See FILTERS.

CONCEPT operators -- these build a searchable concept; use them as operands of the ranking operators
(they do not rank on their own):
  #syn(X Y ...)           SYNONYMS/variants merged into one term -- also your "any of these":
                          #syn("car" "automobile" "vehicle").
  #1("word word ...")     exact PHRASE (adjacent, in order): #1("time restricted eating"). THIS is how
                          you write a phrase.
  #N("a" "b")             ordered window: a ... b in order, at most N-1 tokens between ADJACENT terms
                          (#1 = exact adjacent phrase; the per-gap limit, not a total span).
  #uwN("a" "b" ...)       unordered window: all operands within a span of N tokens, any order --
                          #uw8("mountain" "rescue").
  #band("a" "b" ...)      all operands co-occur somewhere in the document (unordered window the size of
                          the whole document) -- your "all of these." SCORED; not a hard filter on its own.

PHRASES INSIDE #syn: a multi-word variant must be wrapped in #1, or its words merge as synonyms of each
other. Single words go bare: #syn(#1("intermittent fasting") #1("time restricted eating") "fasting").

FILTERS -- hard-require or exclude documents (#scoreif / #scoreifnot)

#scoreif(C S) keeps only documents that MATCH condition C, then ranks the survivors by S.
#scoreifnot(C S) keeps only documents that do NOT match C. S is your normal #combine/#weight ranking.

The condition C must be a TERM or a concept op (#syn / #1 / #uwN / #band) -- something with a plain
"the document contains this" meaning. Do NOT use #combine or #weight as C: a ranking operator matches
the UNION of its operands (any one), so it becomes an accidental OR, not the requirement you meant.

IMPORTANT: the filter C adds NO score -- it only decides membership. Put the required concept in S
(your #combine) as well, or documents that merely mention it once will rank the same as documents that
are actually about it.

Choose C by what you want to require:
  one specific word        -> "vaccine"
  ALL of several words     -> #band("vaccine" "efficacy")
  AT LEAST ONE of several  -> #syn("dog" "cat" "pet")
  an exact phrase          -> #1("climate change")

Examples (note the required concept ALSO appears in the #combine, so ranking rewards it):
  Require the topic:
    #scoreif("vaccine"
             #combine(#syn("vaccine" "vaccination" "immunization") #syn("efficacy" "effectiveness") #syn("booster" "dose")))
  Require BOTH concepts present:
    #scoreif(#band("solar" "efficiency")
             #combine(#syn("solar" #1("solar panel") "photovoltaic") #syn("efficiency" "degradation")))
  Require at least one form of the topic:
    #scoreif(#syn("diabetes" "diabetic")
             #combine(#syn("diabetes" "diabetic") #syn("diet" "nutrition") #syn("management" "control")))
  Exclude the wrong sense (keep docs NOT about the fruit), rank by the rest:
    #scoreifnot(#syn("fruit" "orchard" "pie")
                #combine("apple" #syn("iphone" "mac" "computer")))

BUILDING A QUERY
  - One FACET per concept: a #syn of that concept's variants (single words bare, phrases as #1).
    Combine the facets with #combine (or #weight when some matter more).
  - Fixed phrase or name -> #1("..."). Words that must be near each other -> #uwN.
  - Need a hard must-have or an exclusion? Wrap your #combine in #scoreif / #scoreifnot (see FILTERS).
  - No special punctuation handling: "u.s.a." is analyzed exactly as the documents were, so it matches.

EXAMPLE

Need: the health effects of intermittent fasting on adults.

#combine(
  #syn(#1("intermittent fasting") #1("time restricted eating") #1("alternate day fasting") #1("5:2 diet"))
  #syn("health" "effect" "benefit" "risk" #1("weight loss") "metabolic")
  #syn("adult" "adults" "participant")
)

Now write the query for the need you are given and submit it with one `submit_query` tool call. Each
following turn, read the results and submit an ADAPTED query.
----------------------------------------------------------------------
<!-- SECTION:NOTES:END -->
