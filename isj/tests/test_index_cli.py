import subprocess
import sys
from pathlib import Path

import pytest

from isj_agent import index
from isj_agent.docno_map import DocnoMap


def _fake_run_writing(burrow, contents):
    """A subprocess.run stub that emulates the C++ indexer dropping the flat dump."""

    def fake_run(cmd, *args, **kwargs):
        if contents is not None:
            (burrow / "docno-cp.tsv").write_text(contents, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    return fake_run


def _main_args(tmp_path, burrow):
    # --index-bin points at a real executable so resolution passes; the
    # subprocess itself is stubbed, so it is never actually run.
    return [
        "--input", str(tmp_path / "in"),
        "--burrow", str(burrow),
        "--index-bin", sys.executable,
    ]


def test_front_door_builds_map_and_deletes_flat(tmp_path, monkeypatch):
    burrow = tmp_path / "x.burrow"
    burrow.mkdir()
    monkeypatch.setattr(
        index.subprocess, "run",
        _fake_run_writing(burrow, "doc-001\t0\ndoc-002\t9\n"),
    )

    index.main(_main_args(tmp_path, burrow))

    sqlite_path = burrow / "docno-cp.sqlite"
    assert sqlite_path.exists()
    assert not (burrow / "docno-cp.tsv").exists()  # deleted on success
    with DocnoMap(sqlite_path) as m:
        assert m.docno(0) == "doc-001"
        assert m.cp("doc-002") == 9


def test_front_door_duplicate_leaves_flat_removes_partial(tmp_path, monkeypatch):
    burrow = tmp_path / "x.burrow"
    burrow.mkdir()
    monkeypatch.setattr(
        index.subprocess, "run",
        _fake_run_writing(burrow, "dup\t0\ndup\t9\n"),
    )

    with pytest.raises(SystemExit) as exc:
        index.main(_main_args(tmp_path, burrow))
    assert exc.value.code == 1
    assert (burrow / "docno-cp.tsv").exists()        # flat left in place
    assert not (burrow / "docno-cp.sqlite").exists()  # partial map removed


def test_front_door_no_flat_is_cp_only(tmp_path, monkeypatch):
    burrow = tmp_path / "x.burrow"
    burrow.mkdir()
    monkeypatch.setattr(
        index.subprocess, "run", _fake_run_writing(burrow, None)  # no flat written
    )

    index.main(_main_args(tmp_path, burrow))
    assert not (burrow / "docno-cp.sqlite").exists()  # cp-only burrow, no map


def test_front_door_propagates_index_failure(tmp_path, monkeypatch):
    burrow = tmp_path / "x.burrow"
    burrow.mkdir()
    monkeypatch.setattr(
        index.subprocess, "run",
        lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 3),
    )
    with pytest.raises(SystemExit) as exc:
        index.main(_main_args(tmp_path, burrow))
    assert exc.value.code == 3


def _real_index_bin():
    cfg_path = Path(__file__).resolve().parents[1] / "config.toml"
    try:
        return index._resolve_index_bin(None, index._load_config(cfg_path))
    except SystemExit:
        return None


@pytest.mark.skipif(
    _real_index_bin() is None,
    reason="cottontail-jsonl-index not built (set [index].binary / build with bazel)",
)
def test_end_to_end_against_real_binary(tmp_path):
    indir = tmp_path / "in"
    indir.mkdir()
    (indir / "docs.jsonl").write_text(
        '{"docid":"shard_00037_72680","contents":"black bear attacks on hikers"}\n'
        '{"docid":"doc-2","contents":"the cat in the hat"}\n',
        encoding="utf-8",
    )
    burrow = tmp_path / "e2e.burrow"
    index.main(["--input", str(indir), "--burrow", str(burrow)])

    sqlite_path = burrow / "docno-cp.sqlite"
    assert sqlite_path.exists()
    assert not (burrow / "docno-cp.tsv").exists()  # deleted on success
    with DocnoMap(sqlite_path) as m:
        cp = m.cp("shard_00037_72680")
        assert cp is not None
        assert m.docno(cp) == "shard_00037_72680"
