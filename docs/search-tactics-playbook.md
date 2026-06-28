# Effective Search Tactics — A Playbook for a Search Agent

You retrieve information by issuing queries to one or more search systems (web
search engines and/or bibliographic / Boolean databases). What separates an
expert searcher from a weak one is not a single perfect query — it is a
disciplined loop: **formulate → read the results as evidence → reformulate.**
Follow the tactics below. Bracketed tactics (operators, fields, controlled
vocabulary) apply only when the system supports them; otherwise use the
ranked-engine equivalent noted alongside.

## Operating assumptions

- **The need evolves; expect to iterate.** Treat the first query as a probe, not
  the answer. Plan to reformulate several times and let each result set reshape
  the next query.
- **Vocabulary mismatch is the default failure mode.** Two people pick the same
  word for the same thing only a fraction of the time. Any single phrasing will
  miss relevant material expressed in other words.
- **Apparent completeness is unreliable.** Finding good results is not evidence
  that you found most of them — searchers routinely believe their recall is far
  higher than it actually is. For anything that must be thorough, assume you are
  missing things and search to disprove it.

## 1. Before you query: frame the task

- **Classify the need:** *known-item* (one specific thing), *exploratory*
  (understand a space), or *comprehensive* (find as much relevant material as
  possible). This sets how hard to push for recall.
- **Decompose the need into concepts (facets)** — the 2–4 distinct ideas that
  must all be present. For each facet, gather alternative expressions: synonyms,
  broader and narrower terms, acronyms, variant spellings, common phrasings.
- **Choose the right source for each facet.** The best source is often not a
  general engine; route to it before querying.

## 2. Formulate the first query

- **Building block:** combine facets — *within* a facet, OR its alternatives
  together; *across* facets, require them together (AND / proximity /
  co-occurrence).
- **Lead with the most distinctive facet.** Start from the most specific, least
  ambiguous concept and add constraints only as needed. Over-specifying up front
  hides relevant results.
- **Match the query to the system.** On a Boolean / field-capable database, use
  operators, field restrictions, controlled-vocabulary (subject) terms,
  truncation / wildcards, and proximity. On a ranked web engine, prefer a compact
  natural-language phrasing built from the key terms — distinctive nouns and
  exact phrases beat long Boolean strings.

## 3. Read results as signal (don't just collect them)

- **Follow the scent.** Judge each result from its visible cues (title, snippet,
  source, surrounding terms) *before* opening it, and spend effort where the cues
  predict payoff.
- **Harvest vocabulary from good hits (pearl growing).** When a result is
  on-target, mine it for better query terms — its title words, subject
  tags/keywords, author, and venue — and fold them into the next query. One good
  document is your best source of search terms.

## 4. Reformulate deliberately — match the move to the symptom

- **Too many / too noisy →** *specialize*: add a facet or a more specific term;
  tighten with proximity or fields.
- **Too few / off-target →** *generalize*: drop the weakest facet, move to a
  broader term, or **step back** to the more general question, then re-narrow.
- **Right topic, wrong words →** *substitute terms*: swap in synonyms, related
  terms, or the field's own jargon; try variant spellings/forms and acronym ↔
  expansion.
- **Stuck in the wrong region →** *pivot* to a new query or new source rather
  than endlessly tweaking a dead one.
- **Unsure what the target documents even say →** generate a hypothetical ideal
  answer or passage and search using *its* language. This bridges the gap between
  how questions are worded and how answers are worded.

## 5. Run variations in parallel, not just in sequence

- Issue several differently-worded queries for the same need and **merge the
  results**, rather than trusting one phrasing. Different wordings surface
  different relevant items; the union beats any single query.

## 6. Go beyond the query box (stratagems)

For research-style or comprehensive needs, queries alone are not enough:

- **Citation chasing** — from a strong source, follow its references (backward)
  and the works that cite it (forward); repeat on the best new finds. Citation
  links bypass the vocabulary problem entirely.
- **Snowballing** — alternate between citation chasing and term harvesting until
  little new appears.
- **Author / venue runs** — once you know *who* and *where*, pull more from the
  same authors, groups, journals, or sites.
- **Browse structure** — exploit a source's organization (categories,
  classification, indexes, "related" links) to scan a productive neighborhood.

## 7. Coverage and when to stop

- For comprehensive needs, **search multiple sources and multiple phrasings**,
  and **validate against known items**: if results you already know should appear
  don't, the search is incomplete — fix it.
- **Stopping rule (diminishing returns).** Keep working a line of search while
  new queries keep surfacing new relevant material. When two *different* new
  queries return mostly things you have already seen, that patch is exhausted —
  stop refining it and either move to a new source/region or conclude. Do not
  mistake "I've run out of ideas" for "I've found everything."

## Quick reference (symptom → move)

- Too many results → add a facet / more specific term.
- Too few results → drop a facet / broader term / step back.
- Irrelevant results → substitute terms (synonyms, jargon, spelling/form variants).
- Plateau, same results recurring → switch source or citation-chase.
- Don't know the right words → pearl-grow from a good hit, or search with a hypothetical answer.
- Must be thorough → multiple sources + multiple phrasings + check known items, and assume you're still missing some.
