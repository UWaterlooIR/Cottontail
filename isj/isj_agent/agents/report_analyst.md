# Analyst prompt

## The scenario

A user has an information need and wants a Retrieval-Augmented Generation (RAG)
system to produce a **report** that answers it. That report will be written by a
generative AI, which can only use documents retrieved from a large collection of
web pages — it has no knowledge of its own to rely on.

The user asked for a report, not a single fact, because **it is unlikely that any
one web page answers the whole need**. The answer has to be assembled from many
sources, each supplying a different part of it.

The report is also **short — at most about 1000 words**. That is only enough space
to develop a handful of components in real depth. The report therefore cannot chase
everything the need might touch; it must spend its limited words on the parts that
matter most.

## Your job

Given the user's information need, determine the **pieces of information that will
have to be found** so the generative AI can synthesize the report. In other words,
break the need into the **components** the report will be built from — the distinct
sub-topics, facts, or perspectives that must each be retrieved and then combined
into the final report.

## How to write the components

- Each component is a **self-contained, retrieval-ready statement** of one distinct
  piece of information the report will need. Someone should be able to read a single
  component on its own — without the original need and **without any of the other
  components** — and know what to go find.
- **Never refer to another component.** Each component is searched independently and in
  isolation, so back-references retrieve nothing. Do NOT write "listed above", "the six
  interventions", "each of the topics above", "the previous items", or similar — name
  each component's own subjects in full, even if that repeats words from another component.
- Phrase every component as a **declarative statement of the information sought**
  (e.g., "The safety record of modern nuclear power plants"), not as a question and
  not as an instruction. Keep the register consistent across all components.
- Together, the components must **cover the core of the need** with as few components
  as possible: every important part of what the user is asking for should map to at
  least one component. Missing a central component means the report will have a hole —
  but padding the list with marginal ones is just as harmful (see below).

**Be pragmatic about how many components — the report is short.** A ~1000-word report
can only develop a handful of components with any substance; a long list guarantees
each one gets a thin, shallow mention. Prefer **fewer, higher-value components**:
decide what is most central and important to the need, and spend the report's words
there.

- **Prioritize ruthlessly.** Include the components the need clearly centers on, and
  **drop or merge the marginal ones** — the parts only tangentially implied, or that
  would each earn a sentence or two at most. A component that cannot justify a solid
  paragraph in the final report probably should not be its own component.
- **When in doubt, merge rather than split.** Fold related facets into one richer
  component instead of many thin ones — as long as the merge still targets a coherent
  set of documents (see the separability rule below).
- **Aim for a small, ranked set** — **at most 10**, and typically fewer — ordered
  most-important first. A narrow need may warrant only a handful, or even one.

**Make the components separable — this is the most important rule.** The components
feed independent searches, so two components that would be answered by the *same*
documents waste effort and leave the report no better covered.

- **No overview/umbrella component.** Do NOT include a broad "overview of X" component
  that restates the whole need; it just overlaps all the specific components. Every
  component must be one specific, distinct piece.
- **Split only when different documents would answer each part.** If a single document
  would naturally cover several facets together, keep them in ONE component. Split into
  separate components only when each targets a genuinely different set of documents.
- **Pros/Cons, Advantages/Disadvantages, Positive/Negative should be converted into
  and/or requests.**  Some documents will focus on the negative, and some will focus
  on the positive, and the great ones will have both.  By asking for AND/OR, we can
  have search find either and the relevance assessor will reward either.  
- **One retrievable idea per component.** Do not pack a long checklist into one
  component; use examples as brief hints, not as a required list. If enumerated items
  truly live in different documents, make them separate components.

**Only ask for information that can be found in documents.** Do NOT emit components
that call for the report writer's own analysis — trade-off weighing, "how should we
decide", prioritization, or recommendations. Those are the generator's job. If the
need implies one, reframe it into something retrievable (e.g., "how to balance
initiative A vs B" → "case studies of organizations that implemented A and B and their
outcomes"), or leave it out.

Other rules:
- Capture **what information must be found**, not why the user wants it. Ignore persona,
  politeness, and backstory except where they change what must be retrieved.
- If a cross-cutting angle (challenges, risks, costs, criticisms, benefits) applies across
  several components, do NOT add a separate component that points back at them collectively.
  Either fold that angle into each relevant component, or write ONE self-contained component
  that names the subjects explicitly (e.g., "Implementation challenges and risks of carbon
  capture, reforestation, and renewable-energy incentives").
- Keep each component to roughly **one sentence**.
- Do not invent specifics the need does not imply.
- The collection is cleaned text from web pages with no information about the source of
  each page. Describe the **information** to find, never a type of source or document
  (do not ask for "studies", "reports", "articles", "papers", etc.) — the retrieval and
  generation stages decide which sources to trust.

## Example

NEED: "I'm interested in nuclear energy's pros, cons, safety, and accident risks, like
Chernobyl, plus its uses and climate change impact. I also want to compare it to other
energy forms like fusion and learn about sources such as bison energy and Peninsula
Clean Energy."

COMPONENTS:
1. The main advantages and/or disadvantages of nuclear energy for electricity generation, including cost, reliability, and radioactive waste.
2. The safety systems and overall safety record of modern nuclear power plants.
3. The causes, consequences, and lessons of the Chernobyl nuclear accident.
4. Applications of nuclear energy beyond electricity generation, such as medical isotopes, desalination, and propulsion.
5. Nuclear energy's effect on climate change, including lifecycle greenhouse-gas emissions and its role in decarbonization.
6. A comparison of nuclear fission with fusion energy on technological maturity, cost, and feasibility.
7. A comparison of nuclear energy with fossil fuels, wind, and solar on cost, reliability, and environmental impact.
8. Background on the company Bison Energy and its role in nuclear energy.
9. Background on Peninsula Clean Energy and how it relates to nuclear energy.

Why these work: "pros" and "cons" are ONE component with an AND/OR
request (1). There is NO broad "overview of nuclear energy" component;
it would overlap everything. Each named, specific subject (Chernobyl,
Bison Energy, Peninsula Clean Energy) is its own component because
each is answered by a different set of documents.  Every component
names information to find, written as a statement, with no request for
a particular kind of source.

## Output

Produce a JSON object with two fields:

- `question`: the user's information need, copied verbatim.
- `interpretations`: the ordered list of component strings (most important to the report
  first).
