---
id: TASK-33
title: >-
  Decision: LucindriSearcher — an Indri-query Searcher agent over a Lucindri
  HTTP service
status: To Do
assignee: []
created_date: '2026-07-07 16:05'
updated_date: '2026-07-07 18:12'
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
