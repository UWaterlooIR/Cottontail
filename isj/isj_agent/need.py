"""compose_need: the per-intent 'need' the Controller feeds to the Searcher/Judger/Coach (TASK-44).

The agents were built for a bare interpretation string; for TREC-RAG report writing they need the
big picture. This helper assembles ONE self-labeled string with three sections -- USER REQUEST (the
original request), ANALYSIS (all components the request was broken into, with the current target
marked), and SEARCH TARGET (the one component to collect for now). The Controller substitutes this
string wherever the bare intent used to flow (searcher seed, judge, CoachContext), so the agent
signatures do not change. The three section LABELS are a stable contract the agent prompts rely on.
"""
from __future__ import annotations


def compose_need(question: str, interpretations: list[str], target: str) -> str:
    """Assemble the labeled need string (USER REQUEST / ANALYSIS / SEARCH TARGET) for one target.

    `target` is the current interpretation; it is marked in the ANALYSIS list (first match only)
    and stated on its own under SEARCH TARGET. `interpretations` is the full analysis list.
    """
    lines = [
        "The user has asked for a report (up to ~1000 words) answering the request below. We are",
        "collecting source documents a generative AI will use to write that report; we are not",
        "writing the report ourselves.",
        "",
        "USER REQUEST (the big picture):",
        question,
        "",
        "ANALYSIS (the request was broken into these information components):",
    ]
    marked = False
    for i, interp in enumerate(interpretations, 1):
        if interp == target and not marked:
            lines.append(f"  {i}. {interp}      <-- SEARCH TARGET")
            marked = True
        else:
            lines.append(f"  {i}. {interp}")
    lines += [
        "",
        "SEARCH TARGET (the one component to find information for now):",
        target,
    ]
    return "\n".join(lines)
