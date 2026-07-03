"""prompt_type x tool_type experiment (query fixed to TREC-4 questions).

Follows the 2x2x2 factorial (../tiered-factorial): that run showed the shipped `task20`
prompt + the bare-list tool is the runaway corner, while a STRUCTURED tool bounds
generation. This experiment fixes query=trec and crosses:

  prompt_type = {scout, task20}
  tool_type   = {V2_labeled, V3_angle_why, V4_facets_tiers}   (the 3 structured shapes)

to find which structured tool shape best disciplines/stabilizes each prompt. V1_minimal
(the bare list) is defined for reference/control but not a factor level here.
"""

from pathlib import Path

_HERE = Path(__file__).parent

PROMPTS = {
    "scout": (_HERE / "prompts" / "scout.md").read_text(encoding="utf-8"),
    "task20": (_HERE / "prompts" / "task20.md").read_text(encoding="utf-8"),
}

# TREC-4 topics (trec question form only), excluding the prompts' worked examples 201/202/250.
NEEDS = [
    {"id": "quebec_independence", "entity": "quebec",
     "trec": "What are the prospects of the Quebec separatists achieving independence "
             "from the rest of Canada?"},
    {"id": "self_hypnosis", "entity": None,
     "trec": "What are the different techniques used to create self-induced hypnosis?"},
    {"id": "blood_pressure", "entity": None,
     "trec": "What can be done to lower blood pressure for people diagnosed with high "
             "blood pressure? Include benefits and side effects."},
    {"id": "rainforest_weather", "entity": None,
     "trec": "How has the depletion or destruction of the rain forest effected the "
             "worlds weather?"},
]

# The tool-schema variants -- the `properties` shapes from the design owner. Each becomes a
# full function tool whose `parameters` are {type: object, properties: <props>, required: <req>}.
_VARIANTS = {
    "V1_minimal": {
        "required": ["tiers"],
        "props": {"tiers": {"type": "array", "items": {"type": "string"}}},
    },
    "V2_labeled": {
        "required": ["tiers"],
        "props": {"tiers": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "gcl": {"type": "string"}},
            "required": ["label", "gcl"]}}},
    },
    "V3_angle_why": {
        "required": ["tiers"],
        "props": {"tiers": {"type": "array", "items": {"type": "object", "properties": {
            "angle": {"type": "string", "description": "which aspect of the need this tier targets"},
            "gcl": {"type": "string"},
            "why": {"type": "string", "description": "why this tier (what it broadens or which angle it adds)"}},
            "required": ["angle", "gcl", "why"]}}},
    },
    "V4_facets_tiers": {
        "required": ["facets", "tiers"],
        "props": {
            "facets": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "gcl": {"type": "string"}},
                "required": ["name", "gcl"]}},
            "tiers": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "gcl": {"type": "string"}},
                "required": ["label", "gcl"]}}},
    },
}


def _schema(props, required):
    return {"type": "function", "function": {
        "name": "submit_tiered_query",
        "description": "Submit an ordered, precise->broad tiered GCL query (each tier a valid "
                       "GCL cover).",
        "parameters": {"type": "object", "properties": props, "required": required}}}


def _extract(args):
    """Ordered tier GCL strings, for every variant (tiers is either [str] or [{...,gcl}])."""
    ts = args["tiers"]
    if ts and isinstance(ts[0], dict):
        return [t["gcl"] for t in ts if isinstance(t, dict) and "gcl" in t]
    return [t for t in ts if isinstance(t, str)]


TOOLS = {name: {"schema": _schema(v["props"], v["required"]), "extract": _extract}
         for name, v in _VARIANTS.items()}

# Experiment factor levels.
PROMPT_LEVELS = ["scout", "task20"]
TOOL_LEVELS = ["V2_labeled", "V3_angle_why", "V4_facets_tiers"]


def cells():
    """prompt x tool grid (query is fixed to trec)."""
    for prompt in PROMPT_LEVELS:
        for tool in TOOL_LEVELS:
            yield {"prompt": prompt, "tool": tool}
