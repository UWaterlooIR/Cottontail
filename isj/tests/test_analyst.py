import inspect
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from isj_agent.agents.analyst import Analyst
from isj_agent.config import load_class
from isj_agent.protocol.intents import Intents

_STUB_CLIENT = MagicMock()
_STUB_MODEL = "gpt.oss.120b"


def _analyst() -> Analyst:
    return Analyst(client=_STUB_CLIENT, model=_STUB_MODEL)


def test_analyst_analyze_signature():
    sig = inspect.signature(Analyst.analyze)
    params = list(sig.parameters)
    assert params == ["self", "question"], f"unexpected params: {params}"
    assert sig.return_annotation is Intents


def test_analyst_has_prompt():
    assert isinstance(Analyst.prompt, str)
    assert len(Analyst.prompt) > 0


def test_analyst_stores_client_and_model():
    a = _analyst()
    assert a.client is _STUB_CLIENT
    assert a.model == _STUB_MODEL


def test_load_class_returns_analyst():
    cls = load_class("isj_agent.agents.analyst.Analyst")
    assert cls is Analyst


def test_intents_requires_nonempty():
    Intents(question="q", interpretations=["a"])
    with pytest.raises(ValidationError):
        Intents(question="q", interpretations=[])


def test_analyze_with_mocked_client():
    client = MagicMock()
    content = '{"question": "Q", "interpretations": ["one", "two"]}'
    client.chat.completions.create.return_value.choices[
        0
    ].message.content = content

    a = Analyst(client=client, model="gpt.oss.120b")
    result = a.analyze("Q")

    assert result == Intents(question="Q", interpretations=["one", "two"])
    assert client.chat.completions.create.call_count == 1
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt.oss.120b"
    assert kwargs["response_format"]["json_schema"]["name"] == "Intents"


def test_analyst_bounds_generation_by_default():
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = (
        '{"question": "Q", "interpretations": ["one"]}'
    )
    a = Analyst(client=client, model="gpt.oss.120b")
    assert a.max_tokens == 8000 and a.timeout_s == 120.0
    a.analyze("Q")
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_tokens"] == 8000 and kwargs["timeout"] == 120.0
