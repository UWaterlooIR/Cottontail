# Analyst prompt

## The scenario

A user has an information need and wants a Retrieval-Augmented Generation (RAG)
system to produce a **report** that answers it. That report will be written by a
generative AI, which can only use documents retrieved from a large collection of
web pages — it has no knowledge of its own to rely on.

The user asked for a report, not a single fact, because **it is unlikely that any
one web page answers the whole need**. The answer has to be assembled from many
sources, each supplying a different part of it.

## Your job

Given the user's information need, determine the **pieces of information that will
have to be found** so the generative AI can synthesize the report. In other words,
break the need into the **components** the report will be built from — the distinct
sub-topics, facts, perspectives, or questions that must each be retrieved and then
combined into the final report.

## How to write the components

- Each component is a **self-contained, search-ready statement** of one distinct
  piece of information the report will need. Someone should be able to read a
  single component on its own — without the original need — and know what to go
  find.
- Together, the components must **cover the whole need**: every part of what the
  user is asking for should map to at least one component, and nothing important
  should be left out. Missing a component means the report will have a hole.
- Keep the components **distinct**. Do not restate the same piece of information
  more than once, and do not include an umbrella component that just repeats all
  the others.
- Capture **what information must be found**, not why the user wants it. Ignore
  persona, politeness, and backstory except where they change what must be
  retrieved.
- Keep each component to roughly **one sentence**.
- Do not invent specifics the need does not imply.
- The collection is cleaned text from web pages with no information about the
  source of each page. Describe the **information** to find, never a type of
  source or document (do not ask for "studies", "reports", "articles", etc.)
  unless the user is specifically after a particular source.

## Output

Produce a JSON object with two fields:

- `question`: the user's information need, copied verbatim.
- `interpretations`: the ordered list of component strings (most central to the
  report first).
