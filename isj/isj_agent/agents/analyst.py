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

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        *,
        reasoning_effort: str | None = "medium",
    ) -> None:
        self.client = client
        self.model = model
        self.reasoning_effort = reasoning_effort

    def analyze(self, question: str) -> Intents:
        extra = (
            {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        )
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
            extra_body=extra,
        )
        content = response.choices[0].message.content
        return Intents.model_validate_json(content)
