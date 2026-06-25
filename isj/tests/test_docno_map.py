import sqlite3

import pytest

from isj_agent.docno_map import DocnoMap
from isj_agent.index import DuplicateDocnoError, build_sqlite_map


def write_flat(path, rows):
    path.write_text("".join(f"{docno}\t{cp}\n" for docno, cp in rows), encoding="utf-8")


def test_build_and_round_trip(tmp_path):
    rows = [("doc-001", 0), ("doc-002", 9), ("doc-003", 16)]
    flat = tmp_path / "docno-cp.tsv"
    write_flat(flat, rows)
    sqlite_path = tmp_path / "docno-cp.sqlite"

    assert build_sqlite_map(flat, sqlite_path) == 3

    with DocnoMap(sqlite_path) as m:
        for docno, cp in rows:
            assert m.cp(docno) == cp
            assert m.docno(cp) == docno
        # Batch cp -> docno (out of order); unknown cps are simply absent.
        assert m.docnos([16, 0, 9, 999]) == {0: "doc-001", 9: "doc-002", 16: "doc-003"}
        assert m.docno(999) is None
        assert m.cp("no-such") is None


def test_duplicate_docno_named(tmp_path):
    flat = tmp_path / "docno-cp.tsv"
    write_flat(flat, [("dup", 0), ("other", 9), ("dup", 16)])
    sqlite_path = tmp_path / "docno-cp.sqlite"

    with pytest.raises(DuplicateDocnoError) as exc:
        build_sqlite_map(flat, sqlite_path)
    assert exc.value.docno == "dup"
    assert "dup" in str(exc.value)


def test_read_only(tmp_path):
    flat = tmp_path / "docno-cp.tsv"
    write_flat(flat, [("doc-001", 0)])
    sqlite_path = tmp_path / "docno-cp.sqlite"
    build_sqlite_map(flat, sqlite_path)

    with DocnoMap(sqlite_path) as m:
        with pytest.raises(sqlite3.OperationalError):
            m._conn.execute("INSERT INTO docno_map (cp, docno) VALUES (1, 'x')")


def test_missing_map(tmp_path):
    with pytest.raises(FileNotFoundError):
        DocnoMap(tmp_path / "nope.sqlite")
