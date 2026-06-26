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


def build_search_engine(cfg: dict) -> HttpSearchEngine:
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
    return HttpSearchEngine(base_url=cfg["base_url"], token=token)


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
