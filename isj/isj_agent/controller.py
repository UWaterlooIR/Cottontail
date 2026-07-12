"""The per-intent controller: drive Searcher + Judger over one intent (TASK-16).

Owns the loop the agents do NOT: paging down the ranked list, wave-judging, the
non-relevant streak, the judgment budget, de-duplication, error self-correction
routing, and the structured trace. INPUT: one intent + its `intent_budget` (the
Orchestrator's even split of the run-total `max_judgments`). OUTPUT: the existing
`SearcherResult` = a per-intent `RankedList` + a `TraceEvent` list, so C2/C3 are
unchanged.

The shape (one coherent LLM conversation with the Searcher):
  1. Searcher proposes ONE GCL query (forced `search` tool).
  2. The controller descends that query's TRUE ranked list in WAVES of
     `judger.concurrency`, judging only NEW full documents in parallel, counting
     prior-judged docs (via their stored grade), until a streak of non-relevant
     docs (default: grade 0) -- then stops descending but RETAINS the whole wave.
  3. The judged outcome (new docs' summaries+grades+reasons, plus a J/X/Y aggregate
     for the prior-judged docs) is fed back as the `search` tool result -> the
     Searcher's history -> it proposes the next query.
Stops at `intent_budget` or `max_queries`. A judge failure aborts the intent with a
partial result. Engine errors / empty queries bounce straight back to the Searcher.
"""

from __future__ import annotations

import json
import time

from isj_agent.agents.judger import Judger
from isj_agent.agents.search_coach import CoachContext, MechanicalSearchCoach, SearchCoach
from isj_agent.agents.searcher import Searcher
from isj_agent.engine.base import EngineError, SearchEngine
from collections.abc import Callable

from isj_agent.protocol.results import (
    LiveMarker,
    RankedEntry,
    RankedList,
    SearcherResult,
    TraceEvent,
)
from isj_agent.protocol.search import Verdict


class _JudgeFailure(Exception):
    """An ENTIRE judge wave failed (after per-call retries) -> abort the intent.

    A single failed call no longer aborts (TASK-27): it records a grade -2
    sentinel entry instead. A fully-failed wave means an outage, not a hiccup."""


# TASK-27: a doc whose judge call failed after all retries stays IN the ranked
# list with this sentinel. model_construct BYPASSES pydantic validation, so the
# Verdict wire schema (model_json_schema(), fed verbatim to guided decoding)
# stays 0-3 -- the model can never emit -2 itself.
FAILED_GRADE = -2
FAILED_REASON = "Judger agent failed to assess the relevance."


def _failed_verdict() -> Verdict:
    return Verdict.model_construct(reason=FAILED_REASON, grade=FAILED_GRADE)


