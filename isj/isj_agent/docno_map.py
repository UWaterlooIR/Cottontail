"""Read-only reader over a burrow's cp<->docno SQLite map.

The map lives at ``<burrow>/docno-cp.sqlite`` with one table::

    docno_map(cp INTEGER PRIMARY KEY, docno TEXT UNIQUE)

It is built once at index time (see :mod:`isj_agent.index`) from the flat
``docid-cp.tsv`` dump the C++ indexer writes, and is read **only at a boundary**,
off the hot query path (decision doc-6, ``docs/indexing.md`` section 6):

* ``cp -> docno`` (single + batch) — the run-output rewrite in TASK-5 C2, which
  turns the working ``cp`` ids into portable ``docno`` ids at persistence;
* ``docno -> cp`` — a human/external fetch, which then reads the document by ``cp``.

The map is opened ``immutable=1``: read-only and lock-free, correct for a static
burrow whose files never change after the build. The multi-threaded C++ query
path never opens it; the only C++ reader is the boundary ``--get <docno>`` (A3).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path

# The table name C++ (A3) and Python both key on. Keep in sync with index.py.
_TABLE = "docno_map"

# SQLite's default SQLITE_MAX_VARIABLE_NUMBER is 999 on older builds; stay well
# under it when batching the cp -> docno lookup.
_CHUNK = 900


class DocnoMap:
    """Read-only cp<->docno lookups over ``<burrow>/docno-cp.sqlite``."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"docno map not found: {self.path}")
        # immutable=1 => read-only, no locking, no -wal; the burrow is static.
        # check_same_thread=False: the connection may be used from a worker thread
        # (MultiShardSearchEngine fans queries out across threads); the lock serializes
        # access so the single read-only connection is used one thread at a time.
        uri = f"file:{self.path}?immutable=1"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._lock = threading.Lock()

    def docno(self, cp: int) -> str | None:
        """The docno for one cp, or None if cp is not a document start."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT docno FROM {_TABLE} WHERE cp = ?", (cp,)
            ).fetchone()
        return row[0] if row is not None else None

    def docnos(self, cps: Iterable[int]) -> dict[int, str]:
        """Batch cp -> docno. Returns {cp: docno} for the cps that are known
        (unknown cps are simply absent from the result)."""
        wanted = list(cps)
        out: dict[int, str] = {}
        for i in range(0, len(wanted), _CHUNK):
            chunk = wanted[i : i + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            with self._lock:
                rows = self._conn.execute(
                    f"SELECT cp, docno FROM {_TABLE} WHERE cp IN ({placeholders})", chunk
                ).fetchall()
            for cp, docno in rows:
                out[cp] = docno
        return out

    def cp(self, docno: str) -> int | None:
        """The cp for one docno, or None if the docno is unknown."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT cp FROM {_TABLE} WHERE docno = ?", (docno,)
            ).fetchone()
        return row[0] if row is not None else None

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DocnoMap":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
