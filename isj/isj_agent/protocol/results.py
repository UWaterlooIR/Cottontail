"""Searcher output + trace types (B2, TASK-5.6).

A `run(intent)` produces a `SearcherResult` = a per-intent `RankedList` (the judged,
graded passages) plus a structured event `trace`. These are consumed downstream by
C2 (the run-output writer, which rewrites cp -> docno at persistence) and C3 (the
CLI orchestrator). cp-native (doc-6): identifiers are integer cps; docno never
enters the agent.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RankedEntry(BaseModel):
    """One judged passage in the compiled per-intent ranked list."""

    rank: int  # the COMPILED per-intent rank (distinct from a Hit's per-search rank)
    cp: int
    # canonical UMBRELA / TREC 0-3 scale (matches Verdict.grade), plus the -2
    # error sentinel (TASK-27): "Judger agent failed to assess the relevance."
    # -2 is controller-constructed only -- the model-facing Verdict schema stays 0-3.
    grade: Literal[-2, 0, 1, 2, 3]
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

    type: str  # llm_call | search_request | search | judge | bounce | stop | error
    ts: float  # epoch seconds when the event started
    duration_ms: float  # wall-clock duration of the event (LLM / engine latency)


class SearcherResult(BaseModel):
    """One intent's outcome: the ranked list plus the structured event trace.

    `error` is set when the run ended on a caught mid-loop failure (e.g. the LLM
    raised): the result is then PARTIAL -- `ranked_list` holds whatever was judged
    before the failure and `events` ends in an `error` event. `error` is None on a
    clean run. The result is still persisted either way (the trace is never dropped).
    """

    ranked_list: RankedList
    events: list[TraceEvent]
    error: str | None = None
