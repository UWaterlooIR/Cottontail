"""The Judger: grade ONE full document's relevance to an intent (TASK-16).

A thin LLM-role wrapper (like the Analyst) that judges documents POINTWISE: one LLM
call grades one (summary + full document) and returns a `Verdict {reason, grade 0-3}`
via guided decoding. The controller runs a wave of these CONCURRENTLY; the Judger
owns the thread pool. The cp is NEVER sent to the model -- the controller knows which
document each call was for and pairs the returned Verdict with that cp itself.

cp-native (doc-6): no cp/docno enters the prompt or the output. The Judger sees only
the intent, the cover-biased summary (orientation), and the full document text (the
controller truncates it to `max_doc_chars` before calling). Reasoning models
(gpt-oss-120b) think in a separate channel; guided decoding must constrain only the
final-channel output -- LIVE-VERIFY this on the deployed vLLM/gpt-oss stack.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from importlib.resources import files

import openai

from isj_agent.protocol.search import Verdict

_PROMPT: str = (
    files("isj_agent.agents").joinpath("judger.md").read_text(encoding="utf-8")
)


@dataclass
class JudgeCall:
    """The outcome of one judge LLM round-trip (aligned to its input doc by position).

    `verdict` is None iff the call failed (LLM error or a Verdict that did not validate);
    `error` then carries the message. The controller treats any failure as a mid-loop
    failure that aborts the intent with a partial result. `request` is the VERBATIM
    messages sent (including the full document) so the trace can reconstruct the call.
    """

    verdict: Verdict | None
    request: list[dict]
    content: str | None  # the model's final-channel output (the JSON verdict)
    reasoning: str | None  # the model's thinking trace (reasoning_content), if exposed
    usage: dict = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str | None = None


def _fill(template: str, intent: str, summary: str, document: str) -> str:
    # str.replace, NOT str.format -- document text can contain literal braces.
    return (
        template.replace("{intent}", intent)
        .replace("{summary}", summary)
        .replace("{document}", document)
    )


class Judger:
    """Judges documents pointwise (0-3) against an intent, a wave at a time."""

    prompt: str = _PROMPT

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        *,
        concurrency: int = 15,
        reasoning_effort: str | None = "high",
        temperature: float = 0.0,
    ) -> None:
        self.client = client
        self.model = model
        self.concurrency = concurrency
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature

    def judge(self, intent: str, docs: list[tuple[str, str]]) -> list[JudgeCall]:
        """Grade each (summary, document) for `intent`; one LLM call per doc, in parallel.

        Returns one JudgeCall per input, IN INPUT ORDER (the controller zips them back to
        the cps it asked about). Up to `concurrency` calls run at once via a thread pool.
        The empty case returns [] without spinning up a pool.
        """
        if not docs:
            return []
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            return list(pool.map(lambda d: self._judge_one(intent, d[0], d[1]), docs))

    def _judge_one(self, intent: str, summary: str, document: str) -> JudgeCall:
        messages = [
            {"role": "user", "content": _fill(self.prompt, intent, summary, document)}
        ]
        extra = (
            {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        )
        t0 = time.time()
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "Verdict",
                        "schema": Verdict.model_json_schema(),
                    },
                },
                temperature=self.temperature,
                extra_body=extra,
            )
        except Exception as exc:  # LLM/transport failure -> surfaced as a failed call
            return JudgeCall(
                verdict=None, request=messages, content=None, reasoning=None,
                duration_ms=(time.time() - t0) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
            )
        duration_ms = (time.time() - t0) * 1000.0
        message = resp.choices[0].message
        usage = getattr(resp, "usage", None)
        usage_d = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        content = message.content
        reasoning = getattr(message, "reasoning_content", None)
        try:
            verdict = Verdict.model_validate_json(content or "")
            error = None
        except Exception as exc:  # guided decode should prevent this, but be defensive
            verdict = None
            error = f"verdict parse: {type(exc).__name__}: {exc}"
        return JudgeCall(
            verdict=verdict, request=messages, content=content, reasoning=reasoning,
            usage=usage_d, duration_ms=duration_ms, error=error,
        )
