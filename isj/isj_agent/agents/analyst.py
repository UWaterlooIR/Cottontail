from importlib.resources import files

import openai

from isj_agent.protocol.intents import Intents

_PROMPT: str = (
    files("isj_agent.agents").joinpath("analyst.md").read_text(encoding="utf-8")
)


class Analyst:
    """Infers what a user is looking for, as an Intents object.

    The prompt is part of this class's implementation — see analyst.md.
    One instance can analyze many questions sequentially.
    """

    prompt: str = _PROMPT

    def __init__(self, client: openai.OpenAI, model: str) -> None:
        self.client = client
        self.model = model

    def analyze(self, question: str) -> Intents:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": question},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "Intents",
                    "schema": Intents.model_json_schema(),
                },
            },
        )
        content = response.choices[0].message.content
        return Intents.model_validate_json(content)
