"""The Orchestrator: drive one question end to end (C3).

Analyst.analyze(question) -> Intents; then, per interpretation in order,
Searcher.run(interpretation) over the live engine -> a SearcherResult (or, on
failure, a RunError). Agents are injected at construction. The Orchestrator does
NOT write files (C2's write_run does), does NOT fuse, and does NOT generate the
trace (the Searcher emits it). One failed intent must not abort the rest.
"""

from __future__ import annotations

from collections.abc import Callable

from isj_agent.agents.analyst import Analyst
from isj_agent.agents.searcher import Searcher
from isj_agent.protocol.intents import Intents
from isj_agent.run_output import Outcome, RunError


class Orchestrator:
    """Runs Analyst -> per-intent Searcher for one question."""

    def __init__(self, *, analyst: Analyst, searcher: Searcher) -> None:
        self.analyst = analyst
        self.searcher = searcher

    def run_question(
        self,
        question: str,
        *,
        on_intent: Callable[[int, str, Outcome], None] | None = None,
    ) -> tuple[Intents | None, list[Outcome], str | None]:
        """Analyze, then run the Searcher per interpretation.

        Returns (intents, outcomes, run_error): `outcomes` is one entry per
        interpretation, in order -- a SearcherResult on success, a RunError on a
        per-intent failure (the run continues). If analysis itself fails (no
        interpretations), returns (None, [], <message>). `on_intent(i, interp,
        outcome)` is called after each interpretation (for live --verbose rendering).
        """
        try:
            intents = self.analyst.analyze(question)
        except Exception as exc:  # run-level failure: analysis produced nothing
            return None, [], f"analysis failed: {type(exc).__name__}: {exc}"

        outcomes: list[Outcome] = []
        for i, interp in enumerate(intents.interpretations):
            try:
                outcome: Outcome = self.searcher.run(interp)
            except Exception as exc:  # one failed intent must not abort the rest
                outcome = RunError(message=f"{type(exc).__name__}: {exc}")
            outcomes.append(outcome)
            if on_intent is not None:
                on_intent(i, interp, outcome)
        return intents, outcomes, None
