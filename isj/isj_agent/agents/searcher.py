"""The Searcher: a thin GCL query author (TASK-16).

INPUT: the running conversation (its prior queries and their judged outcomes, which
the CONTROLLER builds). OUTPUT: exactly ONE GCL cover query per turn, via a single
`search` tool with `tool_choice="required"` -- so the Searcher always issues a query;
there is no decline / finish / no-tool-call path.

The Searcher does NOT judge and has no relevance scale: judging is the Judger's job,
and the loop, paging, de-duplication, budget, and trace are the controller's. This
class is deliberately as thin as the Analyst -- one LLM round-trip that returns the
chosen query plus the assistant message to append. The controller owns the message
list and the trace, and feeds each query's judged outcome back as the tool result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files

import openai

_PROMPT: str = (
    files("isj_agent.agents").joinpath("searcher.md").read_text(encoding="utf-8")
)

# One tool: the model writes only the GCL `query`; the controller injects everything
# else (exclude/top_k/window) when it runs the query. tool_choice="required" forces a
# call -- with a single tool offered that is always `search`.
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Run a GCL cover query over the collection. Returns the NEW documents it "
                "surfaces, each already graded (0-3) with a reason, plus a count of results "
                "at those ranks that were already judged by earlier queries."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


@dataclass
class ProposeResult:
    """One Searcher round-trip: the chosen query + what the controller needs to continue.

    `query` is None only in the defensive case where the model returned no tool call
    despite tool_choice="required" (the controller bounces it back). `assistant_message`
    is appended verbatim to the conversation; `tool_call_id` keys the matching tool
    result the controller appends next.
    """

    query: str | None
    content: str | None  # the assistant's reasoning text (for the trace)
    tool_call_id: str | None
    assistant_message: dict
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None
    n_tool_calls: int = 0


class Searcher:
    """Proposes one GCL query per call, given the running conversation."""

    prompt: str = _PROMPT
    system_prompt: str = _PROMPT  # alias; the controller seeds msgs from this

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        *,
        reasoning_effort: str | None = "high",
        temperature: float = 0.0,
    ) -> None:
        self.client = client
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature

    def propose(self, messages: list[dict]) -> ProposeResult:
        """One LLM round-trip. May RAISE on an LLM/transport failure -- the controller
        catches it and returns a partial result (it owns persist-on-failure)."""
        extra = (
            {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=_TOOLS,
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
        tool_calls = message.tool_calls or []
        if not tool_calls:  # defensive: required should guarantee one
            return ProposeResult(
                query=None, content=message.content, tool_call_id=None,
                assistant_message={"role": "assistant", "content": message.content or ""},
                usage=usage_d, finish_reason=getattr(choice, "finish_reason", None),
                n_tool_calls=0,
            )
        call = tool_calls[0]
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
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
            query=args.get("query"),
            content=message.content,
            tool_call_id=call.id,
            assistant_message=assistant_message,
            usage=usage_d,
            finish_reason=getattr(choice, "finish_reason", None),
            n_tool_calls=len(tool_calls),
        )
