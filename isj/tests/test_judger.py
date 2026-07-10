import json
import re
from types import SimpleNamespace

import pytest

from isj_agent.agents.judger import JudgeCall, Judger
from isj_agent.protocol.search import Verdict


# --- a stub OpenAI client whose create() derives the grade from the document ----
# Each document embeds a marker "[[GRADE:n]]"; the stub returns that grade. Because
# the grade is a function of the input, asserting the returned grades match the input
# order proves the Judger keeps results aligned to inputs (despite parallel completion).

def _message(content, reasoning=None):
    return SimpleNamespace(content=content, reasoning_content=reasoning)


def _response(content, reasoning=None, ptok=100, ctok=20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=_message(content, reasoning))],
        usage=SimpleNamespace(prompt_tokens=ptok, completion_tokens=ctok, total_tokens=ptok + ctok),
    )


class StubClient:
    def __init__(self, handler):
        self._handler = handler
        self.calls = []  # kwargs of every create() call
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._handler(kwargs)


def _grade_from_doc(kwargs):
    """Default handler: read [[GRADE:n]] out of the prompt and return that Verdict."""
    prompt = kwargs["messages"][0]["content"]
    g = int(re.search(r"\[\[GRADE:(\d)\]\]", prompt).group(1))
    return _response(json.dumps({"reason": f"graded {g}", "grade": g}), reasoning="thinking...")


def _judger(handler=_grade_from_doc, **kw):
    return Judger(StubClient(handler), "stub-model", **kw)


def _docs(grades):
    return [(f"summary-{g}", f"body [[GRADE:{g}]]") for g in grades]


# --- tests -----------------------------------------------------------------

def test_judge_aligns_results_to_input_order():
    grades = [3, 0, 2, 1, 0]
    calls = _judger(concurrency=4).judge("intent", _docs(grades))
    assert [c.verdict.grade for c in calls] == grades  # order preserved despite parallelism
    assert all(isinstance(c, JudgeCall) and c.error is None for c in calls)
    assert all(isinstance(c.verdict, Verdict) for c in calls)


def test_verdict_has_no_cp():
    [call] = _judger().judge("intent", _docs([2]))
    assert not hasattr(call.verdict, "cp")  # the model never emits a cp


def test_prompt_carries_intent_summary_document_no_cp():
    j = _judger()
    j.judge("my intent", [("the summary", "the document body [[GRADE:1]]")])
    prompt = j.client.calls[0]["messages"][0]["content"]
    assert "my intent" in prompt and "the summary" in prompt and "the document body" in prompt
    assert "cp" not in prompt.lower().split()  # no bare 'cp' token handed to the model


def test_reasoning_effort_forwarded_via_extra_body():
    j = _judger(reasoning_effort="high")
    j.judge("intent", _docs([2]))
    assert j.client.calls[0]["extra_body"] == {"reasoning_effort": "high"}
    # response_format pins the Verdict schema for guided decoding
    assert j.client.calls[0]["response_format"]["json_schema"]["name"] == "Verdict"


def test_no_reasoning_effort_means_empty_extra_body():
    j = _judger(reasoning_effort=None)
    j.judge("intent", _docs([0]))
    assert j.client.calls[0]["extra_body"] == {}


def test_captures_usage_and_reasoning_for_trace():
    [call] = _judger().judge("intent", _docs([3]))
    assert call.usage["prompt_tokens"] == 100 and call.usage["completion_tokens"] == 20
    assert call.reasoning == "thinking..."
    assert call.request[0]["content"]  # verbatim request retained (incl document)


def test_llm_failure_is_surfaced_not_raised():
    def boom(kwargs):
        raise RuntimeError("context length exceeded")

    [call] = _judger(boom).judge("intent", _docs([2]))
    assert call.verdict is None and "context length exceeded" in call.error


def test_unparseable_output_sets_error():
    def junk(kwargs):
        return _response("not json at all")

    [call] = _judger(junk).judge("intent", _docs([2]))
    assert call.verdict is None
    # TASK-27: the failure was retried; error aggregates every attempt.
    assert call.retries == 2
    assert call.error.count("verdict parse") == 3
    assert call.error.startswith("attempt 1: verdict parse")


def test_one_bad_call_does_not_sink_the_others():
    def selective(kwargs):
        if "[[GRADE:9]]" in kwargs["messages"][0]["content"]:
            raise RuntimeError("nope")
        return _grade_from_doc(kwargs)

    docs = [("s", "ok [[GRADE:2]]"), ("s", "bad [[GRADE:9]]"), ("s", "ok [[GRADE:1]]")]
    calls = _judger(selective, concurrency=3).judge("intent", docs)
    assert calls[0].verdict.grade == 2
    assert calls[1].verdict is None and calls[1].error
    assert calls[2].verdict.grade == 1


def test_empty_docs_returns_empty():
    assert _judger().judge("intent", []) == []


def test_transient_failure_retried_then_succeeds():
    # TASK-27: attempt 1 returns an empty completion (the observed vLLM hiccup),
    # attempt 2 succeeds -> a normal verdict with retries recorded.
    state = {"n": 0}

    def flaky(kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return _response("")  # empty completion -> Verdict parse failure
        return _response(json.dumps({"reason": "fine", "grade": 2}))

    [call] = _judger(flaky).judge("intent", _docs([2]))
    assert call.verdict is not None and call.verdict.grade == 2
    assert call.error is None
    assert call.retries == 1
    assert state["n"] == 2  # exactly one retry


def test_permanent_transport_failure_aggregates_attempts():
    def boom(kwargs):
        raise RuntimeError("connection dropped")

    [call] = _judger(boom).judge("intent", _docs([2]))
    assert call.verdict is None
    assert call.retries == 2
    assert call.error.count("RuntimeError") == 3  # all three attempts recorded


# --- TASK-37: bounded generation (max_tokens + per-call timeout) ---------------

def test_judger_bounds_generation_by_default():
    j = _judger()
    assert j.max_tokens == 8000 and j.timeout_s == 120.0
    j.judge("intent", _docs([2]))
    call = j.client.calls[0]
    assert call["max_tokens"] == 8000 and call["timeout"] == 120.0


def test_judger_generation_bounds_are_configurable():
    j = _judger(max_tokens=1234, timeout_s=7.5)
    j.judge("intent", _docs([1]))
    call = j.client.calls[0]
    assert call["max_tokens"] == 1234 and call["timeout"] == 7.5


def test_judger_omits_bounds_when_set_to_none():
    j = _judger(max_tokens=None, timeout_s=None)
    j.judge("intent", _docs([1]))
    call = j.client.calls[0]
    assert "max_tokens" not in call and "timeout" not in call
