"""Fetch a document by docno or cp -- the human/external boundary path.

The C++ engine is cp-only (decision doc-8): it never reads the cp<->docno map.
This helper bridges a human/external caller across that boundary, both ways::

    --docno   docno --DocnoMap--> cp --(cottontail-jsonl-query --get <cp>)--> text
    --cp      cp --DocnoMap--> docno   (plus cp --get--> text)

The cp<->docno hop is resolved in Python (isj_agent.docno_map.DocnoMap, TASK-6.3);
the text is read by the C++ get-by-cp. Installed as the `cottontail-fetch` console
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


def _read_text_by_cp(burrow: Path, cp: int, query_bin: str | Path) -> str:
    """Read a document body by cp via `cottontail-jsonl-query --get <cp>`.

    Raises RuntimeError if the query binary fails or the cp is not found.
    """
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
        raise RuntimeError(f"cp {cp} not found in burrow")
    return out["text"]


def fetch_text(burrow: str | Path, docno: str, query_bin: str | Path) -> str:
    """Return the text of the document identified by `docno` (docno -> cp -> text).

    Resolves docno -> cp via the burrow's DocnoMap, then reads the body by cp.
    Raises KeyError if the docno is unknown, or RuntimeError if the query binary
    fails or the cp is not found.
    """
    burrow = Path(burrow)
    with DocnoMap(burrow / _SQLITE_NAME) as m:
        cp = m.cp(docno)
    if cp is None:
        raise KeyError(docno)
    return _read_text_by_cp(burrow, cp, query_bin)


def fetch_by_cp(
    burrow: str | Path, cp: int, query_bin: str | Path
) -> tuple[str | None, str]:
    """Return (docno, text) for a `cp` (cp -> docno + cp -> text).

    `docno` comes from the burrow's DocnoMap (None if the cp is not mapped); the
    body is read by cp. Raises RuntimeError if the cp is not found in the burrow.
    """
    burrow = Path(burrow)
    with DocnoMap(burrow / _SQLITE_NAME) as m:
        docno = m.docno(cp)
    text = _read_text_by_cp(burrow, cp, query_bin)
    return docno, text


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="cottontail-fetch",
        description="Fetch a document by docno or cp "
        "(docno -> cp -> text, or cp -> docno + text).",
    )
    parser.add_argument("--burrow", required=True, type=Path)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--docno", help="resolve docno -> cp -> text (prints text)")
    which.add_argument("--cp", type=int, help="resolve cp -> docno + text (prints both)")
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
        if args.docno is not None:
            print(fetch_text(args.burrow, args.docno, query_bin))
        else:  # --cp (mutually exclusive, exactly one is set; cp may be 0)
            docno, text = fetch_by_cp(args.burrow, args.cp, query_bin)
            print(f"docno: {docno if docno is not None else '(unmapped)'}")
            print(text)
    except KeyError:
        print(f"error: unknown docno '{args.docno}'", file=sys.stderr)
        raise SystemExit(1)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
