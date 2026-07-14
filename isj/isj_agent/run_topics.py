"""Batch-run one or more ISJ searcher arms over a topics file, driven by ONE shared analysis.

    python -m isj_agent.run_topics \
        --run UWatMDS-gcl=configs/config-gcl-cover.toml \
        --run UWatMDS-mt=configs/config-multitext-tiered.toml \
        --topics topics.dev.tsv \
        --analyst-config configs/analyst.toml            # OR: --analysis <prebuilt-dir>

THE POINT (TASK-41 + TASK-43). Every arm consumes the IDENTICAL per-topic analysis via the isj
CLI's `--analysis-file` (never `--question`), so the Analyst's variation is factored OUT of
cross-searcher comparisons. Supply a prebuilt analysis directory with `--analysis <dir>`, or an
analyst config with `--analyst-config <cfg>` and the runner produces the analysis once up front
(`python -m isj_agent.analyze`) before any arm runs.

MEMORY SAFETY (the cycling). By default the runner cycles the 8 full-ClimbMix shard servers per
topic: bring UP all shards, run every arm on that topic (serially, in the order given), then
bring the servers DOWN before the next topic. Cottontail's posting cache is unbounded and never
evicts (src/simple_idx.h), so leaving 8 servers up across a long batch OOMs the box; a fresh
bring-up per topic caps the cache at one topic's worth of features. `--no-cycle` assumes the
servers are already up and skips all server management (the simple one-shot mode).

RESUMABLE: a (run, topic) whose dir already has intent-*.json and no errors.log is skipped; a
topic with nothing pending skips the whole server cycle. Per-(run,topic) status is appended to
results/<NAME>/run_manifest.tsv; server bring-up/-down output goes to results/servers.log.

TEARDOWN is guaranteed on NORMAL exit, Ctrl-C (SIGINT), AND `kill` (SIGTERM) -- a signal handler
turns SIGTERM into a SystemExit that propagates through the teardown `finally`, so no kill path
leaks the ~8x66 GB of shard servers.

Server lifecycle delegates to Cottontail's scripts/launch-full-shard-servers.sh (its `stop`
subcommand tears them down). `--cottontail` defaults to THIS in-repo checkout but can point at a
different Cottontail checkout (out-of-repo use); it resolves both the launch script and the isj
CLI. `--launch-script` overrides just the launch-script path.
"""
from __future__ import annotations

import argparse
import csv
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_servers_up = False  # module flag so the exit guard tears down if a topic cycle is interrupted


