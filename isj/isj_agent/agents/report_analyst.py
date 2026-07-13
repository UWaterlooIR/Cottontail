"""ReportAnalyst: an Analyst variant that decomposes a need into report COMPONENTS (TASK-42).

Instead of disambiguating a question into interpretations, the ReportAnalyst breaks the
information need into the pieces of information a RAG report must synthesize -- the distinct
sub-topics, facts, or perspectives that must each be retrieved and combined. It emits the SAME
`Intents{question, interpretations[]}` contract (the components populate `interpretations`), so
nothing downstream (Orchestrator, Controller, analysis artifact, run_output) changes. Select it
via `[agents.analyst].class = "isj_agent.agents.report_analyst.ReportAnalyst"`.

The only difference from `Analyst` is the bundled prompt (report_analyst.md, a shipped copy of
scouting/analyst/prompt-report-v3.md); `analyze()` is inherited and reads `self.prompt`.
"""
from importlib.resources import files

from isj_agent.agents.analyst import Analyst

_PROMPT: str = (
    files("isj_agent.agents").joinpath("report_analyst.md").read_text(encoding="utf-8")
)


class ReportAnalyst(Analyst):
    """Analyst that fills `interpretations[]` with RAG-report components (see module docstring)."""

    prompt: str = _PROMPT
