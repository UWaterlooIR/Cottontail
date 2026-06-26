"""Searcher output + trace types (B2, TASK-5.6).

A `run(intent)` produces a `SearcherResult` = a per-intent `RankedList` (the judged,
graded passages) plus a structured event `trace`. These are consumed downstream by
C2 (the run-output writer, which rewrites cp -> docno at persistence) and C3 (the
CLI orchestrator). cp-native (doc-6): identifiers are integer cps; docno never
enters the agent.
"""

from pydantic import BaseModel, ConfigDict, Field


class RankedEntry(BaseModel):
    """One judged passage in the compiled per-intent ranked list."""

    rank: int  # the COMPILED per-intent rank (distinct from a Hit's per-search rank)
    cp: int
    grade: int = Field(ge=0, le=4)  # 0-4 UMBRELA-aligned
    score: float  # the engine ssr cover-density score of the surfacing search
    summary: str  # the cover-biased summary the agent read
    reason: str  # the model's justification for the grade
    surfacing_query: str  # the GCL query that surfaced this passage


class RankedList(BaseModel):
    """The Searcher's per-intent output: judged passages, best-first."""

    intent: str
    entries: list[RankedEntry]


class TraceEvent(BaseModel):
    """One timestamped event in the controller's structured trace.

    extra="allow" so each event type carries its own fields (e.g. a search event's
    returned hits, a judge event's verdicts) alongside the common ones. The trace
    is a research artifact: it must be detailed enough to RECONSTRUCT what the agent
    did (the actual queries, results, and judgements -- not just counts).
    """

    model_config = ConfigDict(extra="allow")

    type: str  # llm_turn | search | judge | bounce | stop
    ts: float  # epoch seconds when the event started
    duration_ms: float  # wall-clock duration of the event (LLM / engine latency)


class SearcherResult(BaseModel):
    """One intent's outcome: the ranked list plus the structured event trace."""

    ranked_list: RankedList
    events: list[TraceEvent]
