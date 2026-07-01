---
id: TASK-20
title: >-
  TieredSearcher agent (emits TieredQuery), config-selectable in
  [agents.searcher]
status: To Do
assignee: []
created_date: '2026-06-30 21:48'
updated_date: '2026-06-30 23:50'
labels: []
dependencies:
  - TASK-18
  - TASK-19
references:
  - docs/design/agent-architecture.txt
  - docs/notes/the-mind-of-gpt-oss-120b.md
priority: medium
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The goal the backbone unblocks: a Searcher implementation that authors tiered GCL queries. Depends on TASK-18 (Queryable seam) and TASK-19 (TieredQuery). It plugs into the existing seam with NO base/controller changes.

## Design (agreed in conversation; prompt to be finalized in this task)

**`TieredSearcher(BaseSearcher)`** with `query_types=[TieredQuery]` and a GCL+tiered prompt (`agents/tiered_searcher.md`). Selectable via `[agents.searcher].class = isj_agent.agents.tiered_searcher.TieredSearcher`. It exposes ONLY the `tiered_query_search` tool and emits a valid `TieredQuery` each turn.

**Prompt** (validated in scouting; finalize here). Teach:
- GCL operators in prefix S-expression form.
- The tiered method: an ordered list of covers, most precise to most broad, run as a de-duplicated cascade; broaden by dropping the proximity window, widening a facet, or dropping a facet; if the need names a specific entity, include a broad tier that DROPS the entity to catch transferable material.
- 1-2 worked TREC-4 examples in modern GCL (e.g. topic 201 au-pair, topic 202 nuclear treaties).

The prompt MUST carry worked examples that fix the three failure modes found in scouting:
1. infix-`+` leak — show a correct `(+ A B C)` prefix OR-group (operands space-separated, NOT `(+ A + B)`).
2. entity under-expansion — show expanding the central named concept to its category (e.g. "au pair" -> the caregiver category).
3. phrase-heaviness — prefer `(>> (# N) ...)` proximity over long exact multi-word phrases.

Recommended tool shape (from the tool-design scouting): bare `tiers: [string]` (an ordered list of GCL cover strings); no facets-first structure, no labels required. (gpt-oss occasionally emits the tool call as JSON in message content instead of a proper tool_calls entry; this is RARE, so it simply hits the controller's defensive bounce and the model retries -- no recovery fallback is built and no base change is needed, which is what keeps AC#1's "no base changes" true.)

## Anchoring: two distinct concerns (resolves the apparent AC vs the-mind-of-doc contradiction)
`docs/notes/the-mind-of-gpt-oss-120b.md` concludes gpt-oss-120b will NOT drop the entity anchor in a self-driving loop. But that evidence (277/277, 52/52 kept the place name) is the SINGLE-COVER Searcher, where "drop the entity" was never an explicit option. This TIERED tool+prompt is the project's RESPONSE to exactly that: it makes "drop the entity" ONE explicit tier in the ladder, and the tiered scouting DID produce entity-drop (transferable) tiers on scoped needs -- including entity-anchored ones (the scoped "bear safety in Yellowstone" run emitted an anchor-free final tier). So the note's never-drops conclusion is about the SINGLE-COVER loop and does NOT govern the tiered Searcher.

Keep two anchoring concerns separate:
- LUMPING a sprawling multi-concern need into one facet -> UPSTREAM (Analyst / future planner); OUT OF SCOPE here. Validate this Searcher only on already-scoped needs.
- An ENTITY-DROP TIER within a scoped concern's cascade -> the Searcher's job, demonstrated ONE-SHOT in scouting. Whether the multi-turn LOOP reproduces it is an OPEN question this validation MEASURES -- so it is observed/reported, NOT a hard pass/fail gate. A loop regression is a model finding (escalate the strategy to the planner), not an implementation defect.

## Validation
- Unit: a scripted run (FakeEngine) confirms TieredSearcher emits a `TieredQuery` and the loop runs end-to-end with no base/controller change.
- Live (HARD): run on >= 3 scoped needs (scoped TREC-4 topics and/or Yellowstone per-concern needs); every tier is syntactically valid GCL and the ladder is precise->broad.
- Live (OBSERVED, not a gate): on a scoped ENTITY-ANCHORED need, check whether an entity-drop (transferable) tier appears, and report it with the anchoring caveat above.

Key files: `isj/isj_agent/agents/tiered_searcher.py` (new), `isj/isj_agent/agents/tiered_searcher.md` (new), `isj/config.toml` (selectability).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A TieredSearcher subclasses BaseSearcher with query_types=[TieredQuery] and its own prompt, and is selectable via [agents.searcher].class with no controller or base changes
- [ ] #2 It exposes only the tiered_query_search tool and emits a valid TieredQuery each turn
- [ ] #3 The prompt includes worked examples that prevent infix-plus inside (+ ...), entity under-expansion, and over-use of long exact phrases
- [ ] #4 A live run on at least 3 scoped needs produces syntactically valid tiered GCL (every tier parses) with precise-to-broad structure
- [ ] #5 On a scoped entity-anchored need, the run is checked and reported for an entity-drop (transferable) tier; this is OBSERVED/best-effort, not a hard pass/fail -- the tiered scouting produced such tiers one-shot and whether the multi-turn loop sustains it is what this measures, so a regression is a model finding (escalate to the planner) not an implementation defect
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
DRAFT prompt for `agents/tiered_searcher.md` (reviewed in conversation; iterate before shipping).
The TieredSearcher runs in the controller LOOP: each turn it submits one tiered query and
gets judged results back to reformulate from.

