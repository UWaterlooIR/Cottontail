import json
from types import SimpleNamespace

import pytest

from isj_agent.agents.searcher import ProposeResult, Searcher
from isj_agent.protocol.queryable import CoverQuery


def _stub():
    return StubClient(SimpleNamespace(content="", tool_calls=[_tool_call("(^ a)")]))


def test_prompt_override_replaces_the_bundled_system_prompt(tmp_path):
    p = tmp_path / "custom.md"
    p.write_text("CUSTOM DIRECTED PROMPT", encoding="utf-8")
    s = Searcher(_stub(), "stub-model", prompt=str(p))
    assert s.system_prompt == "CUSTOM DIRECTED PROMPT"
    assert s.system_prompt != Searcher.system_prompt  # differs from the bundled default


def test_prompt_none_keeps_the_bundled_default():
    s = Searcher(_stub(), "stub-model")
    assert s.system_prompt == Searcher.system_prompt  # the class's bundled searcher.md


def test_missing_prompt_file_fails_loud():
    with pytest.raises(FileNotFoundError):
        Searcher(_stub(), "stub-model", prompt="/no/such/prompt/file.md")


# --- a stub OpenAI client returning one scripted assistant message ---------

def _tool_call(query, cid="c1"):
    return SimpleNamespace(
        id=cid, type="function",
        function=SimpleNamespace(name="cover_search", arguments=json.dumps({"query": query})),
    )


def _response(message, ptok=120, ctok=8):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=("tool_calls" if message.tool_calls else "stop"))],
        usage=SimpleNamespace(prompt_tokens=ptok, completion_tokens=ctok, total_tokens=ptok + ctok),
    )


class StubClient:
    def __init__(self, message):
        self._message = message
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _response(self._message)


def _searcher(message):
    return Searcher(StubClient(message), "stub-model")


# --- tests -----------------------------------------------------------------

def test_propose_returns_query_and_appendable_assistant_message():
    msg = SimpleNamespace(content="let me try the obvious cover", tool_calls=[_tool_call("(^ black bear*)")])
    s = _searcher(msg)
    r = s.propose([{"role": "user", "content": "Question: bears"}])
    assert isinstance(r, ProposeResult)
    assert r.queryable == CoverQuery("(^ black bear*)")
    assert r.queryable.query_string() == "(^ black bear*)"
    assert r.content == "let me try the obvious cover"
    assert r.tool_call_id == "c1"
    assert r.n_tool_calls == 1
    # the assistant message is appendable verbatim and carries the tool call
    assert r.assistant_message["role"] == "assistant"
    assert r.assistant_message["tool_calls"][0]["function"]["name"] == "cover_search"


def test_propose_forces_the_search_tool():
    s = _searcher(SimpleNamespace(content="", tool_calls=[_tool_call("(^ a b)")]))
    s.propose([{"role": "user", "content": "q"}])
    kwargs = s.client.calls[0]
    assert kwargs["tool_choice"] == "required"
    names = [t["function"]["name"] for t in kwargs["tools"]]
    assert names == ["cover_search"]  # exactly one tool offered; there is no judge tool


def test_propose_forwards_reasoning_effort():
    s = Searcher(StubClient(SimpleNamespace(content="", tool_calls=[_tool_call("(^ a)")])),
                 "stub-model", reasoning_effort="high")
    s.propose([{"role": "user", "content": "q"}])
    assert s.client.calls[0]["extra_body"] == {"reasoning_effort": "high"}


def test_propose_captures_usage():
    s = _searcher(SimpleNamespace(content="", tool_calls=[_tool_call("(^ a)")]))
    r = s.propose([{"role": "user", "content": "q"}])
    assert r.usage == {"prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128}


def test_no_tool_call_yields_none_query_defensively():
    # tool_choice=required should prevent this, but if it happens the controller bounces it.
    s = _searcher(SimpleNamespace(content="I am confused", tool_calls=None))
    r = s.propose([{"role": "user", "content": "q"}])
    assert r.queryable is None and r.n_tool_calls == 0
    assert "tool_calls" not in r.assistant_message


def test_malformed_arguments_json_yields_none_query():
    # known tool (cover_search) but unparseable arguments -> bounce (queryable None)
    bad = SimpleNamespace(id="c", type="function",
                          function=SimpleNamespace(name="cover_search", arguments="{not json"))
    s = _searcher(SimpleNamespace(content="", tool_calls=[bad]))
    r = s.propose([{"role": "user", "content": "q"}])
    assert r.queryable is None


def test_unknown_tool_name_yields_none_query():
    # a tool call for a tool this searcher does not offer -> bounce (queryable None)
    other = SimpleNamespace(id="c", type="function",
                            function=SimpleNamespace(name="mystery", arguments=json.dumps({"query": "(^ a)"})))
    s = _searcher(SimpleNamespace(content="", tool_calls=[other]))
    r = s.propose([{"role": "user", "content": "q"}])
    assert r.queryable is None


def test_searcher_has_prompt_without_judging():
    assert "GCL" in Searcher.prompt
    # the searcher authors queries; a separate assessor grades (the searcher does not judge)
    assert "assessor" in Searcher.prompt.lower()


# --- TASK-37: bounded generation (max_tokens + per-call timeout) ---------------

def test_propose_bounds_generation_by_default():
    s = _searcher(SimpleNamespace(content="", tool_calls=[_tool_call("(^ a)")]))
    assert s.max_tokens == 16000 and s.timeout_s == 180.0
    s.propose([{"role": "user", "content": "q"}])
    call = s.client.calls[0]
    assert call["max_tokens"] == 16000 and call["timeout"] == 180.0


def test_propose_generation_bounds_are_configurable():
    s = Searcher(StubClient(SimpleNamespace(content="", tool_calls=[_tool_call("(^ a)")])),
                 "stub-model", max_tokens=2222, timeout_s=9.0)
    s.propose([{"role": "user", "content": "q"}])
    call = s.client.calls[0]
    assert call["max_tokens"] == 2222 and call["timeout"] == 9.0
