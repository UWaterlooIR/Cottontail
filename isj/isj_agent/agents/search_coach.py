"""SearchCoach: pluggable post-judging feedback for the Searcher (TASK-40).

After the Judger stops judging a query's results, the Controller asks a `SearchCoach` to
turn the judged descent into the feedback the Searcher reads. This is the seam that was
formerly the Controller's `_summarize` / `_select_feedback`.

Two implementations behind one protocol:
- `MechanicalSearchCoach` (here) -- deterministic, no-LLM, cannot fail; the always-works
  fallback and today's default. It forwards the top-N + high-grade-nugget passages as a
  plain listing.
- an LLM `SearchCoachAgent` (a later phase) -- writes a free-text coaching report.

The coach is **query-blind**: it never sees the query string, so the same coach serves
every searcher (Cottontail cover / tiered / multitext, Lucindri). The Controller wraps
the coach's report with the query echo and coverage stats. See docs/design/search-coach.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Protocol

import openai

# A cited passage handle: R followed by digits, whether bare (R3), bold (**R3**), or
# bracketed ([R3]). Validated against the actual input handles by the extractor, so a
# stray token that happens to look like a handle is dropped.
_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9])R\d+(?![A-Za-z0-9])")


@dataclass
class CoachContext:
    """What the coach sees -- query-blind.

    `stats` keys: count (docs judged this query), relevant.
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

    `report` is the text the Controller appends after its query/coverage header.
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

    is_llm = False  # the Controller uses this to decide whether to emit a coach llm_call event

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


def _referenced_docnos(report: str, handles: dict) -> list[str]:
    """Docnos the report CITES, in first-mention order. Tolerant of bracket drift: matches
    R\\d+ bracketed OR bare/bold, keeps only handles actually present in the input (dropping
    hallucinated ones), and maps to their docnos. Empty is fine -- the report is
    self-contained, so no citation is not a failure."""
    seen: set[str] = set()
    out: list[str] = []
    for h in _HANDLE_RE.findall(report or ""):
        if h in seen or h not in handles:
            continue
        seen.add(h)
        out.append(handles[h]["id"])
    return out


def _novelty_line(ctx: CoachContext) -> str:
    """A one-line summary of how much NEW ground the query covered vs re-surfacing already-judged
    docs (revisits). Lets the coach detect a searcher stuck re-mining the same vein (the plateau
    counterpart to a 0-result query) and coach a shift/loosen instead of a tighten."""
    total = len(ctx.results)
    if total == 0:
        return "This query surfaced no results."
    seen = sum(1 for d in ctx.results if not d.get("is_new", True))
    new = total - seen
    return (f"This query judged {total} result(s): {new} newly surfaced and "
            f"{seen} already judged on earlier queries (revisits).")


class SearchCoachAgent:
    """The LLM coach (TASK-40): given the information need and the query's judged results,
    it writes a free-text coaching report (the v6 prompt: what's working / hurting / pursue
    next + a self-contained '## Cited passages' section reproducing the excerpts verbatim).

    Query-blind: it sees only the need and the judged passages, so the same coach serves
    every searcher. Free text -- NO guided decoding (that failed on
    gpt-oss-120b). Generation is bounded (max_tokens + per-call timeout, like the Judger);
    a runaway coach times out and the Controller falls back to the MechanicalSearchCoach.
    """

    is_llm = True

    _BUNDLED = files("isj_agent.agents").joinpath("search_coach.md")

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        *,
        prompt: str | Path | None = None,
        reasoning_effort: str | None = "medium",
        temperature: float = 0.0,
        max_tokens: int | None = 8000,
        timeout_s: float | None = 120.0,
        input_top_k: int = 25,
        input_min_grade: int = 3,
    ) -> None:
        self.client = client
        self.model = model
        # Directable prompt: a file path OVERRIDES the bundled search_coach.md (a relative
        # path resolves against the repo root, matching the Searcher). None -> bundled.
        if prompt is None:
            self.prompt = self._BUNDLED.read_text(encoding="utf-8")
        else:
            path = Path(prompt)
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[3] / path
            if not path.is_file():
                raise FileNotFoundError(f"coach prompt file not found: {path}")
            self.prompt = path.read_text(encoding="utf-8")
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.input_top_k = input_top_k
        self.input_min_grade = input_min_grade

    def coach(self, ctx: CoachContext) -> CoachOutput:
        sel = select(ctx.results, self.input_top_k, self.input_min_grade)
        handles = {f"R{i + 1}": d for i, d in enumerate(sel)}
        passages = "\n".join(
            f"[{h}] grade={d['grade']}"
            # mark a re-surfaced (already-judged) doc so the coach can see the rut, not just grades
            + ("" if d.get("is_new", True) else "  (already judged on an earlier query)")
            + f"\n  reason: {d['reason']}\n  summary: {d['summary']}"
            for h, d in handles.items()
        )
        novelty = _novelty_line(ctx)
        # str.replace, NOT str.format -- reasons/summaries can contain literal braces.
        content = (self.prompt
                   .replace("{intent}", ctx.intent)
                   .replace("{novelty}", novelty)
                   .replace("{passages}", passages))
        extra = {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        bound = {}  # token cap + per-call timeout (TASK-37); omit when unset
        if self.max_tokens is not None:
            bound["max_tokens"] = self.max_tokens
        if self.timeout_s is not None:
            bound["timeout"] = self.timeout_s
        # NO response_format: the report is free-text markdown (guided JSON degraded on this
        # stack; see docs/design/search-coach.md). Errors propagate -> Controller fallback.
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            temperature=self.temperature,
            extra_body=extra,
            **bound,
        )
        msg = resp.choices[0].message
        report = msg.content or ""
        usage = getattr(resp, "usage", None)
        usage_d = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        return CoachOutput(
            report=report,
            referenced=_referenced_docnos(report, handles),
            usage=usage_d,
            reasoning=getattr(msg, "reasoning_content", None),
        )
