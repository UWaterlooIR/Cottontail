import json
import subprocess
import sys
from pathlib import Path

import pytest

from isj_agent import fetch, index
from isj_agent.index import build_sqlite_map


def _make_burrow_with_map(tmp_path, rows):
    """A burrow dir with just a docno-cp.sqlite, built from a fixture flat file."""
    burrow = tmp_path / "x.burrow"
    burrow.mkdir()
    flat = burrow / "docno-cp.tsv"
    flat.write_text("".join(f"{d}\t{cp}\n" for d, cp in rows), encoding="utf-8")
    build_sqlite_map(flat, burrow / "docno-cp.sqlite")
    return burrow


def test_fetch_text_resolves_docno_then_gets_by_cp(tmp_path, monkeypatch):
    burrow = _make_burrow_with_map(tmp_path, [("doc-001", 0), ("doc-002", 9)])

    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        cp = cmd[cmd.index("--get") + 1]  # docno -> cp was resolved before the call
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"cp": int(cp), "found": True, "text": "body"}),
            stderr="",
        )

    monkeypatch.setattr(fetch.subprocess, "run", fake_run)
    text = fetch.fetch_text(burrow, "doc-002", "/bin/true")
    assert text == "body"
    assert "9" in captured["cmd"]  # doc-002 -> cp 9 was passed to --get


def test_fetch_text_unknown_docno_raises(tmp_path):
    burrow = _make_burrow_with_map(tmp_path, [("doc-001", 0)])
    with pytest.raises(KeyError):
        fetch.fetch_text(burrow, "no-such", "/bin/true")


def test_main_unknown_docno_exits_nonzero(tmp_path):
    burrow = _make_burrow_with_map(tmp_path, [("doc-001", 0)])
    with pytest.raises(SystemExit) as exc:
        fetch.main(
            ["--burrow", str(burrow), "--docno", "missing", "--query-bin", sys.executable]
        )
    assert exc.value.code == 1


def _fake_get(text="body", found=True):
    def fake_run(cmd, *args, **kwargs):
        cp = int(cmd[cmd.index("--get") + 1])
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"cp": cp, "found": found, "text": text}), stderr=""
        )
    return fake_run


def test_fetch_by_cp_returns_docno_and_text(tmp_path, monkeypatch):
    burrow = _make_burrow_with_map(tmp_path, [("doc-001", 0), ("doc-002", 9)])
    monkeypatch.setattr(fetch.subprocess, "run", _fake_get("body9"))
    docno, text = fetch.fetch_by_cp(burrow, 9, "/bin/true")
    assert docno == "doc-002" and text == "body9"


def test_fetch_by_cp_unmapped_cp_returns_none_docno(tmp_path, monkeypatch):
    burrow = _make_burrow_with_map(tmp_path, [("doc-001", 0)])  # cp 5 is not mapped
    monkeypatch.setattr(fetch.subprocess, "run", _fake_get("b"))
    docno, text = fetch.fetch_by_cp(burrow, 5, "/bin/true")
    assert docno is None and text == "b"


def test_main_cp_prints_docno_and_text(tmp_path, monkeypatch, capsys):
    burrow = _make_burrow_with_map(tmp_path, [("doc-002", 9)])
    monkeypatch.setattr(fetch.subprocess, "run", _fake_get("the body"))
    fetch.main(["--burrow", str(burrow), "--cp", "9", "--query-bin", sys.executable])
    out = capsys.readouterr().out
    assert "docno: doc-002" in out and "the body" in out


def test_main_cp_not_found_exits_nonzero(tmp_path, monkeypatch):
    burrow = _make_burrow_with_map(tmp_path, [("doc-001", 0)])
    monkeypatch.setattr(fetch.subprocess, "run", _fake_get(found=False))
    with pytest.raises(SystemExit) as exc:
        fetch.main(["--burrow", str(burrow), "--cp", "42", "--query-bin", sys.executable])
    assert exc.value.code == 1


def test_main_requires_exactly_one_of_docno_cp(tmp_path):
    burrow = _make_burrow_with_map(tmp_path, [("doc-001", 0)])
    with pytest.raises(SystemExit):  # neither --docno nor --cp -> argparse error
        fetch.main(["--burrow", str(burrow), "--query-bin", sys.executable])


def _real_bins():
    cfg = index._load_config(Path(__file__).resolve().parents[1] / "config.toml")
    try:
        index._resolve_index_bin(None, cfg)
        fetch._resolve_query_bin(None, cfg)
        return True
    except SystemExit:
        return False


@pytest.mark.skipif(not _real_bins(), reason="cottontail binaries not built")
def test_end_to_end_fetch_by_docno(tmp_path):
    indir = tmp_path / "in"
    indir.mkdir()
    (indir / "docs.jsonl").write_text(
        '{"docid":"shard_00037_72680","contents":"black bear attacks on hikers"}\n',
        encoding="utf-8",
    )
    burrow = tmp_path / "e2e.burrow"
    index.main(["--input", str(indir), "--burrow", str(burrow)])
    cfg = fetch._load_config(Path(__file__).resolve().parents[1] / "config.toml")
    query_bin = fetch._resolve_query_bin(None, cfg)
    text = fetch.fetch_text(burrow, "shard_00037_72680", query_bin)
    assert "black bear" in text
