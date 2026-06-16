from isj_agent.cli import format_intents
from isj_agent.protocol.intents import Intents


def test_format_intents():
    intents = Intents(question="What is X?", interpretations=["first", "second"])
    out = format_intents(intents)
    assert "What is X?" in out
    assert "1. first" in out
    assert "2. second" in out
