"""SearchCoach: pluggable post-judging feedback for the Searcher (TASK-40).

After the Judger stops judging a query's results, the Controller asks a `SearchCoach` to
turn the judged descent into the feedback the Searcher reads. This is the seam that was
formerly the Controller's `_summarize` / `_select_feedback`.

Two implementations behind one protocol:
- `MechanicalSearchCoach` (here) -- deterministic, no-LLM, cannot fail; the always-works
  fallback and today's default. It forwards the top-N + high-grade-nugget passages as a
  plain listing.
- an LLM `SearchCoachAgent` (a later phase) -- writes a free-text coaching report.

The coach is **query-blind and atom-blind**: it never sees the query string or the atom
counts, so the same coach serves every searcher (Cottontail cover / tiered / multitext,
Lucindri). The Controller wraps the coach's report with the query echo, coverage stats,
and (Cottontail only) atom counts. See docs/design/search-coach.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class CoachContext:
    """What the coach sees -- query-blind, atom-blind.

    `stats` keys: count (docs judged this query), relevant, total_matches (int | None).
    `results` is the query's judged descent IN RANK ORDER; each item is
    {rank, id, score, grade, summary, reason, is_new} (id is the docno; is_new is False
    for an already-judged revisit).
    """

    intent: str
    stats: dict
    results: list[dict]


@dataclass
class CoachOutput:
    """The coach's contribution to the Searcher feedback.

    `report` is the text the Controller appends after its query/stats/atom header.
    `referenced` are the docnos the coach forwarded/cited (for logging). `usage` and
    `reasoning` are used by the LLM coach's trace event and are empty for the mechanical
    coach.
    """

    report: str
    referenced: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    reasoning: str | None = None


class SearchCoach(Protocol):
    def coach(self, ctx: CoachContext) -> CoachOutput: ...


def select(results: list[dict], top_k: int, min_grade: int) -> list[dict]:
    """The feedback selection: the TOP band -- the first `top_k` by rank, any grade -- plus
    any deeper doc graded `>= min_grade` (the gold nuggets). Rank order is preserved and
    each doc keeps its TRUE rank; skipped docs are not renumbered. (This is the former
    Controller._select_feedback; the mechanical coach's output and the LLM coach's input
    are both shaped by it.)"""
    return [d for pos, d in enumerate(results) if pos < top_k or d["grade"] >= min_grade]


class MechanicalSearchCoach:
    """Deterministic, no-LLM coach: forwards the top-N + high-grade-nugget passages as a
    plain listing. A pure function of its context -- cannot fail -- so it is the universal
    fallback (and today's default feedback)."""

    def __init__(self, *, top_results_to_show: int = 10, min_show_grade: int = 3) -> None:
        self.top_results_to_show = top_results_to_show
        self.min_show_grade = min_show_grade

    def coach(self, ctx: CoachContext) -> CoachOutput:
        shown = select(ctx.results, self.top_results_to_show, self.min_show_grade)
        blocks = [
            f"[rank {d['rank']}] grade={d['grade']} score={d['score']:.3f}\n"
            f"  {d['summary']}\n"
            f"  (assessor: {d['reason']})"
            for d in shown
        ]
        report = "\n\n".join(blocks) if blocks else "(no results surfaced)"
        return CoachOutput(report=report, referenced=[d["id"] for d in shown])