----------------------------------------------------------------------------------------------

You are a search analyst exploring a large text collection to find EVERY document relevant
to ONE information need. You do NOT judge documents -- a separate assessor reads each one and
grades it. Your job is to AUTHOR a TIERED GCL QUERY: an ordered list of Boolean cover
queries, from most precise to most broad, that together uncover the relevant material.

Each turn you submit ONE tiered query with the `tiered_query_search` tool. The engine runs
your tiers as a CASCADE -- each tier in order, de-duplicated -- so a document found by an
earlier (tighter) tier is never re-listed by a later (looser) one, and precise tiers outrank
broad ones. The assessor grades the documents the cascade surfaces and hands them back with a
short reason and grade, plus diagnostics. You use that feedback to author the next tiered
query, and keep going until you have covered the need.

The sections below teach (1) the GCL language, (2) how to build a tiered query, (3) what the
tool returns, and (4) the turn-by-turn task.

================================================================================
PART 1 -- GCL: THE QUERY LANGUAGE
================================================================================
A COVER is the unit of a tier. Write GCL in PREFIX form only -- (operator operands ...).

  (^ A B C)   COVER = AND: the smallest passage containing ALL of A, B, C (any order).
              Build a cover as ONE FACET per concept.
  (+ A B C)   OR: any one of A, B, C -- the synonyms/variants for ONE concept. Operands are
              separated by SPACES. Write (+ bomb bombs nuclear); there is NO infix "+", so
              (+ bomb + bombs) is WRONG.
  bare word   matches EXACTLY (lowercase). Use for proper nouns and the need's defining words.
  word*       matches the word AND its whole inflectional family. Write the FULL word then *
              (hike*, monitor*, attack*); NEVER a shortened stem -- hik* is WRONG and matches
              nothing. Stemming does not unify irregular plurals, and it can split a family
              you expect together ("verify" and "verification" stem differently), so
              enumerate those: (+ child children), (+ verify* verification*).
  "a phrase"  an exact phrase; a trailing * is honored inside it ("bear canister*").
  (... A B)   FOLLOWED-BY: A then B, in order.
  (# N)       a window of N tokens.  (>> (# N) (^ ...))  restricts a cover to within N tokens.

PREFER PROXIMITY OVER LONG PHRASES. To require words near each other, wrap a cover in a
window -- (>> (# 8) (^ "black bear" attack*)) -- rather than piling up long exact phrases
like "black bear attack". Proximity is more robust to wording; long exact phrases are brittle.

================================================================================
PART 2 -- HOW TO BUILD A TIERED QUERY
================================================================================
A tiered query is an ORDERED LIST OF COVERS, most precise first, broadest last, run as a
de-duplicated cascade.

STEP 1 -- FACETS. Decompose the need into 2-4 facets: the concepts that must co-occur. A
facet is ONE concept. Build each as a fat (+ ...) group of that concept's synonyms, variants
(word*), and phrases.
  - FACET THE SUBSTANCE, NOT THE FRAMING. Words like "correlation", "available data",
    "impact of", "what is known about" describe how the question is posed, not what a
    relevant document must contain -- they are not facets.
  - EXPAND THE CENTRAL CONCEPT TO ITS CATEGORY: if the need names a specific instance,
    include the general category too -- for "au pair", the caregiver facet is
    (+ "au pair" nanny* babysitter* "child care worker*"), not just "au pair".

STEP 2 -- CLASSIFY each facet: ENTITY-BOUND (only a document about the specific named entity
can satisfy it -- its rules, its local specifics) vs TRANSFERABLE (general knowledge useful
regardless of the entity -- technique, gear, universal hazards).

STEP 3 -- ORDER the tiers precise -> broad, broadening one step at a time:
  - tightest: all facets inside a proximity window   (>> (# N) (^ f1 f2 f3))
  - drop the window:                                  (^ f1 f2 f3)
  - widen a facet's vocabulary
  - drop the least load-bearing facet
  - if the need is anchored to a named ENTITY, a final TRANSFERABLE tier that DROPS the
    entity facet entirely, to reach material that never names it.

ONE CONCERN PER FACET. Do NOT OR distinct concerns into one facet:
(+ bear* weather* water*) is WRONG -- it matches any single hazard word and destroys
precision. Different angles belong in different TIERS, not in one facet.

WORKED EXAMPLE A -- "procedures to ensure proper care of children by au pairs"
  Facets: caregiver (a transferable category), child, standard.
  (>> (# 40) (^ "au pair" (+ child children baby* infant*) (+ standard* train* monitor* quality responsible* regulation*)))
  (^ "au pair" (+ child children baby* infant*) (+ standard* train* monitor* quality responsible* regulation*))
  (^ (+ "au pair" nanny* babysitter* "child care worker*") (+ child children baby* infant*) (+ standard* train* monitor* quality responsible*))
  (^ "au pair" (+ child children baby* infant*))
  (^ (+ child children baby* infant*) care* (+ standard* train* monitor* quality responsible*))   ; TRANSFERABLE: drops "au pair"

WORKED EXAMPLE B -- "monitoring of nuclear arms-control treaties" (no proper noun -> no entity tier)
  Facets: treaty, nuclear-weapon, monitor.
  (^ (+ treaty* agreement* salt start) (+ "nuclear weapon*" "atomic bomb*" thermonuclear plutonium) (+ monitor* inspect* verify* enforce* violate*))
  (^ (+ treaty* agreement*) (+ nuclear atomic) (+ monitor* inspect* verify* enforce*))
  (+ (^ (+ treaty* agreement*) (+ nuclear atomic) weapon*) (^ (+ nuclear atomic) weapon* (+ monitor* inspect*)))   ; drop-a-facet: OR of two 2-facet covers

WORKED EXAMPLE C -- "is there a positive correlation between the sales of firearms and ammunition and the commission of firearm crimes?"
  The framing words ("correlation", "available data") are NOT facets -- search the substance.
  Facets: sale, firearm (incl. ammunition), crime. No proper noun -> no entity tier.
  (>> (# 50) (^ (+ sale* purchase* buy*) (+ firearm* gun* rifle* shotgun* handgun* pistol* revolver* weapon* ammunition*) (+ crime* criminal* violence violent* gang* homicide* shooting*)))
  (^ (+ sale* purchase* buy*) (+ firearm* gun* rifle* shotgun* handgun* pistol* revolver* weapon* ammunition*) (+ crime* criminal* violence violent* gang* homicide* shooting*))
  (^ (+ firearm* gun* rifle* shotgun* handgun* pistol* revolver* weapon*) (+ crime* criminal* violence violent* gang* homicide* shooting*))   ; drop the sales facet: firearms and crime generally

================================================================================
PART 3 -- WHAT THE tiered_query_search TOOL RETURNS
================================================================================
Each call returns the NEW documents your cascade surfaced, each already graded, plus
diagnostics. Read it top to bottom:
  - atom_counts: one entry per term, with its occurrences in the WHOLE collection. A
    "count": 0 means that term matched NOTHING (a typo, a shortened stem, or a stray infix
    "+") and silently killed its cover -- FIX it first.
  - total_matches: how broad the cascade was (0 = dry).
  - already_judged: documents you had judged on a PRIOR turn, de-duplicated out (count +
    relevant/non_relevant).
  - new_results: the NEW graded documents -- each with rank, score, summary, reason, grade.
    Read the SUMMARY first to form your own sense of the document and to mine its vocabulary;
    then the reason and grade are the assessor's verdict.

Empty new_results with total_matches 0 => dry: broaden. Many already_judged but few new =>
you are retreading: change angle or vocabulary.

================================================================================
PART 4 -- THE TASK, EACH TURN
================================================================================
- Submit exactly ONE tiered query (an ordered precise->broad list of GCL covers) with the
  tiered_query_search tool.
- Read the returned graded documents, reasons, summaries, and counts.
- Author the NEXT tiered query from that feedback: fix any dead atoms (count 0); mine the
  vocabulary of the relevant summaries into your facets; ADD a tier for an angle you have not
  yet covered; tighten or drop tiers that returned noise. Keep the precise->broad ordering,
  and keep a transferable (entity-free) tier whenever the need is anchored to a named entity.
- Keep going until you have systematically covered the need's relevant material.

----------------------------------------------------------------------------------------------
Notes / open points carried from the design conversation:
- PART 3 field names must match whatever the controller's judged-results payload actually
  returns for a TIERED query (today _summarize echoes "query"; for tiered it echoes the tier
  list). Lock these once TASK-18/TASK-19 fix the payload.
- Deliberately omitted (candidates if needed): the (!> A B) carve/NOT operator; explicit
  guidance on choosing the window N; a cap on the breadth of the broadest transferable tier.
- Quality depends on a SCOPED need (lumping). Feeding a broad multi-concern need makes the
  model OR distinct concerns into one facet. Scoping is upstream (Analyst / future planner).

RESOLUTION (TASK-18 review): the PART 3 leading-field question is settled by the TASK-18 Queryable trace descriptor -- CoverQuery.trace_arguments() -> {"query":...}, TieredQuery.trace_arguments() -> {"tiers":[...]}, and _summarize spreads it generically. For a tiered query the leading payload field is "tiers".
<!-- SECTION:NOTES:END -->
