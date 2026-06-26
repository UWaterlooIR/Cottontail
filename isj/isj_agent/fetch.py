"""Fetch a document's text by docno -- the human/external boundary path.

The C++ engine is cp-only (decision doc-8): it never reads the cp<->docno map.
This helper bridges a human/external caller that holds only a docno::

    docno --DocnoMap--> cp --(cottontail-jsonl-query --get <cp>)--> text

`docno -> cp` is resolved in Python (isj_agent.docno_map.DocnoMap, TASK-6.3); the
text is read by the C++ get-by-cp. Installed as the `cottontail-fetch` console
script. The query-binary path comes from config.toml `[query].binary`
(repo-root-relative) with a `--query-bin` override.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from isj_agent.docno_map import DocnoMap

# Repo root: isj_agent -> isj -> <repo>. Used to resolve a relative binary path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SQLITE_NAME = "docno-cp.sqlite"


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open("rb") as f:
        return tomllib.load(f)


def _resolve_query_bin(arg: str | None, config: dict) -> Path:
    if arg:
        candidate = Path(arg)
    else:
        binary = config.get("query", {}).get("binary")
        if not binary:
            raise SystemExit(
                "no query binary configured: set [query].binary in config.toml "
                "or pass --query-bin <path>"
            )
        candidate = Path(binary)
    if not candidate.is_absolute():
        candidate = _REPO_ROOT / candidate
    candidate = candidate.resolve()
    if not (candidate.is_file() and os.access(candidate, os.X_OK)):
        raise SystemExit(f"query binary not found or not executable: {candidate}")
    return candidate


def fetch_text(burrow: str | Path, docno: str, query_bin: str | Path) -> str:
    """Return the text of the document identified by `docno`.

    Resolves docno -> cp via the burrow's DocnoMap, then reads the body by cp with
    `cottontail-jsonl-query --get <cp>`. Raises KeyError if the docno is unknown,
    or RuntimeError if the query binary fails or the cp is not found.
    """
    burrow = Path(burrow)
    with DocnoMap(burrow / _SQLITE_NAME) as m:
        cp = m.cp(docno)
    if cp is None:
        raise KeyError(docno)
    proc = subprocess.run(
        [str(query_bin), "--burrow", str(burrow), "--get", str(cp), "--format", "jsonl"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"cottontail-jsonl-query failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    out = json.loads(proc.stdout)
    if not out.get("found"):
        raise RuntimeError(f"cp {cp} (docno {docno!r}) not found in burrow")
    return out["text"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="cottontail-fetch",
        description="Fetch a document's text by docno (docno -> cp -> text).",
    )
    parser.add_argument("--burrow", required=True, type=Path)
    parser.add_argument("--docno", required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent.parent / "config.toml",
        help="path to config.toml (default: isj/config.toml)",
    )
    parser.add_argument(
        "--query-bin",
        help="path to cottontail-jsonl-query (overrides [query].binary)",
    )
    args = parser.parse_args(argv)

    config = _load_config(args.config)
    query_bin = _resolve_query_bin(args.query_bin, config)
    try:
        text = fetch_text(args.burrow, args.docno, query_bin)
    except KeyError:
        print(f"error: unknown docno '{args.docno}'", file=sys.stderr)
        raise SystemExit(1)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(text)


if __name__ == "__main__":
    main()