def read_topics(path: Path) -> list[tuple[str, str]]:
    """Read a 2-col (topic_id, query) TSV. Skips blank lines / short rows."""
    out: list[tuple[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) >= 2 and row[0].strip():
                out.append((row[0].strip(), row[1]))
    return out


def is_done(topic_dir: Path) -> bool:
    """A (run, topic) is done if it produced intent output and no errors.log."""
    return (any(topic_dir.glob("intent-*.json"))
            and not topic_dir.joinpath("errors.log").exists())


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ports(spec: str) -> list[int]:
    """'7000-7007' or a comma list -> [7000..7007]."""
    ports: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            ports.extend(range(int(a), int(b) + 1))
        elif part:
            ports.append(int(part))
    return ports


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_until(predicate, ports: list[int], timeout: float, poll: float = 2.0) -> bool:
    """Poll until predicate(port) holds for ALL ports, or timeout. Returns success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(predicate(p) for p in ports):
            return True
        time.sleep(poll)
    return all(predicate(p) for p in ports)


def bring_up(launch_script: Path, ports: list[int], timeout: float, log) -> bool:
    global _servers_up
    proc = subprocess.run([str(launch_script)], stdout=log, stderr=subprocess.STDOUT)
    _servers_up = True  # processes may be launching even if the script erred; teardown must run
    if proc.returncode != 0:
        return False
    return wait_until(healthy, ports, timeout)


def bring_down(launch_script: Path, ports: list[int], timeout: float, settle: float, log) -> None:
    global _servers_up
    subprocess.run([str(launch_script), "stop"], stdout=log, stderr=subprocess.STDOUT)
    wait_until(lambda p: not listening(p), ports, timeout)  # wait for ports free (memory reclaimed)
    if settle > 0:
        time.sleep(settle)
    _servers_up = False


def analyze_topics(isj_dir: Path, topics: Path, analyst_config: Path, out_dir: Path,
                   only: list[str], limit: int | None) -> None:
    """Run `python -m isj_agent.analyze` once, up front, to produce the shared analysis dir.

    Every arm then reads <out_dir>/<topic>.json, so all arms see the SAME analysis. Resumable
    (analyze skips topics whose <id>.json already exists). Aborts the batch if analyze fails."""
    cmd = ["uv", "run", "--directory", str(isj_dir), "python", "-m", "isj_agent.analyze",
           "--topics", str(topics), "--config", str(analyst_config), "--out", str(out_dir)]
    for i in only:
        cmd += ["--only", i]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    print(f">> analyzing topics -> {out_dir}  (one analysis drives every arm) …")
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        sys.exit(f"analyze step failed (rc={proc.returncode}); see output above")


def run_arm(name: str, cfg: Path, out: Path, tid: str, analysis_file: Path,
            isj_dir: Path, totals: dict) -> None:
    """Run ONE searcher arm on ONE topic via the isj CLI (subprocess, for process isolation).

    Drives the CLI with --analysis-file (never --question) so the arm consumes the shared
    analysis. Records ok/FAIL + rc + seconds to results/<NAME>/run_manifest.tsv."""
    tdir = (out / tid).resolve()
    if not analysis_file.is_file():  # the analysis for this topic is missing -> can't run the arm
        totals["failed"] += 1
        with (out / "run_manifest.tsv").open("a", encoding="utf-8") as m:
            m.write(f"{now()}\t{tid}\tFAIL\tno_analysis\t0\n")
        print(f"    [{name}] topic {tid}: FAIL (no analysis at {analysis_file})")
        return
    cmd = ["uv", "run", "--directory", str(isj_dir), "python", "-m", "isj_agent.cli",
           "--analysis-file", str(analysis_file), "--out", str(tdir), "--config", str(cfg)]
    if tdir.exists() and any(tdir.iterdir()):
        cmd.append("--overwrite")
    print(f"    [{name}] topic {tid}: running …")
    t0 = time.time()
    proc = subprocess.run(cmd)
    secs = time.time() - t0
    ok = proc.returncode == 0 and is_done(tdir)
    totals["ran"] += 1
    totals["failed"] += 0 if ok else 1
    with (out / "run_manifest.tsv").open("a", encoding="utf-8") as m:
        m.write(f"{now()}\t{tid}\t{'ok' if ok else 'FAIL'}\t{proc.returncode}\t{secs:.0f}\n")
    print(f"    [{name}] topic {tid}: {'ok' if ok else 'FAIL'} (rc={proc.returncode}, {secs:.0f}s)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="isj_agent.run_topics", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", default=[], metavar="NAME=CONFIG", required=True,
                    help="a searcher arm: results/<NAME>/ output dir + ISJ config toml (repeatable, ordered)")
    ap.add_argument("--topics", required=True, type=Path, help="2-col topics TSV")
    # analysis source (exactly one): a prebuilt analysis dir, OR an analyst config to generate it.
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--analysis", type=Path,
                     help="prebuilt analysis dir (from isj analyze); each arm gets --analysis-file <dir>/<topic>.json")
    src.add_argument("--analyst-config", type=Path,
                     help="run isj analyze with this config up front to produce the shared analysis, then drive every arm from it")
    ap.add_argument("--analysis-out", type=Path, default=None,
                    help="where --analyst-config writes the analysis (default <results>/analysis)")
    ap.add_argument("--results", type=Path, default=Path("results"), help="parent of the run dirs")
    ap.add_argument("--cottontail", type=Path, default=Path(__file__).resolve().parents[2],
                    help="Cottontail repo root (default: this in-repo checkout; override for out-of-repo use)")
    ap.add_argument("--launch-script", type=Path, default=None,
                    help="shard launch script (default <cottontail>/scripts/launch-full-shard-servers.sh)")
    ap.add_argument("--shard-ports", default="7000-7007", help="shard server ports (default 7000-7007)")
    ap.add_argument("--healthz-timeout", type=float, default=180.0, help="secs to wait for all shards healthy")
    ap.add_argument("--teardown-timeout", type=float, default=120.0, help="secs to wait for ports to free")
    ap.add_argument("--settle", type=float, default=8.0, help="extra secs after ports free before next topic")
    ap.add_argument("--no-cycle", action="store_true",
                    help="assume the shard servers are already up; do not cycle them per topic")
    ap.add_argument("--only", action="append", default=[], help="run only this topic id (repeatable)")
    ap.add_argument("--limit", type=int, help="run only the first N topics")
    ap.add_argument("--overwrite", action="store_true", help="re-run even completed (run, topic)s")
    ap.add_argument("--dry-run", action="store_true", help="print the per-topic plan; touch nothing")
    args = ap.parse_args(argv)

    # Tear the shard servers down on SIGTERM too (not just SIGINT / normal exit): the handler
    # raises SystemExit(143), which propagates through the teardown `finally` below. Guarded so a
    # non-main-thread caller (e.g. a test runner) doesn't blow up -- teardown still covers normal
    # exit + SIGINT there. No-op in --no-cycle: we never bring the servers up.
    try:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    except ValueError:
        pass

    isj_dir = (args.cottontail / "isj").resolve()
    if not isj_dir.is_dir():
        sys.exit(f"Cottontail isj dir not found: {isj_dir} (pass --cottontail)")
    launch_script = (args.launch_script
                     or args.cottontail / "scripts" / "launch-full-shard-servers.sh").resolve()
    if not args.no_cycle and not launch_script.is_file():
        sys.exit(f"launch script not found: {launch_script} (pass --launch-script, or --no-cycle)")
    ports = parse_ports(args.shard_ports)

    # runs: ordered list of (name, config_path, out_dir)
    runs = []
    for spec in args.run:
        if "=" not in spec:
            sys.exit(f"--run must be NAME=CONFIG, got: {spec!r}")
        name, cfg = spec.split("=", 1)
        cfg_path = Path(cfg).resolve()
        if not cfg_path.is_file():
            sys.exit(f"config not found for run {name!r}: {cfg_path}")
        out_dir = args.results / name
        if not args.dry_run:  # dry-run must touch nothing
            out_dir.mkdir(parents=True, exist_ok=True)
        runs.append((name, cfg_path, out_dir))

    topics = read_topics(args.topics)
    if args.only:
        topics = [(i, q) for i, q in topics if i in set(args.only)]
    if args.limit is not None:
        topics = topics[: args.limit]
    if not topics:
        sys.exit("no topics selected")

    # the shared analysis dir (one analysis drives every arm)
    if args.analysis is not None:
        analysis_dir = args.analysis.resolve()
        if not args.dry_run and not analysis_dir.is_dir():
            sys.exit(f"--analysis dir not found: {analysis_dir} (run isj analyze first, or pass --analyst-config)")
    else:
        analysis_dir = (args.analysis_out or (args.results / "analysis")).resolve()

    mode = "servers already up (--no-cycle)" if args.no_cycle else f"shards {ports[0]}-{ports[-1]} cycled per topic"
    print(f"{len(topics)} topic(s) x {len(runs)} run(s): "
          + ", ".join(n for n, _, _ in runs) + f"  ({mode})")

    if args.dry_run:
        if args.analyst_config is not None:
            print(f"  [analyze] isj_agent.analyze --topics {args.topics} --config {args.analyst_config} --out {analysis_dir}")
        for n, (tid, _) in enumerate(topics, 1):
            pending = [name for name, _, out in runs if args.overwrite or not is_done(out / tid)]
            if not pending:
                print(f"[{n}/{len(topics)}] topic {tid}: SKIP (all runs done)")
            elif args.no_cycle:
                print(f"[{n}/{len(topics)}] topic {tid}: " + ", ".join(pending))
            else:
                print(f"[{n}/{len(topics)}] topic {tid}: UP servers -> " + ", ".join(pending) + " -> DOWN")
        return 0

    # generate the shared analysis once, up front, if the caller passed an analyst config
    if args.analyst_config is not None:
        analyze_topics(isj_dir, args.topics, args.analyst_config, analysis_dir, args.only, args.limit)

    servers_log_path = args.results / "servers.log"
    totals = {"ran": 0, "skipped": 0, "failed": 0, "topics_cycled": 0}
    try:
        for n, (tid, question) in enumerate(topics, 1):
            pending = [(name, cfg, out) for name, cfg, out in runs
                       if args.overwrite or not is_done((out / tid))]
            if not pending:
                print(f"[{n}/{len(topics)}] topic {tid}: SKIP (all runs done)")
                totals["skipped"] += len(runs)
                continue
            analysis_file = analysis_dir / f"{tid}.json"

            if args.no_cycle:  # servers already up: just run the arms, no server management
                for name, cfg, out in pending:
                    run_arm(name, cfg, out, tid, analysis_file, isj_dir, totals)
                continue

            # cycled: UP -> arms -> DOWN, guaranteed teardown via the finally
            print(f"[{n}/{len(topics)}] topic {tid}: bringing up {len(ports)} shard servers …")
            with servers_log_path.open("a", encoding="utf-8") as slog:
                slog.write(f"\n===== topic {tid} @ {now()} =====\n")
                up = bring_up(launch_script, ports, args.healthz_timeout, slog)
            totals["topics_cycled"] += 1
            if not up:
                print(f"[{n}/{len(topics)}] topic {tid}: SERVERS DID NOT COME HEALTHY -> skipping "
                      f"(see {servers_log_path}); tearing down")
                for name, cfg, out in pending:
                    with (out / "run_manifest.tsv").open("a", encoding="utf-8") as m:
                        m.write(f"{now()}\t{tid}\tFAIL\tserver_up\t0\n")
                    totals["failed"] += 1
                with servers_log_path.open("a", encoding="utf-8") as slog:
                    bring_down(launch_script, ports, args.teardown_timeout, args.settle, slog)
                continue

            try:
                for name, cfg, out in pending:  # e.g. gcl on tid, then mt on tid — serial
                    run_arm(name, cfg, out, tid, analysis_file, isj_dir, totals)
            finally:
                print(f"[{n}/{len(topics)}] topic {tid}: bringing down shard servers …")
                with servers_log_path.open("a", encoding="utf-8") as slog:
                    bring_down(launch_script, ports, args.teardown_timeout, args.settle, slog)
    except KeyboardInterrupt:
        print("\ninterrupted — ensuring shard servers are down …", file=sys.stderr)
    finally:
        if _servers_up:
            with servers_log_path.open("a", encoding="utf-8") as slog:
                bring_down(launch_script, ports, args.teardown_timeout, args.settle, slog)

    print(f"\ndone: ran={totals['ran']} skipped={totals['skipped']} failed={totals['failed']} "
          f"topics_cycled={totals['topics_cycled']}")
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
