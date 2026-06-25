"""cp-native index front door: build a searchable burrow from JSONL.

This is the single entry point for building an index (decision doc-6,
``docs/indexing.md`` section 6). It:

1. runs the C++ ``cottontail-jsonl-index`` (subprocess) -> a cp-native burrow
   (contents + one ``:item`` per document) plus a flat ``docid<TAB>cp`` dump at
   ``<burrow>/docid-cp.tsv``;
2. loads that dump into the SQLite map ``<burrow>/docno-cp.sqlite``
   (``docno_map(cp INTEGER PRIMARY KEY, docno TEXT UNIQUE)``), whose UNIQUE index
   is the docno-uniqueness check;
3. deletes the flat dump on success. On a duplicate docid it leaves the burrow and
   the flat dump in place, removes the partial map, and exits non-zero, naming the
   offender.

A docno-less corpus produces no flat dump and therefore no map (a cp-only burrow).

The C++ binary path comes from ``[index].binary`` in config.toml (repo-root-relative
or absolute), overridable with ``--index-bin``. Installed as the ``cottontail-index``
console script.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

# Repo root: isj_agent -> isj -> <repo>. Used to resolve a relative binary path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FLAT_NAME = "docid-cp.tsv"
_SQLITE_NAME = "docno-cp.sqlite"
# Table name shared with the reader (docno_map.py) and the C++ --get reader (A3).
_TABLE = "docno_map"
_BATCH = 10_000


class DuplicateDocnoError(Exception):
    """A docid appears more than once in the flat dump (UNIQUE violation)."""

    def __init__(self, docno: str):
        super().__init__(f"duplicate docid '{docno}'")
        self.docno = docno


def build_sqlite_map(flat_path: Path, sqlite_path: Path) -> int:
    """Build the cp<->docno SQLite map from a flat ``docid<TAB>cp`` dump.

    Returns the number of rows inserted. Raises :class:`DuplicateDocnoError`,
    naming the offending docno, if the dump contains a duplicate docid (the
    UNIQUE index is the uniqueness check).
    """
    conn = sqlite3.connect(sqlite_path)
    try:
        # The map is a rebuildable, write-once artifact; trade durability for
        # build speed.
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute(
            f"CREATE TABLE {_TABLE} (cp INTEGER PRIMARY KEY, docno TEXT UNIQUE)"
        )
        count = 0
        batch: list[tuple[int, str]] = []

        def flush() -> None:
            nonlocal count
            if not batch:
                return
            try:
                conn.executemany(
                    f"INSERT INTO {_TABLE} (cp, docno) VALUES (?, ?)", batch
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # A UNIQUE(docno) collision is somewhere in this batch (possibly
                # against an earlier committed batch). Replay row by row to name
                # the offender; the partial map is discarded by the caller.
                conn.rollback()
                for cp, docno in batch:
                    try:
                        conn.execute(
                            f"INSERT INTO {_TABLE} (cp, docno) VALUES (?, ?)",
                            (cp, docno),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise DuplicateDocnoError(docno) from exc
                    conn.commit()
                raise  # no single row reproduced it -- re-raise the original
            count += len(batch)
            batch.clear()

        with flat_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                docno, tab, cp = line.partition("\t")
                if not tab:
                    raise ValueError(f"malformed flat-dump line (no TAB): {line!r}")
                batch.append((int(cp), docno))
                if len(batch) >= _BATCH:
                    flush()
        flush()
        return count
    finally:
        conn.close()


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open("rb") as f:
        return tomllib.load(f)


def _resolve_index_bin(arg: str | None, config: dict) -> Path:
    if arg:
        candidate = Path(arg)
    else:
        binary = config.get("index", {}).get("binary")
        if not binary:
            raise SystemExit(
                "no index binary configured: set [index].binary in config.toml "
                "or pass --index-bin <path>"
            )
        candidate = Path(binary)
    if not candidate.is_absolute():
        candidate = _REPO_ROOT / candidate
    candidate = candidate.resolve()
    if not (candidate.is_file() and os.access(candidate, os.X_OK)):
        raise SystemExit(f"index binary not found or not executable: {candidate}")
    return candidate


def _index_command(index_bin: Path, args: argparse.Namespace) -> list[str]:
    cmd = [str(index_bin), "--input", args.input, "--burrow", str(args.burrow)]
    for flag, value in (
        ("--docid-field", args.docid_field),
        ("--contents-field", args.contents_field),
        ("--tokenizer", args.tokenizer),
        ("--stem", args.stem),
        ("--buffer", args.buffer),
        ("--limit", args.limit),
    ):
        if value is not None:
            cmd += [flag, str(value)]
    if args.strict:
        cmd.append("--strict")
    if args.overwrite:
        cmd.append("--overwrite")
    if args.verbose:
        cmd.append("--verbose")
    return cmd


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="cottontail-index",
        description="Build a cp-native burrow from JSONL and its cp<->docno map.",
    )
    parser.add_argument("--input", required=True, help="directory of *.jsonl[.gz]")
    parser.add_argument("--burrow", required=True, type=Path, help="output burrow path")
    parser.add_argument("--docid-field")
    parser.add_argument("--contents-field")
    parser.add_argument("--tokenizer", choices=["ascii", "utf8"])
    parser.add_argument("--stem", help="also build a stemmed stream (e.g. porter)")
    parser.add_argument("--buffer", help="builder buffer size (records)")
    parser.add_argument("--limit", help="index at most n rows")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent.parent / "config.toml",
        help="path to config.toml (default: isj/config.toml)",
    )
    parser.add_argument(
        "--index-bin", help="path to cottontail-jsonl-index (overrides [index].binary)"
    )
    args = parser.parse_args(argv)

    config = _load_config(args.config)
    index_bin = _resolve_index_bin(args.index_bin, config)

    proc = subprocess.run(_index_command(index_bin, args))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)

    flat = args.burrow / _FLAT_NAME
    if not flat.exists():
        print(f"cp-only burrow (no {_FLAT_NAME}); no SQLite map built.")
        return

    sqlite_path = args.burrow / _SQLITE_NAME
    if sqlite_path.exists():
        sqlite_path.unlink()
    try:
        n = build_sqlite_map(flat, sqlite_path)
    except DuplicateDocnoError as exc:
        if sqlite_path.exists():
            sqlite_path.unlink()
        print(
            f"error: {exc}; burrow and {_FLAT_NAME} left in place for inspection",
            file=sys.stderr,
        )
        raise SystemExit(1)
    flat.unlink()
    print(f"built {sqlite_path} ({n} docids); removed {_FLAT_NAME}")


if __name__ == "__main__":
    main()
