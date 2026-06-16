import argparse
import tomllib
from pathlib import Path

from isj_agent.config import build_client, load_class
from isj_agent.orchestrator import Orchestrator
from isj_agent.protocol.intents import Intents

SAMPLE_QUESTIONS = [
    "Will wearing an ankle brace help heal achilles tendonitis?",
    "What language and cultural differences impede the integration of foreign "
    "minorities in Germany?",
    "What security measures are in effect or are proposed to go into effect in "
    "airports?",
    "Find ways of measuring creativity.",
    "I'm hoping to grasp the intricacies of different healthcare systems, "
    "particularly what drives their accessibility, cost, and the fundamental "
    "debate around healthcare as a right versus a privilege. Can you explain "
    "the main factors affecting healthcare delivery, equity, and expenses, and "
    "suggest ways to improve health outcomes for everyone?",
    "I'm a college student who has seen articles about Geoffrey Hinton and his "
    "resignation from Google, with warnings of AI's impacts, but I don't fully "
    "understand the context of these warnings. Since I'm interested in the "
    "future of AI and how it might affect jobs or safety, I'd like a report "
    "that breaks down the story and why Hinton's warnings matter. I want "
    "something that helps me follow this issue more clearly without needing a "
    "tech background.",
]


def format_intents(intents: Intents) -> str:
    lines = [f"Q: {intents.question}"]
    for i, interp in enumerate(intents.interpretations, start=1):
        lines.append(f"  {i}. {interp}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="isj-agent CLI")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent.parent / "config.toml",
        help="Path to config.toml (default: isj/config.toml)",
    )
    parser.add_argument(
        "questions",
        nargs="*",
        help="Questions to analyze (default: a built-in sample set)",
    )
    args = parser.parse_args()

    config_path: Path = args.config
    if not config_path.exists():
        raise FileNotFoundError(
            f"config file not found: {config_path}\n"
            f"Copy config.example.toml to {config_path} and edit as needed."
        )

    with config_path.open("rb") as f:
        config = tomllib.load(f)

    llm_configs = config.get("llm", {})
    agent_configs = config.get("agents", {})

    # Build LLM clients keyed by profile name.
    clients = {name: build_client(llm_cfg) for name, llm_cfg in llm_configs.items()}

    # Instantiate agents from config.
    analyst_cfg = agent_configs["analyst"]
    analyst_llm = llm_configs[analyst_cfg["llm"]]
    AnalystClass = load_class(analyst_cfg["class"])
    analyst = AnalystClass(
        client=clients[analyst_cfg["llm"]],
        model=analyst_llm["model"],
    )

    orchestrator = Orchestrator(analyst=analyst)

    questions = args.questions or SAMPLE_QUESTIONS

    print(f"endpoint: {analyst_llm['base_url']}  model: {analyst_llm['model']}\n")
    for question in questions:
        intents = orchestrator.analyst.analyze(question)
        print(format_intents(intents))
        print()


if __name__ == "__main__":
    main()
