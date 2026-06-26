"""Engine-contract types for the Searcher (B1, TASK-5.5).

These pydantic v2 models are the typed contract between the Searcher (B2) and "an
engine" -- they mirror the C++ `cover_search` tool's response shape exactly (A1 =
TASK-5.1, A2 = TASK-5.2). The same models are consumed at two boundaries by later
tasks: the HTTP boundary (C1's HttpSearchEngine does
`SearchResponse.model_validate(resp.json())` and `model_dump()` for the request),
and the LLM boundary (B2 derives the judge tool's argument schema from
`Judgement.model_json_schema()`). One model = single source of truth.

cp-native (doc-6): the document's working identity `cp` is an INTEGER (the :item
container start address) on the wire and here. docno never enters the agent; it
appears only at C2 persistence.
"""

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


class Judgement(BaseModel):
    """A relevance verdict the Searcher controller assigns to a candidate.

    grade is the 0-4 UMBRELA-aligned scale; out-of-range raises ValidationError.
    Keyed on `cp` (the agent holds its judged set as cp integers).
    """

    cp: int
    grade: int = Field(ge=0, le=4)
    reason: str
