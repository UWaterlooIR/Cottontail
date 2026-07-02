"""The Searcher: a thin query author over a pluggable set of query types (TASK-16, TASK-18).

INPUT: the running conversation (its prior queries and their judged outcomes, which
the CONTROLLER builds). OUTPUT: exactly ONE `Queryable` per turn -- the query the
Controller will execute.

`BaseSearcher` is generic: it holds a `system_prompt` and a list of `query_types`
(Queryable subclasses), offers their tool schemas to the LLM with
`tool_choice="required"`, and routes the returned tool call BY NAME to the matching
query type's `from_tool_arguments`. A concrete searcher is just a subclass that sets
`system_prompt` + `query_types` -- e.g. `Searcher` (cover queries) here, and
`TieredSearcher` (tiered queries) in TASK-20 -- so neither needs base changes.

The Searcher does NOT judge and has no relevance scale, and never runs the query or
touches Cottontail: the loop, paging, de-duplication, budget, execution, and trace
are the Controller's. If the model returns no proper tool call (or a malformed /
unknown one), `propose` yields `queryable=None`; the Controller bounces it and the
model retries (an inline-JSON emission is rare, so it is bounced, not recovered).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files

import openai

from isj_agent.protocol.queryable import CoverQuery, Queryable

_PROMPT: str = (
    files("isj_agent.agents").joinpath("searcher.md").read_text(encoding="utf-8")
)


@dataclass
class ProposeResult:
    """One Searcher round-trip: the chosen queryable + what the controller needs to continue.

    `queryable` is None only in the defensive case where the model returned no usable
    tool call (no tool_calls, or a malformed / unknown tool call) -- the controller
    bounces it back. `assistant_message` is appended verbatim to the conversation;
    `tool_call_id` keys the matching tool result the controller appends next.
    """

    queryable: Queryable | None
    content: str | None  # the assistant's reasoning text (for the trace)
    tool_call_id: str | None
    assistant_message: dict
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None
    n_tool_calls: int = 0


class BaseSearcher:
    """Proposes one Queryable per call over a configured set of query types.

    Subclasses set `system_prompt` and `query_types`; the round-trip, tool exposure,
    and tool-call routing are generic here.
    """

    system_prompt: str = ""
    query_types: list[type[Queryable]] = []

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        *,
        reasoning_effort: str | None = "medium",
        temperature: float = 0.0,
    ) -> None:
        self.client = client
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature

    def propose(self, messages: list[dict]) -> ProposeResult:
        """One LLM round-trip. May RAISE on an LLM/transport failure -- the controller
        catches it and returns a partial result (it owns persist-on-failure)."""
        by_name = {qt.tool_name: qt for qt in self.query_types}
        extra = (
            {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=[qt.tool_schema() for qt in self.query_types],
            tool_choice="required",
            temperature=self.temperature,
            extra_body=extra,
        )
        choice = response.choices[0]
        message = choice.message
        usage = getattr(response, "usage", None)
        usage_d = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        finish_reason = getattr(choice, "finish_reason", None)
        tool_calls = message.tool_calls or []
        if not tool_calls:  # defensive: required should guarantee one -> bounce
            return ProposeResult(
                queryable=None, content=message.content, tool_call_id=None,
                assistant_message={"role": "assistant", "content": message.content or ""},
                usage=usage_d, finish_reason=finish_reason, n_tool_calls=0,
            )
        call = tool_calls[0]
        # Route the tool call by name to its query type; a malformed / unknown / bad-shape
        # call yields queryable=None so the controller bounces it (no inline-JSON recovery).
        queryable: Queryable | None = None
        qt = by_name.get(call.function.name)
        if qt is not None:
            try:
                args = json.loads(call.function.arguments or "{}")
                queryable = qt.from_tool_arguments(args)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                queryable = None
        assistant_message = {
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
        return ProposeResult(
            queryable=queryable,
            content=message.content,
            tool_call_id=call.id,
            assistant_message=assistant_message,
            usage=usage_d,
            finish_reason=finish_reason,
            n_tool_calls=len(tool_calls),
        )


class Searcher(BaseSearcher):
    """The cover-query searcher: one GCL cover per turn (the default searcher)."""

    prompt: str = _PROMPT
    system_prompt: str = _PROMPT  # alias; the controller seeds msgs from this
    query_types: list[type[Queryable]] = [CoverQuery]
