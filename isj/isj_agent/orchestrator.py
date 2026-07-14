"""The Orchestrator: drive one question end to end (C3).

Analyst.analyze(question) -> Intents; then, per interpretation in order,
Controller.run(interpretation, intent_budget) over the live engine -> a
SearcherResult (or, on failure, a RunError). The run-total judgment budget
`max_judgments` is split EVENLY across the interpretations (intent_budget =
max_judgments // num_intents, >=1). Agents/controller are injected at construction.
The Orchestrator does NOT write files (C2's write_run does), does NOT fuse, and does
NOT generate the trace (the Controller emits it). One failed intent must not abort
the rest.
"""

from __future__ import annotations

from collections.abc import Callable

from isj_agent.agents.analyst import Analyst
from isj_agent.controller import Controller
from isj_agent.protocol.intents import Intents
from isj_agent.protocol.results import LiveMarker, TraceEvent
from isj_agent.run_output import Outcome, RunError


class Orchestrator:
    """Runs Analyst -> per-intent Controller for one question."""

    def __init__(
        self, analyst: Analyst | None, controller: Controller, *, max_judgments: int = 1000
    ) -> None:
        self.analyst = analyst  # may be None when a precomputed `intents` is supplied to run_question
        self.controller = controller
        self.max_judgments = max_judgments

    def run_question(
        self,
        question: str,
        *,
        intents: Intents | None = None,
        on_intent: Callable[[int, str, Outcome], None] | None = None,
        observer: Callable[[int, TraceEvent | LiveMarker], None] | None = None,
        on_analyzed: Callable[[Intents], None] | None = None,
    ) -> tuple[Intents | None, list[Outcome], str | None]:
        """Analyze, then run the Controller per interpretation with the split budget.

        Returns (intents, outcomes, run_error): `outcomes` is one entry per
        interpretation, in order -- a SearcherResult on success, a RunError on a
        per-intent failure (the run continues). If analysis itself fails (no
        interpretations), returns (None, [], <message>).

        `intents`, if given, is a precomputed analysis (e.g. loaded from an analysis artifact,
        TASK-41): the Analyst is skipped entirely and these interpretations drive the run, so one
        analysis can feed many searcher configs. When None, the Analyst produces them.

        Callbacks (all optional, for live observability -- TASK-35):
        - `on_analyzed(intents)` fires once, right after analysis succeeds (before any
          intent runs), so a caller can open the run directory / write intents.json.
        - `observer(i, event_or_marker)` fires the MOMENT the Controller for intent `i`
          emits each trace event (or a live-only pre-call marker) -- a real-time stream.
        - `on_intent(i, interp, outcome)` fires after each interpretation completes.
        """
        if intents is None:
            try:
                intents = self.analyst.analyze(question)
            except Exception as exc:  # run-level failure: analysis produced nothing
                return None, [], f"analysis failed: {type(exc).__name__}: {exc}"

        if on_analyzed is not None:
            on_analyzed(intents)

        n = len(intents.interpretations)
        intent_budget = max(1, self.max_judgments // n)  # even split; >=1 each
        outcomes: list[Outcome] = []
        for i, interp in enumerate(intents.interpretations):
            obs = (lambda ev, i=i: observer(i, ev)) if observer is not None else None
            try:
                outcome: Outcome = self.controller.run(
                    interp, intent_budget,
                    question=intents.question, interpretations=intents.interpretations,
                    observer=obs,
                )
            except Exception as exc:  # one failed intent must not abort the rest
                outcome = RunError(message=f"{type(exc).__name__}: {exc}")
            outcomes.append(outcome)
            if on_intent is not None:
                on_intent(i, interp, outcome)
        return intents, outcomes, None
