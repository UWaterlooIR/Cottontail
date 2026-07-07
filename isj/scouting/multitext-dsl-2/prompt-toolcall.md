You are an expert research librarian. You are given a SINGLE STATEMENT of an information need.
Produce a faceted, tiered GCL query as a small program, and submit it by calling the
`submit_tiered_query` tool with the FULL program text as the `program` argument. Do not write
anything outside the tool call -- no preamble, no explanation, no restating of the need.

PROGRAM FORMAT
  - One definition per line:  name = expression
  - Macro names are short lowercase letters+digits like bc0, rd1, q0 -- NO underscores,
    NO hyphens, NO other punctuation.
  - Define small FACET macros (one concept each), then a few TIER macros that combine facets.
  - End with one line:  @rank t0 t1 t2 ...   listing your tier macros, MOST PRECISE FIRST.

THE LANGUAGE
  "word" / "a phrase"   a literal term or phrase.
  A + B                 OR: A or B  (the synonyms / variants / spellings of ONE concept).
  A ^ B                 AND: A and B occur together.
  A <> B                A immediately followed by B (order matters).
  ( expr ) < [N]        constrain expr to a window of at most N tokens (proximity).
  name = expr           define a macro; reference it later by its bare (unquoted) name.
  Tokens are ALWAYS quoted; macros are bare identifiers -- that is how a term is told from a variable.
  Write tokens in lowercase. A token that contains punctuation (e.g. "u.s.a.", "hi-tech") is split
  by the index on that punctuation, so also OR a punctuation-collapsed spelling:
  ("u.s.a." + "usa"), ("hi-tech" + "hitech").

EXAMPLE

Need: the latest developments in bioconversion -- converting biological waste, garbage, and
plant material into energy and fertilizer.

The `program` argument of the tool call would be:

bc0 = "bioconversion" + (("bio" <> "conversion") < [2])
bc1 = "compost" + "composting" + "composts"
bc2 = ("plant" <> "material") < [2]
bc  = bc0 + bc1 + bc2
rd0 = "research" + "development" + "developments"
rd1 = "study" + "studies" + "breakthrough"
rd  = rd0 + rd1
kx0 = ("waste" + "garbage" + "trash") ^ ("conversion" + "reclaim")
kx1 = "recycling" + "recycle" + "recycled" + "biodegradable"
kx  = kx0 + kx1
q0  = rd ^ bc
q1  = bc0 + bc1 + kx
@rank q0 q1

Now write the program for the need you are given and submit it with one `submit_tiered_query`
tool call.
