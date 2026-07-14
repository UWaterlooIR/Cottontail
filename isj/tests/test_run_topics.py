"""run_topics batch-runner tests (TASK-43): pure helpers + the --dry-run plan.

Server bring-up/cycling needs live infra, so it is exercised by hand; here we pin the parsing/
resume helpers and that --dry-run prints the per-topic plan while touching nothing on disk.
"""
import importlib.util
from pathlib import Path

# run_topics is an operational script under isj/scripts/, not a package module -- load it by path.
_RT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_topics.py"
_spec = importlib.util.spec_from_file_location("run_topics", _RT_PATH)
run_topics = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_topics)


def test_parse_ports_range():
    assert run_topics.parse_ports("7000-7007") == [7000, 7001, 7002, 7003, 7004, 7005, 7006, 7007]


def test_parse_ports_comma_and_mixed():
    assert run_topics.parse_ports("7000,7001,7002") == [7000, 7001, 7002]
    assert run_topics.parse_ports("7000-7001, 7005") == [7000, 7001, 7005]
    assert run_topics.parse_ports("8080") == [8080]


def test_is_done(tmp_path):
    d = tmp_path / "t1"
    d.mkdir()
    assert not run_topics.is_done(d)                     # empty -> not done
    (d / "intent-00.json").write_text("{}", encoding="utf-8")
    assert run_topics.is_done(d)                         # has intent output, no errors -> done
    (d / "errors.log").write_text("boom", encoding="utf-8")
    assert not run_topics.is_done(d)                     # errors.log present -> not done


def test_read_topics_skips_blanks(tmp_path):
    tsv = tmp_path / "topics.tsv"
    tsv.write_text("t1\tfirst\n\n  \nt2\tsecond\n", encoding="utf-8")
    assert run_topics.read_topics(tsv) == [("t1", "first"), ("t2", "second")]


def _fixture(tmp_path) -> tuple[Path, Path, Path, Path]:
    """A topics TSV, two arm configs, and a prebuilt analysis dir (contents irrelevant to dry-run)."""
    tsv = tmp_path / "topics.tsv"
    tsv.write_text("t1\tq one\nt2\tq two\n", encoding="utf-8")
    cfg_a = tmp_path / "a.toml"; cfg_a.write_text("", encoding="utf-8")
    cfg_b = tmp_path / "b.toml"; cfg_b.write_text("", encoding="utf-8")
    analysis = tmp_path / "analysis"; analysis.mkdir()
    return tsv, cfg_a, cfg_b, analysis


def test_dry_run_no_cycle_prints_plan_and_touches_nothing(tmp_path, capsys):
    tsv, cfg_a, cfg_b, analysis = _fixture(tmp_path)
    results = tmp_path / "results"
    rc = run_topics.main([
        "--run", f"A={cfg_a}", "--run", f"B={cfg_b}",
        "--topics", str(tsv), "--analysis", str(analysis),
        "--results", str(results), "--no-cycle", "--dry-run",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "servers already up (--no-cycle)" in out
    assert "topic t1: A, B" in out and "topic t2: A, B" in out
    assert "UP servers" not in out
    assert not results.exists()                          # --dry-run must touch nothing


def test_dry_run_cycled_prints_up_arms_down(tmp_path, capsys):
    tsv, cfg_a, cfg_b, analysis = _fixture(tmp_path)
    results = tmp_path / "results"
    rc = run_topics.main([
        "--run", f"A={cfg_a}", "--run", f"B={cfg_b}",
        "--topics", str(tsv), "--analysis", str(analysis),
        "--results", str(results), "--dry-run",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cycled per topic" in out
    assert "topic t1: UP servers -> A, B -> DOWN" in out
    assert not results.exists()                          # --dry-run must touch nothing


def test_dry_run_with_analyst_config_shows_analyze_step(tmp_path, capsys):
    tsv, cfg_a, _cfg_b, _analysis = _fixture(tmp_path)
    results = tmp_path / "results"
    rc = run_topics.main([
        "--run", f"A={cfg_a}", "--topics", str(tsv),
        "--analyst-config", str(cfg_a), "--results", str(results),
        "--no-cycle", "--dry-run",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[analyze] isj_agent.analyze" in out          # the up-front analyze step is planned
    assert not results.exists()
