"""Engine-contract types for the Searcher (B1, TASK-5.5).

These pydantic v2 models are the typed contract between the Searcher (B2) and "an
engine" -- they mirror the C++ `cover_search` tool's response shape exactly (A1 =
TASK-5.1, A2 = TASK-5.2). The same models are consumed at two boundaries by later
tasks: the HTTP boundary (C1's HttpSearchEngine does
`SearchResponse.model_validate(resp.json())` and `model_dump()` for the request),
and the LLM boundary (the Judger derives its guided-output schema from
`Verdict.model_json_schema()`). One model = single source of truth.

cp-native (doc-6): the document's working identity `cp` is an INTEGER (the :item
container start address) on the wire and here. docno never enters the agent; it
appears only at C2 persistence.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AtomCount(BaseModel):
    """Per query-leaf occurrence count (cover_search atom_counts, A2)."""

    term: str
    count: int  # total OCCURRENCES of the resolved feature in the corpus


class Hit(BaseModel):
    """One ranked document in a cover_search response (A1)."""

    rank: int  # 1-based within this response
    score: float  # ssr cover-density score
    cp: int  # the document's working identity (:item container start address)
    summary: str  # cover-biased extractive summary


class SearchResponse(BaseModel):
    """The cover_search response aggregate (A1 + A2, the enriched shape).

    extra="forbid": a server that adds an unexpected field fails LOUDLY (catches
    contract drift) rather than silently dropping it. The tradeoff is strictness
    over forward-compatibility -- chosen deliberately for the engine response so
    the Python contract and the C++ server stay in lock-step.
    """

    model_config = ConfigDict(extra="forbid")

    total_matches: int  # documents matching the query in :item (ignores exclude)
    unjudged_matches: int  # matches not in the exclude set
    atom_counts: list[AtomCount]
    results: list[Hit]


class Verdict(BaseModel):
    """The Judger's guided output for ONE document: a relevance grade + reason.

    NO cp: the controller called the Judger about a specific document, so it pairs
    the returned Verdict with that cp itself -- the model is never given the id.
    `reason` is declared BEFORE `grade` on purpose: under guided JSON decoding the
    model fills properties in declaration order, so the justification is generated
    before the grade is committed. `grade` is the canonical UMBRELA / TREC 0-3 scale.
    """

    reason: str = Field(
        description=(
            "One to three sentences. Name the searcher's intent, how well the "
            "document's ACTUAL content meets it (coverage, directness, specificity), "
            "and trust if it affected the grade. Cite a specific span or concrete "
            "detail from the document; judge on substance, not keyword overlap."
        )
    )
    grade: Literal[0, 1, 2, 3] = Field(
        description=(
            "0 = irrelevant; 1 = related but does not answer; 2 = partial (some "
            "answer, incomplete/unclear/buried); 3 = perfectly relevant (dedicated, "
            "complete, direct). Low trust caps the grade."
        )
    )
