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
        max_tokens: int | None = 8000,
        timeout_s: float | None = 120.0,
    ) -> None:
        self.client = client
        self.model = model
        self.reasoning_effort = reasoning_effort
        # BOUND the generation (TASK-37): one call per run, but the same runaway-reasoning
        # pathology -> bound it so analysis can't hang the run start.
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    def analyze(self, question: str) -> Intents:
        extra = (
            {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        )
        bound = {}  # token cap + per-call timeout (TASK-37); omit when unset
        if self.max_tokens is not None:
            bound["max_tokens"] = self.max_tokens
        if self.timeout_s is not None:
            bound["timeout"] = self.timeout_s
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
            **bound,
        )
        content = response.choices[0].message.content
        return Intents.model_validate_json(content)
