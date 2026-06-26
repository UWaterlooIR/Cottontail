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
