"""The Searcher: one human "interactive searcher" (ISJ) as a guardrailed LLM loop.

INPUT: one intent (a self-contained, search-ready restatement of the question).
OUTPUT: a `SearcherResult` = a per-intent `RankedList` (judged, graded passages)
plus a structured event `trace`.

The loop: the model writes a GCL cover query (`search`), reads the returned
cover-biased summaries, judges them (`judge`), reformulates, and repeats. The
CONTROLLER -- not the model -- owns termination and the guardrails (judge before
re-searching, engine-delegated errors, judge-argument validation), because the
scouting probes showed model behavior is not portable here
(docs/searcher-agent-lessons-June-16-2026.md).

Recall-first: there is NO hard search budget. The agent keeps reformulating until
it exhausts new material -- the model stops, or queries go dry, or it makes no
progress -- with a generous max-turns cap as the only runaway backstop.
"""

from __future__ import annotations

import json
import time
from importlib.resources import files

import openai
from pydantic import ValidationError

from isj_agent.engine.base import EngineError, SearchEngine
from isj_agent.protocol.results import (
    RankedEntry,
    RankedList,
    SearcherResult,
    TraceEvent,
)
from isj_agent.protocol.search import Hit, Judgement

_PROMPT: str = (
    files("isj_agent.agents").joinpath("searcher.md").read_text(encoding="utf-8")
)

# The judge tool's argument schema is derived from B1's Judgement model so guided
# decoding constrains grades to 0-4. Judgement has no nested models, so its schema
# embeds directly as the array item.
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Run a GCL cover query; returns the unjudged passages plus "
                "total_matches and per-atom counts."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "judge",
            "description": (
                "Record relevance judgements (grade 0-4) for the passages you just read."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "judgements": {
                        "type": "array",
                        "items": Judgement.model_json_schema(),
                    }
                },
                "required": ["judgements"],
            },
        },
    },
]


