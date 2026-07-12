"""Context compaction: Controller._maybe_compact / _shrink_message (TASK-40.3).

Unit-level: a Controller built with stub agents, driving _maybe_compact over a hand-made
msgs list. Trigger is the server-reported prompt_tokens vs compact_trigger * context_limit.
"""

import math

from isj_agent.controller import Controller

HEADER = "## Cited passages"


def _ctl(**kw):
    # searcher/judger/engine are unused by the compaction path; pass None.
    return Controller(None, None, None, **kw)


def _report(k: str, *, with_header=True, tail=2000) -> str:
    prose = f"Your query: q{k}\nWhat is working: keep pursuing beavers.\nVocabulary worth pursuing: dam, lodge."
    if with_header:
        return prose + "\n\n" + HEADER + "\n" + ("EXCERPT " * (tail // 8))
    return "NOHEADER " * (tail // 9)  # no '## Cited passages' -> hard-truncate path


def _msgs(n_tools: int, *, with_header=True):
    """system, user, then n interleaved (assistant tool-call, tool) pairs."""
    msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "Question: q"}]
    for k in range(n_tools):
        cid = f"c{k}"
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"id": cid, "type": "function",
                                     "function": {"name": "cover_search", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": cid, "content": _report(str(k), with_header=with_header)})
    return msgs


def _tool_idx(msgs):
    return [i for i, m in enumerate(msgs) if m.get("role") == "tool"]


def _shape(msgs):
    # a protocol-safety fingerprint: (role, tool_call_id) per message; must be invariant.
    return [(m.get("role"), m.get("tool_call_id")) for m in msgs]


def _emitter():
    events = []
    return events, (lambda type_, ts, dur, **f: events.append({"type": type_, **f}))


# --- no-op guards --------------------------------------------------------------

def test_no_context_limit_is_noop():
    msgs = _msgs(4)
    before = [m["content"] for m in msgs]
    events, emit = _emitter()
    _ctl(context_limit=None)._maybe_compact(msgs, 999999, set(), emit)
    assert [m["content"] for m in msgs] == before and events == []


def test_under_trigger_is_noop():
    msgs = _msgs(4)
    before = [m["content"] for m in msgs]
    events, emit = _emitter()
    # threshold = 0.8 * 1000 = 800; 700 is under.
    _ctl(context_limit=1000, compact_trigger=0.8)._maybe_compact(msgs, 700, set(), emit)
    assert [m["content"] for m in msgs] == before and events == []


def test_none_prompt_tokens_is_noop():
    msgs = _msgs(4)
    before = [m["content"] for m in msgs]
    events, emit = _emitter()
    _ctl(context_limit=1000)._maybe_compact(msgs, None, set(), emit)
    assert [m["content"] for m in msgs] == before and events == []


def test_single_tool_message_is_noop():
    msgs = _msgs(1)
    before = [m["content"] for m in msgs]
    events, emit = _emitter()
    _ctl(context_limit=1000)._maybe_compact(msgs, 900, set(), emit)
    assert [m["content"] for m in msgs] == before and events == []


# --- the shrink pass -----------------------------------------------------------

def test_over_trigger_shrinks_oldest_half_never_last():
    msgs = _msgs(5)                       # tool msgs at positions with 5 candidates -> last excluded
    shape = _shape(msgs)
    tool_idx = _tool_idx(msgs)
    shrunk = set()
    events, emit = _emitter()
    _ctl(context_limit=1000, compact_trigger=0.8)._maybe_compact(msgs, 850, shrunk, emit)

    # candidates = first 4 tool msgs; ceil(4/2) = 2 oldest shrunk.
    assert shrunk == {tool_idx[0], tool_idx[1]}
    for i in tool_idx[:2]:
        assert HEADER not in msgs[i]["content"] and msgs[i]["content"].startswith("Your query:")
    # ranks 3-4 (not yet in this pass) and the LAST tool msg keep their header intact.
    for i in tool_idx[2:]:
        assert HEADER in msgs[i]["content"]
    # protocol-safe: message count + every role/tool_call_id unchanged; non-tool msgs untouched.
    assert _shape(msgs) == shape
    assert msgs[0]["content"] == "SYS" and all(m["content"] == "" for m in msgs if m["role"] == "assistant")
    # a compact event recorded the pass.
    assert events == [{"type": "compact", "prompt_tokens": 850, "shrunk": 2, "tool_messages": 5}]


def test_shrink_drops_cited_section_keeps_prose():
    ctl = _ctl(context_limit=1000)
    m = {"role": "tool", "tool_call_id": "c", "content": _report("7", with_header=True)}
    ctl._shrink_message(m)
    assert HEADER not in m["content"]
    assert "Vocabulary worth pursuing: dam, lodge." in m["content"]  # prose + vocab line kept
    assert not m["content"].endswith("\n")  # rstripped


def test_shrink_hard_truncates_when_no_header():
    ctl = _ctl(context_limit=1000, shrink_truncate_tokens=50)  # keep = 200 chars
    body = _report("7", with_header=False)
    assert HEADER not in body and len(body) > 200
    m = {"role": "tool", "tool_call_id": "c", "content": body}
    ctl._shrink_message(m)
    assert m["content"].endswith("...[older feedback truncated]")
    assert len(m["content"]) < len(body)


def test_repeated_triggers_halve_the_remaining_unshrunk():
    msgs = _msgs(9)                        # candidates = 8 (last excluded)
    tool_idx = _tool_idx(msgs)
    shrunk = set()
    ctl = _ctl(context_limit=1000, compact_trigger=0.8)

    got = []
    for _ in range(5):
        events, emit = _emitter()
        ctl._maybe_compact(msgs, 900, shrunk, emit)
        got.append(events[0]["shrunk"] if events and events[0].get("pass_") is None else None)

    # 8 candidates: ceil(8/2)=4, then 4->2, 2->1, 1->1(last remaining), then floor pass.
    assert got[:4] == [4, 2, 1, 1]
    # every candidate ends up shrunk; the last tool message is never touched.
    assert shrunk == set(tool_idx[:-1])
    assert HEADER in msgs[tool_idx[-1]]["content"]


def test_floor_pass_hard_truncates_when_all_but_last_shrunk():
    # All non-last tool messages already shrunk (header dropped) but STILL over trigger:
    # the degenerate floor path hard-truncates them and emits a floor compact event.
    msgs = _msgs(3, with_header=False)     # no header -> _shrink already hard-truncates
    tool_idx = _tool_idx(msgs)
    ctl = _ctl(context_limit=1000, compact_trigger=0.8, shrink_truncate_tokens=50)
    shrunk = set(tool_idx[:-1])            # pretend the first two are already shrunk
    # make them long again so the floor truncate actually shortens something
    for i in tool_idx[:-1]:
        msgs[i]["content"] = "Z" * 5000
    events, emit = _emitter()
    ctl._maybe_compact(msgs, 900, shrunk, emit)
    assert events and events[0]["type"] == "compact" and events[0].get("pass_") == "floor"
    for i in tool_idx[:-1]:
        assert msgs[i]["content"].endswith("...[older feedback truncated]")
