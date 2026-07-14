from pydantic import BaseModel, Field


class Intents(BaseModel):
    """Analyst output: the user question plus the things to find for it.

    interpretations must be non-empty. Each is a self-contained, search-ready
    statement of one distinct thing to find for this question -- a reading the user
    might mean, or a component of the answer -- capturing WHAT to find, not WHY. A
    simple need may yield a single item.
    """

    question: str
    interpretations: list[str] = Field(min_length=1)
