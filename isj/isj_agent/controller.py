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
from isj_agent.agents.searcher import Searcher
from isj_agent.engine.base import EngineError, SearchEngine
from isj_agent.protocol.results import RankedEntry, RankedList, SearcherResult, TraceEvent
from isj_agent.protocol.search import Verdict


class _JudgeFailure(Exception):
    """A judge call failed (LLM error or unparseable Verdict) -> abort the intent."""


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

    # wave width = the Judger's concurrency (ONE knob; do not add a second)
    @property
    def wave_size(self) -> int:
        return self.judger.concurrency

    def _relevant(self, grade: int) -> bool:
        return grade >= self.relevant_grade_threshold

    def run(self, intent: str, intent_budget: int) -> SearcherResult:
        msgs: list[dict] = [
            {"role": "system", "content": self.searcher.system_prompt},
            {"role": "user", "content": f"Question: {intent}"},
        ]
        judged: dict[int, Verdict] = {}      # GLOBAL: cp -> verdict judged in ANY prior query
        recorded: list[RankedEntry] = []     # one entry per NEW judgment this intent
        events: list[TraceEvent] = []
        queries = 0
        last_usage: dict = {}
        run_error: str | None = None

        def emit(type_: str, ts: float, duration_ms: float, **fields) -> None:
            events.append(TraceEvent(type=type_, ts=ts, duration_ms=duration_ms, **fields))

        while True:
            if len(recorded) >= intent_budget:
                emit("stop", time.time(), 0.0, reason="intent_budget")
                break
            if queries >= self.max_queries:
                emit("stop", time.time(), 0.0, reason="max_queries")
                break

            request = list(msgs)  # the verbatim messages we send this turn
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
                 calls=([{"name": "search", "arguments": json.dumps({"query": pr.query})}]
                        if pr.query is not None else []),
                 finish_reason=pr.finish_reason, tool=("search" if pr.query is not None else None),
                 tool_calls=pr.n_tool_calls, **pr.usage)
            msgs.append(pr.assistant_message)
            queries += 1

            if pr.query is None:  # defensive: tool_choice=required should prevent this
                emit("bounce", time.time(), 0.0, kind="no_query",
                     message="no GCL query produced")
                if pr.tool_call_id is not None:
                    self._tool(msgs, pr.tool_call_id, {"error": "emit a search tool call with a GCL query"})
                else:
                    msgs.append({"role": "user", "content": "Call the search tool with a GCL query."})
                continue

            emit("propose", time.time(), 0.0, query=pr.query)
            try:
                outcome = self._descend(intent, pr.query, judged, recorded, events, emit, intent_budget)
            except _JudgeFailure as jf:
                emit("error", time.time(), 0.0, error_type="JudgeFailure",
                     message=str(jf), turn=queries, request=None, **last_usage)
                run_error = str(jf)
                break
            self._tool(msgs, pr.tool_call_id, outcome)

        return SearcherResult(
            ranked_list=self._compile(intent, recorded), events=events, error=run_error
        )

    def _descend(self, intent, query, judged, recorded, events, emit, intent_budget) -> dict:
        """Descend ONE query's true ranked list in waves; return the Searcher's history payload.

        Returns {"error": msg} on a malformed query (-> Searcher reformulates), otherwise the
        summarize payload. RAISES _JudgeFailure on a failed judge call.
        """
        streak = 0
        seen: set[int] = set()   # cps consumed THIS query -> the engine exclude (NOT global judged)
        depth = 0                # K: ranks descended this query
        again: list[tuple[int, int]] = []   # (cp, grade) prior-judged re-encounters (count only)
        fresh: list[tuple] = []  # (Hit, Verdict) NEW judgments this query -> returned to Searcher
        buffer: list = []
        total_matches = 0
        atom_counts: list = []   # per query-leaf corpus counts; identical across this query's fetches
        exhausted = False

        while not exhausted and len(recorded) < intent_budget:
            if not buffer:  # REFILL: fetch the next batch (exclude = this query's consumed cps)
                exclude = sorted(seen)
                ts = time.time()
                emit("search_request", ts, 0.0, query=query, top_k=self.fetch_k,
                     window=self.window, exclude=exclude)
                try:
                    resp = self.engine.search(query, top_k=self.fetch_k, exclude=exclude,
                                              window=self.window)
                except EngineError as e:  # malformed query -> bounce back to the Searcher
                    emit("bounce", time.time(), 0.0, kind="engine_error", query=query, message=str(e))
                    return {"error": str(e)}
                eng_ms = (time.time() - ts) * 1000.0
                total_matches = resp.total_matches
                fetch_atoms = [a.model_dump() for a in resp.atom_counts]
                if not atom_counts:  # representative = the query's first fetch (atoms are identical across fetches)
                    atom_counts = fetch_atoms
                emit("search", ts, eng_ms, query=query, total_matches=resp.total_matches,
                     unjudged_matches=resp.unjudged_matches,
                     atom_counts=fetch_atoms,
                     returned=len(resp.results),
                     results=[h.model_dump() for h in resp.results])
                if not resp.results:  # dry / list exhausted
                    break
                buffer = list(resp.results)

            wave = buffer[: self.wave_size]
            buffer = buffer[self.wave_size :]
            new = [h for h in wave if h.cp not in judged]   # only NEW docs go to the Judger
            docs = [(h.summary, (self.engine.read(h.cp) or "")[: self.max_doc_chars]) for h in new]
            calls_by_cp = {h.cp: c for h, c in zip(new, self.judger.judge(intent, docs))}  # PARALLEL

            # RETAIN ALL: ONE pass in rank order. Record EVERY new doc -- even past the streak
            # trip -- and, on a judge failure, only AFTER recording the good docs ranked before it.
            for h in wave:
                seen.add(h.cp)
                depth += 1
                if h.cp in judged:           # prior judgment: count only (no re-read/re-judge/re-record)
                    g = judged[h.cp].grade
                    again.append((h.cp, g))
                    emit("revisit", time.time(), 0.0, cp=h.cp, grade=g)
                else:                          # NEW: emit the judge llm_call, then record
                    c = calls_by_cp[h.cp]
                    emit("llm_call", time.time(), c.duration_ms, purpose="judge", request=c.request,
                         content=c.content, reasoning=c.reasoning, error=c.error, **c.usage)
                    if c.error or c.verdict is None:
                        raise _JudgeFailure(f"judge failed for cp {h.cp}: {c.error}")
                    v = c.verdict
                    judged[h.cp] = v
                    recorded.append(RankedEntry(rank=0, cp=h.cp, grade=v.grade, score=h.score,
                                                summary=h.summary, reason=v.reason,
                                                surfacing_query=query))
                    fresh.append((h, v))
                    emit("judge", time.time(), 0.0, cp=h.cp, grade=v.grade, reason=v.reason)
                    g = v.grade
                if self._relevant(g):
                    streak = 0
                else:
                    streak += 1
                    if streak >= self.nonrelevant_streak and not exhausted:
                        exhausted = True       # stop AFTER this wave; keep recording its remaining docs
                        emit("list_exhausted", time.time(), 0.0, query=query, depth=depth, streak=streak)

            if self.max_list_depth and depth >= self.max_list_depth:
                break

        return self._summarize(query, atom_counts, total_matches, depth, again, fresh)

    def _summarize(self, query, atom_counts, total_matches, depth, again, fresh) -> dict:
        # Field order is deliberate -- it is what the Searcher reads top-to-bottom:
        # diagnostics first (atom_counts up top so a count-0 dead atom is caught early),
        # the content last; and per result rank/score then summary BEFORE reason BEFORE
        # grade, so the agent reads the passage before it sees the assessor's verdict.
        x = sum(1 for _, g in again if self._relevant(g))
        return {
            "query": query,
            "atom_counts": atom_counts,
            "total_matches": total_matches,
            "depth_judged": depth,
            "already_judged": {"count": len(again), "relevant": x, "non_relevant": len(again) - x},
            "new_results": [
                {"rank": h.rank, "score": h.score, "summary": h.summary,
                 "reason": v.reason, "grade": v.grade}
                for h, v in fresh
            ],
        }

    @staticmethod
    def _tool(msgs: list[dict], tool_call_id: str, payload: dict) -> None:
        msgs.append({"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(payload)})

    @staticmethod
    def _compile(intent: str, entries: list[RankedEntry]) -> RankedList:
        ordered = sorted(entries, key=lambda e: (-e.grade, -e.score))
        ranked = [e.model_copy(update={"rank": i}) for i, e in enumerate(ordered, 1)]
        return RankedList(intent=intent, entries=ranked)
