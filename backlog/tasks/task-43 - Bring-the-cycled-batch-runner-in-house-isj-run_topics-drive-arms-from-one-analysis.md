---
id: TASK-43
title: >-
  Bring the cycled batch runner in-house (isj run_topics) + drive arms from one
  analysis
status: In Progress
assignee:
  - '@claude'
created_date: '2026-07-13 18:10'
updated_date: '2026-07-13 20:07'
labels:
  - analyst
  - isj
  - infra
dependencies:
  - TASK-41
  - TASK-42
ordinal: 60000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Port trec-rag-2026/scripts/run_topics_cycled.py into the Cottontail isj package as a first-class, versioned, testable batch runner. Integrate it with the TASK-41 analysis artifact so one precomputed analysis drives every searcher arm (--analysis-file), and keep the memory-safe per-topic server cycling. Followup to TASK-41/42.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A canonical in-house runner (python -m isj_agent.run_topics) runs one or more searcher arms (--run NAME=CONFIG, ordered) over a topics TSV, cycling the 8 shard servers UP-before / DOWN-after each topic (memory-safe), serial within a topic, resumable per (arm,topic), with per-arm run_manifest.tsv, a servers.log, and guaranteed teardown on exit/interrupt.
- [x] #2 It drives each arm via the isj CLI with --analysis-file <analysis-dir>/<topic>.json (TASK-41), so all arms consume the IDENTICAL analysis (no per-arm analyst variation). It either takes a prebuilt --analysis <dir> or, given an analyst config, runs the analyze step first (python -m isj_agent.analyze) to produce it.
- [ ] #3 trec-rag-2026's scripts/run_topics_cycled.py is retired in favor of the in-house tool (its README points at python -m isj_agent.run_topics) -- flagged as a trec-rag-2026 follow-up, not required to land in Cottontail.
- [x] #4 Options preserved: --only ID, --limit N, --overwrite, --dry-run, --shard-ports, --healthz-timeout, --teardown-timeout, --settle. --dry-run prints the per-topic UP->arms->DOWN plan. isj suite green (a smoke/dry-run test where feasible).
- [x] #5 Server lifecycle delegates to launch-full-shard-servers.sh; --cottontail (default: in-repo root, overridable for out-of-repo use) resolves the launch script + isj CLI, and --launch-script overrides just the script path. It waits for all shard /healthz green before running, and tears down + waits ports-free + --settle before the next topic.
- [x] #6 The runner brings the shard servers DOWN before exiting on SIGTERM (a signal handler triggers the teardown), in addition to normal completion and SIGINT/Ctrl-C, so no kill path leaks the ~8x66 GB of servers.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
SOURCE: trec-rag-2026/scripts/run_topics_cycled.py (current cycled runner). It has: --run
NAME=CONFIG arms; read_topics/is_done; parse_ports; healthy()/listening()/wait_until(preds);
bring_up()/bring_down() delegating to launch-full-shard-servers.sh; a per-topic try/finally
teardown + a module-level _servers_up exit guard; a run_manifest.tsv per NAME; a servers.log.
DEPENDS ON TASK-41 (--analysis-file, python -m isj_agent.analyze, config.build_analyst) and
TASK-42 (ReportAnalyst as an analyst option). Work on branch claude/analyst-report-scout.

STEPS:
1. Create isj/isj_agent/run_topics.py, runnable as python -m isj_agent.run_topics, porting the
   cycled runner. Consolidate: cycling is the default; add --no-cycle for a servers-already-up mode
   (absorbs the simpler run_topics.py). Keep read_topics / is_done / parse_ports / healthy /
   listening / wait_until / bring_up / bring_down.
2. --cottontail STAYS (for out-of-repo use). It defaults to the in-repo root computed from
   Path(__file__) (isj_agent -> isj -> repo), but can point at a different Cottontail checkout. It
   resolves BOTH the launch script (<cottontail>/scripts/launch-full-shard-servers.sh) and the isj
   CLI. --launch-script remains an independent override of just the launch script path.
