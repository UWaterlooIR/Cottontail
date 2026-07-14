You are assessing a DOCUMENT for a retrieval task that supports report writing. A generative
AI will write a report (up to ~1000 words) answering the user's request; it can only use
documents that retrieval finds. The request has been broken into information components, and
right now we are collecting documents for ONE of them — the SEARCH TARGET. You are given the
full context (the user's request, the analysis, and the SEARCH TARGET) below.

Grade how useful this document is on a 0–3 scale, judged against the SEARCH TARGET first and
the overall report second:
  3 — Highly relevant to the SEARCH TARGET: directly and substantially provides the information
      the target calls for.
  2 — Relevant to the SEARCH TARGET: helps cover the target — partially, or with useful detail,
      even if incomplete.
  1 — Relevant to the REPORT but NOT the SEARCH TARGET: useful for the user's request / some
      OTHER component, but it does not address this target. (Another search collects that; here
      it is off-target.)
  0 — Not relevant to the report at all.

Reason through these steps before grading:
1. Target — what would actually satisfy the SEARCH TARGET: the information need behind it,
   read within the user's request, not its surface words.
2. Topical match — what the document ACTUALLY contains. Does it provide the SEARCH TARGET's
   information (→ 2/3), only some OTHER part of the report (→ 1), or nothing for the report
   (→ 0)? Grade on substance, never on keyword overlap; a document can echo the words and
   answer nothing.
3. Trust — whether the content is credible enough to rely on (watch for spam, fabrication,
   promotional filler, internal contradiction, unsupported claims). Untrustworthy content does
   not satisfy the need however on-topic it appears; let low trust cap the grade.
4. Scope — judge the FULL document text below (it may be truncated). The representative passage
   is cover-biased orientation only; do not let one strong passage lift the grade if the rest of
   the document is thin.

REPORT CONTEXT AND SEARCH TARGET:
{intent}

REPRESENTATIVE PASSAGE (orientation only — judge the full document, not just this):
{summary}

DOCUMENT:
{document}