class Searcher:
    """Runs the ISJ search-and-judge loop for one intent against a SearchEngine."""

    prompt: str = _PROMPT

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        engine: SearchEngine,
        *,
        top_k: int = 10,
        window: int = 75,
        max_turns: int = 150,
        dry_threshold: int = 3,
        no_progress_threshold: int = 3,
        temperature: float = 0.0,
    ) -> None:
        self.client = client
        self.model = model
        self.engine = engine
        self.top_k = top_k
        self.window = window
        self.max_turns = max_turns
        self.dry_threshold = dry_threshold
        self.no_progress_threshold = no_progress_threshold
        self.temperature = temperature

    def run(self, intent: str) -> SearcherResult:
        msgs: list[dict] = [
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": f"Question: {intent}"},
        ]
        judged: set[int] = set()
        recorded: list[RankedEntry] = []  # accumulated judgements (rank filled at compile)
        pending: list[Hit] = []  # surfaced this search, not yet judged
        hits_by_cp: dict[int, Hit] = {}
        surfacing_query: dict[int, str] = {}
        events: list[TraceEvent] = []
        dry = no_progress = turns = 0

        def emit(type_: str, ts: float, duration_ms: float, **fields) -> None:
            events.append(TraceEvent(type=type_, ts=ts, duration_ms=duration_ms, **fields))

        while turns < self.max_turns:
            turns += 1
            t0 = time.time()
            message = (
                self.client.chat.completions.create(
                    model=self.model,
                    messages=msgs,
                    tools=_TOOLS,
                    tool_choice="auto",
                    temperature=self.temperature,
                )
                .choices[0]
                .message
            )
            llm_ms = (time.time() - t0) * 1000.0
            tool_calls = message.tool_calls or []
            emit(
                "llm_turn",
                t0,
                llm_ms,
                turn=turns,
                tool=(tool_calls[0].function.name if tool_calls else None),
                tool_calls=len(tool_calls),  # emitted count; only the first is processed
                stopped=not tool_calls,
            )

            if not tool_calls:
                # Termination: no tool call. Trailing prose is discarded from the output.
                msgs.append({"role": "assistant", "content": message.content or ""})
                emit("stop", time.time(), 0.0, reason="no_tool_call")
                break

            # Process ONLY the first tool call; append only it to the assistant
            # message so each tool_call gets exactly one tool response (real serving
            # stacks reject an assistant tool_call with no matching tool result).
            call = tool_calls[0]
            msgs.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                    ],
                }
            )
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            name = call.function.name

            if name == "search":
                if pending:  # GUARDRAIL: judge the surfaced passages first
                    cps = [h.cp for h in pending]
                    # cps in a STRUCTURED field (so C2 can rewrite cp -> docno);
                    # the persisted message carries no raw cps.
                    emit("bounce", time.time(), 0.0, kind="judge_before_search",
                         cps=cps, message="search refused: judge the surfaced passages first")
                    self._tool(msgs, call, {"error": f"Judge these passages first: {cps}"})
                    continue
                query = args.get("query", "")
                exclude = sorted(judged)
                # Log the request GOING OUT, before the engine call, so the query is
                # on record regardless of outcome -- even if the engine/server dies
                # mid-request (then only this event, not the response, is emitted).
                ts = time.time()
                emit("search_request", ts, 0.0, query=query,
                     top_k=self.top_k, window=self.window, exclude=exclude)
                try:
                    resp = self.engine.search(
                        query, top_k=self.top_k, exclude=exclude, window=self.window
                    )
                    eng_ms = (time.time() - ts) * 1000.0
                except EngineError as exc:  # ENGINE-DELEGATED error -> bounce (the RESPONSE);
                    # carry the query so the failure is self-contained.
                    emit("bounce", time.time(), 0.0, kind="engine_error",
                         query=query, message=str(exc))
                    self._tool(msgs, call, {"error": str(exc)})
                    continue
                emit(
                    "search",
                    ts,
                    eng_ms,
                    query=query,
                    top_k=self.top_k,
                    window=self.window,
                    exclude=exclude,
                    total_matches=resp.total_matches,
                    unjudged_matches=resp.unjudged_matches,
                    atom_counts=[a.model_dump() for a in resp.atom_counts],
                    results=[h.model_dump() for h in resp.results],
                )
                pending = list(resp.results)
                for h in resp.results:
                    hits_by_cp[h.cp] = h
                    surfacing_query[h.cp] = query
                dry = dry + 1 if not resp.results else 0
                no_progress = 0
                self._tool(msgs, call, resp.model_dump())

            elif name == "judge":
                try:  # GUARDRAIL: the model's own tool-call args (NOT a GCL validator)
                    verdicts = [Judgement.model_validate(j) for j in args.get("judgements", [])]
                except ValidationError as exc:
                    emit("bounce", time.time(), 0.0, kind="judge_invalid", message=str(exc))
                    no_progress += 1
                    self._tool(msgs, call, {"error": str(exc)})
                    continue
                surfaced = {h.cp for h in pending}
                new = [j for j in verdicts if j.cp in surfaced and j.cp not in judged]
                for j in new:
                    judged.add(j.cp)
                    hit = hits_by_cp[j.cp]
                    recorded.append(
                        RankedEntry(
                            rank=0,  # filled by _compile
                            cp=j.cp,
                            grade=j.grade,
                            score=hit.score,
                            summary=hit.summary,
                            reason=j.reason,
                            surfacing_query=surfacing_query[j.cp],
                        )
                    )
                pending = [h for h in pending if h.cp not in judged]
                no_progress = no_progress + 1 if not new else 0
                emit(
                    "judge",
                    time.time(),
                    0.0,
                    recorded=len(new),
                    judgements=[{"cp": j.cp, "grade": j.grade, "reason": j.reason} for j in new],
                )
                self._tool(msgs, call, {"ok": True, "recorded": len(new)})

            else:  # defensive: only search/judge are offered
                emit("bounce", time.time(), 0.0, kind="unknown_tool", message=name)
                self._tool(msgs, call, {"error": f"unknown tool: {name}"})
                continue

            if dry >= self.dry_threshold:
                emit("stop", time.time(), 0.0, reason="dry")
                break
            if no_progress >= self.no_progress_threshold:
                emit("stop", time.time(), 0.0, reason="no_progress")
                break
        else:
            # Loop exited via the while condition: the runaway backstop tripped.
            emit("stop", time.time(), 0.0, reason="turn_cap")

        return SearcherResult(ranked_list=self._compile(intent, recorded), events=events)

    @staticmethod
    def _tool(msgs: list[dict], call, payload: dict) -> None:
        msgs.append(
            {"role": "tool", "tool_call_id": call.id, "content": json.dumps(payload)}
        )

    @staticmethod
    def _compile(intent: str, entries: list[RankedEntry]) -> RankedList:
        ordered = sorted(entries, key=lambda e: (-e.grade, -e.score))
        ranked = [e.model_copy(update={"rank": i}) for i, e in enumerate(ordered, 1)]
        return RankedList(intent=intent, entries=ranked)
