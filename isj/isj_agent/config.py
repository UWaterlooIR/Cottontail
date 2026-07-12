import importlib
import os
from pathlib import Path

import openai

from isj_agent.docno_map import DocnoMap
from isj_agent.engine.http import HttpSearchEngine

# Repo root: isj_agent -> isj -> <repo>. Used to resolve a relative burrow path.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def load_class(dotted_path: str) -> type:
    """Return the class named by a fully-qualified dotted path.

    Example: load_class("isj_agent.agents.analyst.Analyst")
    """
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def build_client(llm_config: dict) -> openai.OpenAI:
    """Construct an OpenAI-compatible client from a parsed [llm.*] config entry.

    If api_key_env is specified, reads the API key from that environment
    variable and raises RuntimeError if it is not set. If api_key_env is
    absent, defaults to "EMPTY" (works for unauthenticated local vLLM).
    """
    if "api_key_env" in llm_config:
        env_var = llm_config["api_key_env"]
        api_key = os.environ.get(env_var)
        if api_key is None:
            raise RuntimeError(
                f"environment variable '{env_var}' (api_key_env) is not set"
            )
    else:
        api_key = "EMPTY"
    return openai.OpenAI(base_url=llm_config["base_url"], api_key=api_key)


def build_search_engine(cfg: dict, burrow_override: str | None = None) -> HttpSearchEngine:
    """Construct an HttpSearchEngine from a parsed [cottontail_http_json_server] entry.

    The bearer token comes ONLY from the environment variable named by api_key_env
    (never a flag, never logged); RuntimeError if that var is named but unset. Omit
    api_key_env on a loopback server running without a token.
    """
    token = None
    if "api_key_env" in cfg:
        env_var = cfg["api_key_env"]
        token = os.environ.get(env_var)
        if token is None:
            raise RuntimeError(
                f"environment variable '{env_var}' (api_key_env) is not set"
            )
    kwargs = {}
    if "timeout_s" in cfg:
        kwargs["timeout"] = float(cfg["timeout_s"])
    # Docno on the wire (Option B): the engine owns the cp<->docno map and translates
    # at its boundary, so the agent sees only docnos. A docno-less burrow -> no map.
    docno_map = build_docno_map(cfg, burrow_override=burrow_override)
    return HttpSearchEngine(
        base_url=cfg["base_url"], token=token, docno_map=docno_map, **kwargs
    )


def build_docno_map(cfg: dict, burrow_override: str | None = None) -> DocnoMap | None:
    """Open the read-only cp<->docno map for the served burrow, or None.

    The map lives at <burrow>/docno-cp.sqlite. `burrow` comes from the
    [cottontail_http_json_server] config (or a CLI override); a relative path is
    resolved against the repo root. Returns None when no burrow is configured or the
    burrow has no map (a docno-less corpus) -- C2 then persists raw cps.
    """
    burrow = burrow_override or cfg.get("burrow")
    if not burrow:
        return None
    path = Path(burrow)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    sqlite_path = path / "docno-cp.sqlite"
    if not sqlite_path.exists():
        return None
    return DocnoMap(sqlite_path)


def build_lucindri_engine(cfg: dict):
    """Construct a LucindriSearchEngine from a config section (URL-only) and health-check it.

    Q6: the Lucindri server is operator-launched; poll /healthz on startup and FAIL FAST
    (an EngineError -> the CLI exits) if it is not reachable/ready.
    """
    from isj_agent.engine.lucindri import LucindriSearchEngine

    kwargs = {}
    if "timeout_s" in cfg:
        kwargs["timeout"] = float(cfg["timeout_s"])
    eng = LucindriSearchEngine(base_url=cfg["base_url"], **kwargs)
    eng.healthz()  # fail fast if the operator-launched server is down
    return eng


def build_engine(config: dict, burrow_override: str | None = None):
    """Construct THE configured SearchEngine (docno on the wire).

    Config-selected: an [engine] section names the class + its base_url [+ burrow for the
    Cottontail engine]. Backward-compatible: a config with only the legacy
    [cottontail_http_json_server] section still builds the Cottontail HTTP engine.
    """
    from isj_agent.engine.lucindri import LucindriSearchEngine
    from isj_agent.engine.multishard import MultiShardSearchEngine

    if "engine" in config:
        eng = config["engine"]
        cls = load_class(eng["class"])
        if cls is LucindriSearchEngine:
            return build_lucindri_engine(eng)
        if cls is MultiShardSearchEngine:
            return build_multishard_engine(eng)
        return build_search_engine(eng, burrow_override=burrow_override)
    # legacy: no [engine] -> the Cottontail HTTP engine from its section
    return build_search_engine(
        config["cottontail_http_json_server"], burrow_override=burrow_override
    )


def build_multishard_engine(cfg: dict):
    """Construct a MultiShardSearchEngine over N single-burrow Cottontail shards (TASK-34).

    `shards` is a non-empty list; each entry IS a single-Cottontail-engine config
    (base_url + burrow -- the burrow gives that shard its docno-cp.sqlite; without it the
    shard would emit stringified cps that collide across shards). Each is built via the
    existing build_search_engine. Health-checks every shard on build (fail fast, Q2).
    """
    from isj_agent.engine.multishard import MultiShardSearchEngine

    shards = cfg.get("shards")
    if not isinstance(shards, list) or not shards:
        raise SystemExit(
            "[engine] MultiShardSearchEngine requires a non-empty `shards` list"
        )
    for i, s in enumerate(shards):
        if not isinstance(s, dict) or "base_url" not in s or "burrow" not in s:
            raise SystemExit(
                f"[engine] shard {i} needs both base_url and burrow (burrow is required "
                "so the shard emits real docnos, not colliding cps)"
            )
    engines = [build_search_engine(s) for s in shards]
    eng = MultiShardSearchEngine(engines)
    eng.healthz()  # fail fast if any shard server is down
    return eng


def build_coach(config: dict):
    """Build the configured SearchCoach (TASK-40). Phase 1 supports MechanicalSearchCoach
    only. `[coach.mechanical]` carries top_results_to_show / min_show_grade (migrated out of
    `[loop]`, which is still read as a DEPRECATED fallback). A later phase adds the LLM
    SearchCoachAgent branch. See docs/design/search-coach.md."""
    from isj_agent.agents.search_coach import MechanicalSearchCoach

    coach_cfg = config.get("coach", {})
    mech_cfg = coach_cfg.get("mechanical", {})
    loop = config.get("loop", {})  # deprecated fallback for the migrated knobs
    top = mech_cfg.get("top_results_to_show", loop.get("top_results_to_show", 10))
    min_g = mech_cfg.get("min_show_grade", loop.get("min_show_grade", 3))

    cls_path = coach_cfg.get("class")
    if cls_path and load_class(cls_path) is not MechanicalSearchCoach:
        raise SystemExit(
            f"[coach] class {cls_path!r} is not available yet "
            "(phase 1 supports isj_agent.agents.search_coach.MechanicalSearchCoach)"
        )
    return MechanicalSearchCoach(top_results_to_show=top, min_show_grade=min_g)
