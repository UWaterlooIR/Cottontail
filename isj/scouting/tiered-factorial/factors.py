"""Factors for the tiered-query 2x2x2 investigation.

Why: the SHIPPED TieredSearcher over-enumerated (30-50 alternatives per facet) on a
live run, while the earlier SCOUTING produced disciplined tiers (~13 max). BUT the
shipped run differed from scouting on THREE axes at once, so we can't attribute the
regression. This module defines the three factors so run.py can cross them.

  FACTOR A -- prompt:  scout  (validated "expert search-query author", ~3.9k chars)
                       task20 (shipped  "search analyst", ~8.9k chars)
  FACTOR B -- query:   trec    (a full TREC-4-style question)
                       keyword (a short web-search keyword string)
  FACTOR C -- tool:    list    (bare {tiers:[gcl]}          -- the shipped schema)
                       faceted ({facets, tiers:[{label,gcl}]} -- the scouting schema)

Known corners: (scout, trec, faceted) is the scouting baseline that worked;
(task20, keyword, list) is the shipped combination that bloated.
"""

from pathlib import Path

_HERE = Path(__file__).parent

PROMPTS = {
    "scout": (_HERE / "prompts" / "scout.md").read_text(encoding="utf-8"),
    "task20": (_HERE / "prompts" / "task20.md").read_text(encoding="utf-8"),
}

# Matched need-pairs: ONE underlying need, expressed as a full TREC-style question
# (`trec`, the verbatim TREC-4 topic description) and as a keyword string (`keyword`),
# so FACTOR B is isolated. `entity` marks a named entity for the entity-drop observation
# (None = no named entity).
#
# IMPORTANT: these are TREC-4 topics NOT used as worked examples in either prompt --
# the prompts teach on topics 201 (au pair), 202 (nuclear treaties), and 250 (firearms/
# crime), so testing on those would measure PARROTING, not authoring. Topics chosen from
# docs/trec4/topics.201-250, excluding {201, 202, 250}.
NEEDS = [
    {
        "id": "quebec_independence", "entity": "quebec",  # TREC-4 topic 207
        "trec": "What are the prospects of the Quebec separatists achieving "
                "independence from the rest of Canada?",
        "keyword": "quebec separatist independence canada",
    },
    {
        "id": "self_hypnosis", "entity": None,  # TREC-4 topic 214
        "trec": "What are the different techniques used to create self-induced hypnosis?",
        "keyword": "self-induced hypnosis techniques",
    },
    {
        "id": "blood_pressure", "entity": None,  # TREC-4 topic 224
        "trec": "What can be done to lower blood pressure for people diagnosed with "
                "high blood pressure? Include benefits and side effects.",
        "keyword": "lower high blood pressure treatment side effects",
    },
    {
        "id": "rainforest_weather", "entity": None,  # TREC-4 topic 249
        "trec": "How has the depletion or destruction of the rain forest effected the "
                "worlds weather?",
        "keyword": "rainforest destruction effect world weather",
    },
]


# FACTOR C: the two tool schemas + how to pull the ordered GCL tier strings out of a call.

def _list_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "tiered_query_search",
            "description": "Submit an ORDERED list of GCL cover tiers, most precise "
                           "first and broadest last.",
            "parameters": {
                "type": "object",
                "properties": {"tiers": {"type": "array", "items": {"type": "string"}}},
                "required": ["tiers"],
            },
        },
    }


def _faceted_schema() -> dict:
    # The exact scouting schema (recovered from the session transcript): a faceted
    # decomposition plus labeled tiers.
    return {
        "type": "function",
        "function": {
            "name": "submit_tiered_query",
            "description": "Submit the faceted decomposition and the ordered "
                           "precise->broad tiered GCL query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "facets": {
                        "type": "array",
                        "items": {"type": "object", "properties": {
                            "name": {"type": "string"},
                            "kind": {"type": "string", "enum": ["entity-bound", "transferable"]},
                            "gcl": {"type": "string"},
                        }, "required": ["name", "kind", "gcl"]},
                    },
                    "tiers": {
                        "type": "array",
                        "items": {"type": "object", "properties": {
                            "label": {"type": "string"},
                            "gcl": {"type": "string"},
                        }, "required": ["label", "gcl"]},
                    },
                },
                "required": ["facets", "tiers"],
            },
        },
    }


def _extract_list(args: dict) -> list:
    return [t for t in args["tiers"] if isinstance(t, str)]


def _extract_faceted(args: dict) -> list:
    return [t["gcl"] for t in args["tiers"] if isinstance(t, dict) and "gcl" in t]


TOOLS = {
    "list": {"schema": _list_schema(), "name": "tiered_query_search", "extract": _extract_list},
    "faceted": {"schema": _faceted_schema(), "name": "submit_tiered_query", "extract": _extract_faceted},
}


def cells():
    """The full 2x2x2 grid (8 cells)."""
    for prompt in ("scout", "task20"):
        for query in ("trec", "keyword"):
            for tool in ("list", "faceted"):
                yield {"prompt": prompt, "query": query, "tool": tool}
