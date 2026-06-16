from pydantic import BaseModel, Field


class Intents(BaseModel):
    """Analyst output: the user question plus inferred interpretations.

    interpretations is ordered most-plausible-first and must be non-empty.
    Each interpretation is a self-contained, search-ready restatement of one
    thing the user might mean (the WHAT, not the WHY). An unambiguous question
    yields a single interpretation.
    """

    question: str
    interpretations: list[str] = Field(min_length=1)
