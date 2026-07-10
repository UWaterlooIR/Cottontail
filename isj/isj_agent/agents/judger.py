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

    `verdict` is None iff the call failed (LLM error or a Verdict that did not
    validate) after ALL retries; `error` then aggregates every attempt's message.
    Transient failures are retried here (TASK-27, up to 2 retries after the first
    attempt); the controller's policy for a still-failed call is the grade -2
    sentinel entry, and only a fully-failed WAVE aborts the intent. `request` is
    the VERBATIM messages sent (including the full document) so the trace can
    reconstruct the call; content/reasoning/usage/duration describe the FINAL
    attempt; `retries` counts attempts beyond the first.
    """

    verdict: Verdict | None
    request: list[dict]
    content: str | None  # the model's final-channel output (the JSON verdict)
    reasoning: str | None  # the model's thinking trace (reasoning_content), if exposed
    usage: dict = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str | None = None
    retries: int = 0


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
        reasoning_effort: str | None = "medium",
        temperature: float = 0.0,
        max_tokens: int | None = 8000,
        timeout_s: float | None = 120.0,
    ) -> None:
        self.client = client
        self.model = model
        self.concurrency = concurrency
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        # BOUND the generation (TASK-37): a judge that falls into gpt-oss's reasoning
        # loop spews tokens unbounded (guided decoding constrains only the FINAL channel,
        # not the reasoning channel) and, because judge() waves on a barrier, hangs the
        # whole run. A cap/timeout -> parse failure -> the retry -> grade -2 path. Normal
        # medium-effort judge completions are ~400-900 tokens, so 8000 is ample headroom.
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

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

    # Attempts per document: the first call plus up to (RETRIES) fresh re-calls.
    # Empty completions / transport hiccups are overwhelmingly transient (TASK-27).
    RETRIES: int = 2

    def _judge_one(self, intent: str, summary: str, document: str) -> JudgeCall:
        """One document, with retries: returns the first successful attempt's
        JudgeCall (retries recorded); if every attempt fails, the LAST attempt's
        JudgeCall with `error` aggregating all attempts' messages."""
        failures: list[str] = []
        call = None
        for attempt in range(1 + self.RETRIES):
            call = self._attempt(intent, summary, document)
            call.retries = attempt
            if call.error is None and call.verdict is not None:
                return call
            failures.append(f"attempt {attempt + 1}: {call.error}")
        call.error = "; ".join(failures)
        return call

    def _attempt(self, intent: str, summary: str, document: str) -> JudgeCall:
        messages = [
            {"role": "user", "content": _fill(self.prompt, intent, summary, document)}
        ]
        extra = (
            {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        )
        bound = {}  # token cap + per-call timeout (TASK-37); omit when unset
        if self.max_tokens is not None:
            bound["max_tokens"] = self.max_tokens
        if self.timeout_s is not None:
            bound["timeout"] = self.timeout_s
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
                **bound,
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
