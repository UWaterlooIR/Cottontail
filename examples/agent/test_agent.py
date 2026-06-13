#!/usr/bin/env python3
"""Deterministic harness test for the ReAct loop in search_agent.py.

Stubs both the LLM client and the tool executor (no vLLM, no GPU, no network),
so it asserts the *loop logic*: the model's tool calls are executed in order,
observations are fed back, docids are harvested as citations, and the loop
terminates on a final answer (or the step budget).

Run:  uv run examples/agent/test_agent.py     (or: python3 examples/agent/test_agent.py)
"""

import json
import types
import unittest

from search_agent import run_agent


def _resp(tool_calls=None, content=None):
    """Build a fake OpenAI chat-completion response."""
    tcs = None
    if tool_calls:
        tcs = [
            types.SimpleNamespace(
                id=f"call_{i}", type="function",
                function=types.SimpleNamespace(name=n, arguments=json.dumps(a)),
            )
            for i, (n, a) in enumerate(tool_calls)
        ]
    msg = types.SimpleNamespace(content=content, tool_calls=tcs)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


class FakeClient:
    """Returns scripted responses; records each create() call."""

    def __init__(self, script):
        self._script = list(script)
        self.requests = []

    # client.chat.completions.create(...)
    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self._script.pop(0)


class ReActLoopTest(unittest.TestCase):
    def test_search_then_read_then_answer(self):
        script = [
            _resp(tool_calls=[("search_text", {"query": "elephants", "top_k": 5})]),
            _resp(tool_calls=[("get_document", {"docid": "d-1"})]),
            _resp(content="Elephants disappeared from the Middle East. [d-1]"),
        ]
        client = FakeClient(script)

        seen = []

        def fake_tool(name, args):
            seen.append((name, args))
            if name == "search_text":
                return {"results": [{"docid": "d-1", "score": 1.0},
                                    {"docid": "d-2", "score": 0.5}],
                        "result_count": 2, "truncated": False}
            if name == "get_document":
                return {"docid": "d-1", "found": True, "text": "Elephants ..."}
            return {"error": "unexpected"}

        res = run_agent(client, "m", tools=[], call_tool=fake_tool,
                        question="where did the elephants go?", max_steps=5)

        self.assertEqual(res["stopped"], "answer")
        self.assertTrue(res["answer"].startswith("Elephants"))
        # tools were executed in the order the model asked for them
        self.assertEqual([n for n, _ in seen], ["search_text", "get_document"])
        self.assertEqual(seen[0][1], {"query": "elephants", "top_k": 5})
        # docids from search results + the read doc are harvested as citations
        self.assertIn("d-1", res["citations"])
        self.assertIn("d-2", res["citations"])
        # three model turns: two tool rounds + the final answer
        self.assertEqual(len(client.requests), 3)
        # tools are advertised to the model on every turn
        self.assertEqual(client.requests[0]["tools"], [])

    def test_observations_are_fed_back(self):
        script = [
            _resp(tool_calls=[("search_text", {"query": "x"})]),
            _resp(content="done"),
        ]
        client = FakeClient(script)
        run_agent(client, "m", tools=[],
                  call_tool=lambda n, a: {"results": [], "result_count": 0},
                  question="q", max_steps=5)
        # second request carries the assistant tool_call + the tool observation
        second = client.requests[1]["messages"]
        roles = [m["role"] for m in second]
        self.assertIn("assistant", roles)
        self.assertIn("tool", roles)
        tool_msg = [m for m in second if m["role"] == "tool"][0]
        self.assertEqual(json.loads(tool_msg["content"]) ["result_count"], 0)

    def test_step_budget(self):
        # model never stops calling tools -> loop terminates on the budget
        script = [_resp(tool_calls=[("search_text", {"query": "x"})])
                  for _ in range(10)]
        client = FakeClient(script)
        res = run_agent(client, "m", tools=[],
                        call_tool=lambda n, a: {"results": []},
                        question="q", max_steps=3)
        self.assertEqual(res["stopped"], "budget")
        self.assertIsNone(res["answer"])
        self.assertEqual(res["steps"], 3)
        self.assertEqual(len(client.requests), 3)


if __name__ == "__main__":
    unittest.main()