class Controller:
    """Runs the search/judge loop for one intent against a SearchEngine."""

    def __init__(
        self,
        searcher: Searcher,
        judger: Judger,
        engine: SearchEngine,
        *,
        fetch_k: int = 200,
        window: int = 75,
        nonrelevant_streak: int = 5,
        relevant_grade_threshold: int = 1,
        max_doc_chars: int = 50000,
        max_queries: int = 100,
        max_list_depth: int | None = None,
        coach: SearchCoach | None = None,
        mechanical: SearchCoach | None = None,
        top_results_to_show: int = 10,
        min_show_grade: int = 3,
    ) -> None:
        self.searcher = searcher
        self.judger = judger
        self.engine = engine
        self.fetch_k = fetch_k
        self.window = window
        self.nonrelevant_streak = nonrelevant_streak
        self.relevant_grade_threshold = relevant_grade_threshold
        self.max_doc_chars = max_doc_chars
        self.max_queries = max_queries
        self.max_list_depth = max_list_depth
        # The SearchCoach turns a query's judged descent into the Searcher's feedback
        # (TASK-40). Default: a MechanicalSearchCoach built from top_results_to_show /
        # min_show_grade (kept here as convenience defaults for the auto-built coach); the
        # CLI injects a configured coach. `mechanical` is the always-works fallback the
        # Controller drops to if an LLM coach RAISES mid-run -- so the search never stalls on
        # a coach failure. It defaults to the mechanical coach itself when none is injected.
        self.coach: SearchCoach = coach or MechanicalSearchCoach(
            top_results_to_show=top_results_to_show, min_show_grade=min_show_grade
        )
        self.mechanical: SearchCoach = mechanical or (
            self.coach
            if not getattr(self.coach, "is_llm", False)
            else MechanicalSearchCoach(
                top_results_to_show=top_results_to_show, min_show_grade=min_show_grade
            )
        )

    # wave width = the Judger's concurrency (ONE knob; do not add a second)
    @property
    def wave_size(self) -> int:
        return self.judger.concurrency

    def _relevant(self, grade: int) -> bool:
        return grade >= self.relevant_grade_threshold

    def run(
        self,
        intent: str,
        intent_budget: int,
        observer: Callable[[TraceEvent | LiveMarker], None] | None = None,
    ) -> SearcherResult:
        """Drive the search/judge loop for one intent.

        `observer`, if given, is called the MOMENT each trace event is emitted (and for
        each live-only pre-call marker) so a caller can stream activity in real time
        (TASK-35). The full `events` list is still returned in the SearcherResult for
        run-output writing; with no observer, behavior is byte-identical to before.
        """
        msgs: list[dict] = [
            {"role": "system", "content": self.searcher.system_prompt},
            {"role": "user", "content": f"Question: {intent}"},
        ]
        judged: dict[str, Verdict] = {}      # GLOBAL: docno -> verdict judged in ANY prior query
        recorded: list[RankedEntry] = []     # one entry per NEW judgment this intent
        events: list[TraceEvent] = []
        queries = 0
        last_usage: dict = {}
        run_error: str | None = None

        def emit(type_: str, ts: float, duration_ms: float, **fields) -> None:
            ev = TraceEvent(type=type_, ts=ts, duration_ms=duration_ms, **fields)
            events.append(ev)
            if observer is not None:
                observer(ev)

        def mark(kind: str, **fields) -> None:
            # A LIVE-ONLY marker: delivered to the observer, NOT appended to `events`
            # and never persisted -- so a hung call is visible as a started-but-unfinished
            # signal without changing the persisted trace.
            if observer is not None:
                observer(LiveMarker(kind=kind, ts=time.time(), **fields))

        while True:
            if len(recorded) >= intent_budget:
                emit("stop", time.time(), 0.0, reason="intent_budget")
                break
            if queries >= self.max_queries:
                emit("stop", time.time(), 0.0, reason="max_queries")
                break

            request = list(msgs)  # the verbatim messages we send this turn
            mark("await_searcher_turn", turn=queries + 1)  # live: a turn's LLM call is starting
            t0 = time.time()
            try:
                pr = self.searcher.propose(msgs)
            except Exception as exc:  # searcher LLM failure -> partial result
                emit("error", time.time(), 0.0, error_type=type(exc).__name__,
                     message=str(exc), turn=queries + 1, request=request, **last_usage)
                run_error = f"{type(exc).__name__}: {exc}"
                break
            llm_ms = (time.time() - t0) * 1000.0
            last_usage = pr.usage
            emit("llm_call", t0, llm_ms, purpose="searcher_turn", turn=queries + 1,
                 request=request, content=pr.content,
                 calls=([{"name": pr.queryable.tool_name,
                          "arguments": json.dumps(pr.queryable.trace_arguments())}]
                        if pr.queryable is not None else []),
                 finish_reason=pr.finish_reason,
                 tool=(pr.queryable.tool_name if pr.queryable is not None else None),
                 tool_calls=pr.n_tool_calls, **pr.usage)
            msgs.append(pr.assistant_message)
            queries += 1

            if pr.queryable is None:  # defensive: tool_choice=required should prevent this
                emit("bounce", time.time(), 0.0, kind="no_query",
                     message="no usable query produced")
                if pr.tool_call_id is not None:
                    self._tool(msgs, pr.tool_call_id, {"error": "emit a valid search tool call with a query"})
                else:
                    msgs.append({"role": "user", "content": "Call the provided search tool with a query."})
                continue

            emit("propose", time.time(), 0.0, query=pr.queryable.query_string())
            try:
                outcome = self._descend(intent, pr.queryable, judged, recorded, events, emit, mark, intent_budget)
            except _JudgeFailure as jf:
                emit("error", time.time(), 0.0, error_type="JudgeFailure",
                     message=str(jf), turn=queries, request=None, **last_usage)
                run_error = str(jf)
                break
            if "error" in outcome:  # malformed-query bounce -> back to the Searcher as-is
                self._tool(msgs, pr.tool_call_id, outcome)
            else:  # build the Searcher feedback via the coach
                descended = outcome["descended"]
                stats = {"count": len(descended),
                         "relevant": sum(1 for d in descended if self._relevant(d["grade"])),
                         "total_matches": outcome["total_matches"]}
                ctx = CoachContext(intent=intent, stats=stats, results=descended)
                coach_is_llm = getattr(self.coach, "is_llm", False)
                if coach_is_llm:
                    mark("await_coach")  # live: the coach's LLM call is starting
                c0 = time.time()
                try:
                    out = self.coach.coach(ctx)
                except Exception as exc:  # an LLM coach failed -> never stall; use the fallback
                    emit("coach_fallback", time.time(), (time.time() - c0) * 1000.0,
                         error_type=type(exc).__name__, message=str(exc))
                    out = self.mechanical.coach(ctx)
                else:
                    if coach_is_llm:  # a real LLM call happened; the mechanical coach is silent
                        emit("llm_call", c0, (time.time() - c0) * 1000.0, purpose="coach",
                             referenced=out.referenced, content=out.reasoning, **(out.usage or {}))
                content = self._compose_feedback(pr.queryable, outcome["atom_counts"], stats, out)
                self._tool(msgs, pr.tool_call_id, content)

        return SearcherResult(
            ranked_list=self._compile(intent, recorded), events=events, error=run_error
        )

    def _descend(self, intent, queryable, judged, recorded, events, emit, mark, intent_budget) -> dict:
        """Descend ONE query's true ranked list in waves; return the Searcher's history payload.

        Returns {"error": msg} on a malformed query (-> Searcher reformulates), otherwise the
        summarize payload. RAISES _JudgeFailure on a failed judge call. `queryable.execute()`
        runs the query (a cover, or a tiered cascade) each refill; the controller only pages it.
        """
        qs = queryable.query_string()  # display string for the trace events + surfacing_query
        streak = 0
        seen: set[str] = set()   # docnos consumed THIS query -> the engine exclude (NOT global judged)
        depth = 0                # K: ranks descended this query
        descended: list[dict] = []  # every doc processed THIS query, IN RANK ORDER (new AND
                                    # already-judged): {rank(=global depth), id, score, grade,
                                    # summary, reason, is_new} -> the Searcher feedback selection
        buffer: list = []
        total_matches = None
        atom_counts: list | None = None   # per query-leaf corpus counts (None if the engine omits them)
        exhausted = False

        while not exhausted and len(recorded) < intent_budget:
            if not buffer:  # REFILL: fetch the next batch (exclude = this query's consumed docnos)
                exclude = sorted(seen)
                ts = time.time()
                emit("search_request", ts, 0.0, query=qs, top_k=self.fetch_k,
                     window=self.window, exclude=exclude)
                try:
                    resp = queryable.execute(self.engine, top_k=self.fetch_k, exclude=exclude,
                                             window=self.window)
                except EngineError as e:  # malformed query -> bounce back to the Searcher
                    emit("bounce", time.time(), 0.0, kind="engine_error", query=qs, message=str(e))
                    return {"error": str(e)}
                eng_ms = (time.time() - ts) * 1000.0
                if resp.total_matches is not None:
                    total_matches = resp.total_matches
                fetch_atoms = ([a.model_dump() for a in resp.atom_counts]
                               if resp.atom_counts is not None else None)
                if atom_counts is None and fetch_atoms is not None:  # representative = the query's first fetch
                    atom_counts = fetch_atoms
                # OPTIONAL diagnostics (Q3): only emit the counts an engine actually reports.
                diag = {}
                if resp.total_matches is not None:
                    diag["total_matches"] = resp.total_matches
                if resp.unjudged_matches is not None:
                    diag["unjudged_matches"] = resp.unjudged_matches
                if fetch_atoms is not None:
                    diag["atom_counts"] = fetch_atoms
                emit("search", ts, eng_ms, query=qs, returned=len(resp.results),
                     results=[h.model_dump() for h in resp.results], **diag)
                if not resp.results:  # dry / list exhausted
                    break
                buffer = list(resp.results)

            wave = buffer[: self.wave_size]
            buffer = buffer[self.wave_size :]
            new = [h for h in wave if h.id not in judged]   # only NEW docs go to the Judger
            if new:
                mark("await_judge", count=len(new))  # live: a judge wave (reads + LLM) is starting
            docs = [(h.summary, (self.engine.read(h.id) or "")[: self.max_doc_chars]) for h in new]
            calls_by_id = {h.id: c for h, c in zip(new, self.judger.judge(intent, docs))}  # PARALLEL
            # Systemic guard (TASK-27): every call in the wave failed after retries
            # -> an outage, not a hiccup; abort with the partial result as before.
            if new and all(c.error or c.verdict is None for c in calls_by_id.values()):
                for c in calls_by_id.values():
                    emit("llm_call", time.time(), c.duration_ms, purpose="judge",
                         request=c.request, content=c.content, reasoning=c.reasoning,
                         error=c.error, retries=c.retries, **c.usage)
                raise _JudgeFailure(
                    f"entire judge wave failed ({len(new)} calls, after retries): "
                    f"{next(iter(calls_by_id.values())).error}")

            # RETAIN ALL: ONE pass in rank order. Record EVERY new doc -- even past the streak
            # trip -- and, on a judge failure, only AFTER recording the good docs ranked before it.
            for h in wave:
                seen.add(h.id)
                depth += 1
                if h.id in judged:           # prior judgment: no re-read/re-judge/re-record
                    v = judged[h.id]         # the stored Verdict (carries grade + reason)
                    g = v.grade
                    emit("revisit", time.time(), 0.0, id=h.id, grade=g)
                    is_new = False
                else:                          # NEW: emit the judge llm_call, then record
                    c = calls_by_id[h.id]
                    emit("llm_call", time.time(), c.duration_ms, purpose="judge", request=c.request,
                         content=c.content, reasoning=c.reasoning, error=c.error,
                         retries=c.retries, **c.usage)
                    if c.error or c.verdict is None:
                        # TASK-27: retries exhausted -> record the -2 sentinel and
                        # keep going; the doc consumes budget, enters the judged/
                        # exclude set, and the Searcher sees the outcome.
                        emit("judge_failed", time.time(), 0.0, id=h.id,
                             retries=c.retries, error=c.error)
                        v = _failed_verdict()
                    else:
                        v = c.verdict
                    judged[h.id] = v
                    recorded.append(RankedEntry(rank=0, id=h.id, grade=v.grade, score=h.score,
                                                summary=h.summary, reason=v.reason,
                                                surfacing_query=qs))
                    emit("judge", time.time(), 0.0, id=h.id, grade=v.grade, reason=v.reason)
                    g = v.grade
                    is_new = True
                # Capture the doc IN RANK ORDER (depth = its true cross-refill rank). This
                # full descent is the coach's input (CoachContext.results); the coach/
                # search_coach.select() decides what the Searcher ultimately sees.
                descended.append({"rank": depth, "id": h.id, "score": h.score, "grade": g,
                                  "summary": h.summary, "reason": v.reason, "is_new": is_new})
                if g < 0:      # TASK-27 sentinel: an ERROR is evidence of neither
                    pass       # relevance nor irrelevance -- the streak is untouched
                elif self._relevant(g):
                    streak = 0
                else:
                    streak += 1
                    if streak >= self.nonrelevant_streak and not exhausted:
                        exhausted = True       # stop AFTER this wave; keep recording its remaining docs
                        emit("list_exhausted", time.time(), 0.0, query=qs, depth=depth, streak=streak)

            if self.max_list_depth and depth >= self.max_list_depth:
                break

        # Return the raw descent + diagnostics; run() builds the Searcher feedback via the
        # coach. (A malformed-query bounce still returns {"error": msg} above.)
        return {"descended": descended, "atom_counts": atom_counts, "total_matches": total_matches}

    def _compose_feedback(self, queryable, atom_counts, stats: dict, out) -> str:
        """Assemble the Searcher's feedback string: the query echo + coverage stats +
        (Cottontail only, iff the engine returned them) atom counts + the coach's report.
        The coach is query-blind/atom-blind, so the Controller owns the first three parts."""
        cov = (f"Coverage: judged {stats['count']} results this query, "
               f"{stats['relevant']} relevant")
        if stats["total_matches"] is not None:
            cov += f"; {stats['total_matches']} total corpus matches"
        lines = [f"Your query: {queryable.query_string()}", cov + "."]
        if atom_counts is not None:  # engine-provided per-term corpus counts (Cottontail only)
            lines.append("Atom matches: " + ", ".join(
                f"{a['term']}={a['count']}" for a in atom_counts))
        return "\n".join(lines) + "\n\n" + out.report

    @staticmethod
    def _tool(msgs: list[dict], tool_call_id: str, payload) -> None:
        # payload is the Searcher-feedback STRING (the coach path) or a dict (the bounce
        # path); a dict is JSON-serialized, a string sent as-is.
        content = payload if isinstance(payload, str) else json.dumps(payload)
        msgs.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})

    @staticmethod
    def _compile(intent: str, entries: list[RankedEntry]) -> RankedList:
        ordered = sorted(entries, key=lambda e: (-e.grade, -e.score))
        ranked = [e.model_copy(update={"rank": i}) for i, e in enumerate(ordered, 1)]
        return RankedList(intent=intent, entries=ranked)
