from isj_agent.agents.analyst import Analyst


class Orchestrator:
    """Drives the agentic ISJ investigation loop (§5 of the spec).

    Agents are injected at construction — the Orchestrator does not build them.
    """

    def __init__(self, *, analyst: Analyst) -> None:
        self.analyst = analyst