3. INVOCATION: run each (arm,topic) as
   'uv run --directory <cottontail>/isj python -m isj_agent.cli --analysis-file
   <analysis-dir>/<topic>.json --out results/<NAME>/<topic> --config <arm-cfg> [--overwrite]'
   (uv run --directory <cottontail>/isj works for the in-repo default AND an out-of-repo
   --cottontail). Subprocess per run for process isolation; do NOT import cli.main in-process.
4. ANALYSIS wiring (the point -- one analysis, N searchers): accept either --analysis <dir>
   (prebuilt) OR --analyst-config <cfg> + --topics, in which case run
   'uv run --directory <cottontail>/isj python -m isj_agent.analyze --topics <tsv> --config <cfg>
   --out <analysis-dir>' once up front, then feed each arm
   --analysis-file <analysis-dir>/<topic>.json for that topic.
5. Per-topic lifecycle: pending = arms not is_done(results/<NAME>/<topic>); if none, skip (no
   server cycle); else bring_up + healthz-wait; for arm in pending: subprocess isj CLI; finally
   bring_down + wait ports-free + --settle.
6. SIGNAL TEARDOWN (new): guarantee the servers come down before exit on SIGTERM as well as SIGINT.
   Install signal.signal(signal.SIGTERM, lambda *_: sys.exit(143)) near startup. SystemExit
   propagates through the outer try/.../finally, whose 'finally: if _servers_up: bring_down(...)'
   runs the teardown. Keep the existing 'except KeyboardInterrupt' (SIGINT) branch + the
   _servers_up finally guard. Net: normal exit, Ctrl-C (SIGINT), and kill (SIGTERM) all tear the
   servers down first.
7. RETIRE the trec-rag-2026 copy: note in that repo's scripts/README that the canonical runner is
   python -m isj_agent.run_topics; the actual removal is a trec-rag-2026 change (separate repo/PR),
   not required to land here.
8. TESTS (isj/tests/): a --dry-run test (parse arms + topics, print the UP->arms->DOWN plan, no side
   effects); unit-test parse_ports and is_done. Server bring-up needs live infra -> keep manual.
   Run 'uv run pytest' green.

GOTCHAS: keep --cottontail (default in-repo, overridable) so out-of-repo use still works; use
--analysis-file not --question so all arms share the one analysis; teardown guaranteed on normal
exit, SIGINT, AND SIGTERM; subprocess per run for process isolation; --dry-run must touch nothing.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented on branch claude/analyst-report-scout (isj/), depends on TASK-41/42:
- isj_agent/run_topics.py (python -m isj_agent.run_topics): ported from trec-rag-2026/scripts/run_topics_cycled.py (read with one-time permission) with the TASK-43 changes:
  * --cottontail now defaults to THIS in-repo checkout (Path(__file__).parents[2]); still overridable for out-of-repo use. Resolves both the launch script and the isj CLI.
  * drives each arm via --analysis-file <analysis-dir>/<topic>.json (never --question), so all arms consume the IDENTICAL analysis. Source: --analysis <prebuilt-dir> OR --analyst-config <cfg> (runs `isj analyze` once up front).
  * --no-cycle mode (servers already up) absorbs the simpler run_topics.py.
  * SIGTERM teardown: signal handler raises SystemExit(143) that propagates through the teardown finally (guarded so a non-main-thread test caller doesn't break). Teardown now guaranteed on normal exit, SIGINT, AND SIGTERM.
  * --dry-run now touches nothing (guarded the results mkdir; the trec-rag-2026 source created dirs on dry-run).
- tests/test_run_topics.py (7): parse_ports, is_done, read_topics, and --dry-run plan (cycled + --no-cycle + analyst-config) asserting it prints the plan and creates no files. Full isj suite green: 233 passed, 1 skipped.
- Docs: README layout + running-the-search-stack.md §4 gain a "Batch runs over many topics" subsection.

AC#3 (retire trec-rag-2026's scripts/run_topics_cycled.py, point its README here) is a SEPARATE-REPO follow-up, not landing in Cottontail -> left unchecked. Live server cycling / bring-up needs the 8-shard infra -> verified by hand; unit tests cover parsing + the dry-run plan.
<!-- SECTION:NOTES:END -->
