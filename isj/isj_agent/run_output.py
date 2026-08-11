"""Run-output writer: persist one question's Searcher run to a directory (C2).

One directory per run (one question)::

    <out_dir>/
      intents.json            the Intents (question + ordered interpretations)
      intent-00.json          interpretations[0]'s RankedList (only if it succeeded)
      intent-00.trace.jsonl   interpretations[0]'s event trace, one TraceEvent per line
      intent-01.json
      intent-01.trace.jsonl
      ...
      errors.log              PRESENT ONLY IF SOMETHING FAILED -- its absence means the
                              whole run succeeded.

Docno on the wire (Option B): the agent's id is already the docno for every engine
(the engine translated it at its boundary), so this writer does NO id resolution --
no DocnoMap, no lookup. It only renames the in-memory key `id` -> the portable
external key `docno` on disk (in the RankedList AND the trace events).

PURE filesystem: no network, no LLM, no Searcher logic, and no error CATCHING -- C3
runs the pipeline, catches the errors, and passes them in as RunError outcomes / a
run-level error. C2 only persists.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from isj_agent.protocol.intents import Intents
from isj_agent.protocol.results import LiveMarker, SearcherResult, TraceEvent


class RunError(BaseModel):
    """A failed interpretation: an exception escaped the Searcher (caught by C3)."""

    message: str


# The success outcome is exactly a SearcherResult (ranked_list + events).
Outcome = SearcherResult | RunError


def write_run(
    out_dir: str | Path,
    intents: Intents | None,
    outcomes: Sequence[Outcome],
    *,
    run_error: str | None = None,
    overwrite: bool = False,
) -> None:
    """Persist one question's run. `outcomes` is one entry PER interpretation, in order.

    `intents` is None only for a run-level failure before analysis produced any
    interpretations (e.g. the Analyst raised): then nothing but errors.log is written.
    """
    if intents is not None and len(outcomes) != len(intents.interpretations):
        raise ValueError(
            f"outcomes ({len(outcomes)}) != interpretations "
            f"({len(intents.interpretations)})"
        )
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        raise FileExistsError(
            f"output directory is not empty: {out_dir} (pass overwrite=True)"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear managed files from a prior run so stale intent-NN / errors.log never linger.
    for p in (
        list(out_dir.glob("intent-*.json"))
        + list(out_dir.glob("intent-*.trace.jsonl"))
        + [out_dir / "errors.log"]
    ):
        p.unlink(missing_ok=True)

    if intents is not None:
        (out_dir / "intents.json").write_text(
            intents.model_dump_json(indent=2), encoding="utf-8"
        )

    errors: list[str] = []
    for i, outcome in enumerate(outcomes):
        if isinstance(outcome, RunError):
            interp = intents.interpretations[i] if intents is not None else "?"
            errors.append(f"intent {i:02d} ({interp}): {outcome.message}")
            continue
        rl = _ranked_list_dict(outcome.ranked_list)
        (out_dir / f"intent-{i:02d}.json").write_text(
            json.dumps(rl, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        lines = [
            json.dumps(_event_dict(ev), ensure_ascii=False) for ev in outcome.events
        ]
        (out_dir / f"intent-{i:02d}.trace.jsonl").write_text(
            "".join(line + "\n" for line in lines), encoding="utf-8"
        )
        if outcome.error:
            # A PARTIAL result (a caught mid-loop failure): its json + trace are still
            # written above, but surface the failure in errors.log so the run is not
            # counted a clean success.
            interp = intents.interpretations[i] if intents is not None else "?"
            errors.append(f"intent {i:02d} ({interp}): {outcome.error}")

    if run_error:
        errors.append(f"run-level error: {run_error}")
    if errors:
        (out_dir / "errors.log").write_text("\n".join(errors) + "\n", encoding="utf-8")


def _rename_id(d: dict) -> None:
    """Rename the in-memory scalar `id` to the portable on-disk key `docno`."""
    d["docno"] = d.pop("id")


def _ranked_list_dict(ranked_list) -> dict:
    d = ranked_list.model_dump()
    for entry in d["entries"]:
        _rename_id(entry)
    return d


def _event_dict(event) -> dict:
    d = event.model_dump()
    t = d.get("type")
    # `exclude` lists (search_request / search) are already docnos -> left as-is.
    if t == "search":  # the response: every returned hit carries an id
        for hit in d.get("results", []):
            _rename_id(hit)
    elif t in ("judge", "revisit", "judge_failed"):  # a per-doc event: a single id
        _rename_id(d)
    # llm_call.request, propose/list_exhausted/bounce/stop/error carry no id field
    # and are left as-is. Only the structured id fields above are renamed.
    return d


# --------------------------------------------------------------------------- #
# Streaming (live) run output -- TASK-35
# --------------------------------------------------------------------------- #

def _fmt_ts(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _activity_lines(ev: TraceEvent | LiveMarker) -> list[str]:
    """Human-readable activity line(s) for one trace event or live marker.

    This is the tail-able rendering written to activity.log (and echoed to stdout in
    --verbose). Live markers render as 'awaiting ...' so a hung call is visible.
    """
    ts = _fmt_ts(getattr(ev, "ts", 0.0))
    if isinstance(ev, LiveMarker):
        if ev.kind == "await_searcher_turn":
            return [f"  {ts}  turn {getattr(ev, 'turn', '?')}: awaiting LLM ..."]
        if ev.kind == "await_judge":
            return [f"  {ts}  awaiting {getattr(ev, 'count', '?')} judge call(s) ..."]
        return [f"  {ts}  {ev.kind} ..."]

    d = ev.model_dump()
    t = d.get("type")
    out: list[str] = []
    if t == "llm_call":
        pt, ct = d.get("prompt_tokens"), d.get("completion_tokens")
        toks = f" tokens={pt}+{ct}" if pt is not None else ""
        purpose = d.get("purpose")
        head = f"turn {d['turn']}" if purpose == "searcher_turn" else purpose
        out.append(f"  {ts}  llm[{head}]{toks} ({d['duration_ms']:.0f} ms)")
        if purpose == "searcher_turn" and d.get("content") and d["content"].strip():
            out.append(f"        reasoning: {d['content'].strip()}")
        for c in d.get("calls", []):
            out.append(f"        -> {c['name']}({c['arguments']})")
    elif t == "error":
        pt = d.get("prompt_tokens")
        size = f" (prompt_tokens={pt})" if pt is not None else ""
        out.append(f"  {ts}  ERROR turn {d.get('turn')}: {d.get('error_type')}: {d.get('message')}{size}")
    elif t == "propose":
        out.append(f"  {ts}  -> query: {d['query']!r}")
    elif t == "search_request":
        out.append(f"  {ts}  -> request: {d['query']!r} (exclude={len(d.get('exclude', []))})")
    elif t == "search":
        out.append(
            f"  {ts}  search {d['query']!r}: "
            f"returned={len(d.get('results', []))} ({d['duration_ms']:.0f} ms)"
        )
    elif t == "judge":
        out.append(f"  {ts}  judge {d.get('docno', d.get('id'))}: grade={d['grade']}")
    elif t == "revisit":
        out.append(f"  {ts}  revisit {d.get('docno', d.get('id'))}: grade={d['grade']} (already judged)")
    elif t == "judge_failed":
        out.append(f"  {ts}  judge_failed {d.get('docno', d.get('id'))}: retries={d.get('retries')}")
    elif t == "list_exhausted":
        out.append(f"  {ts}  list exhausted at depth {d['depth']} (streak {d['streak']})")
    elif t == "bounce":
        out.append(f"  {ts}  bounce[{d['kind']}]: {d.get('message')}")
    elif t == "stop":
        out.append(f"  {ts}  stop: {d['reason']}")
    else:
        out.append(f"  {ts}  {t}")
    return out


class StreamingRunWriter:
    """Persist ONE question's run INCREMENTALLY, as it happens (TASK-35).

    The out dir is created if missing. As the run proceeds it writes:

      intents.json          once, at start()
      activity.log          human-readable stream of EVERY event + pre-call marker,
                            across all intents, appended and flushed per line -- the
                            file to `tail -f` to watch a run live (independent of --verbose)
      intent-NN.trace.jsonl structured trace, appended per event (PERSISTED events only;
                            byte-identical to write_run's one-shot output on success)
      intent-NN.json        the compiled RankedList, at finish_intent()
      errors.log            at finish(), ONLY if something failed (absence == clean run)

    A killed / timed-out run therefore leaves a partial, inspectable activity.log and
    trace rather than an empty directory. `echo=True` also mirrors activity to stdout
    (used for --verbose). Drive it from the Orchestrator callbacks:
        w = StreamingRunWriter(out, overwrite=..., echo=verbose)
        run_question(q, on_analyzed=w.start, observer=w.observe, on_intent=w.finish_intent)
        w.finish(run_error=run_error)
    """

    def __init__(self, out_dir: str | Path, *, overwrite: bool = False, echo: bool = False) -> None:
        out_dir = Path(out_dir)
        if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
            raise FileExistsError(
                f"output directory is not empty: {out_dir} (pass overwrite=True)"
            )
        out_dir.mkdir(parents=True, exist_ok=True)
        # Clear managed files from a prior run so nothing stale lingers.
        for p in (
            list(out_dir.glob("intent-*.json"))
            + list(out_dir.glob("intent-*.trace.jsonl"))
            + [out_dir / "errors.log", out_dir / "activity.log"]
        ):
            p.unlink(missing_ok=True)
        self.out_dir = out_dir
        self.echo = echo
        self.intents: Intents | None = None
        self._trace: dict[int, object] = {}   # intent index -> open trace file handle
        self._errors: list[str] = []
        self._cur: int | None = None           # current intent for activity headers
        self._activity = (out_dir / "activity.log").open("w", encoding="utf-8")

    def start(self, intents: Intents) -> None:
        """Write intents.json and the activity header (call once, after analysis)."""
        self.intents = intents
        (self.out_dir / "intents.json").write_text(
            intents.model_dump_json(indent=2), encoding="utf-8"
        )
        self._write_activity(f"question: {intents.question}")
        self._write_activity(f"interpretations: {len(intents.interpretations)}")

    def observe(self, i: int, ev: TraceEvent | LiveMarker) -> None:
        """Stream one event/marker for intent `i`: append to activity.log (+ echo), and
        (for a real TraceEvent) append to intent-NN.trace.jsonl. Markers are live-only."""
        if self._cur != i:
            self._cur = i
            interp = self.intents.interpretations[i] if self.intents is not None else "?"
            self._write_activity(f"\n[intent {i:02d}] {interp}")
        for line in _activity_lines(ev):
            self._write_activity(line)
        if isinstance(ev, TraceEvent):
            f = self._trace.get(i)
            if f is None:
                f = (self.out_dir / f"intent-{i:02d}.trace.jsonl").open("w", encoding="utf-8")
                self._trace[i] = f
            f.write(json.dumps(_event_dict(ev), ensure_ascii=False) + "\n")
            f.flush()

    def finish_intent(self, i: int, interp: str, outcome: Outcome) -> None:
        """Close intent `i`'s trace, write its RankedList json, and record any error."""
        f = self._trace.pop(i, None)
        if f is not None:
            f.close()
        if isinstance(outcome, RunError):
            self._errors.append(f"intent {i:02d} ({interp}): {outcome.message}")
            self._write_activity(f"    intent {i:02d} FAILED: {outcome.message}")
            return
        (self.out_dir / f"intent-{i:02d}.json").write_text(
            json.dumps(_ranked_list_dict(outcome.ranked_list), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        note = f" (PARTIAL: {outcome.error})" if outcome.error else ""
        self._write_activity(f"    -> {len(outcome.ranked_list.entries)} judged passages{note}")
        if outcome.error:
            self._errors.append(f"intent {i:02d} ({interp}): {outcome.error}")

    def finish(self, run_error: str | None = None) -> None:
        """Write errors.log if anything failed, close activity.log. Absence of
        errors.log means the whole run succeeded (same contract as write_run)."""
        for f in self._trace.values():
            f.close()
        self._trace.clear()
        if run_error:
            self._errors.append(f"run-level error: {run_error}")
        if self._errors:
            (self.out_dir / "errors.log").write_text(
                "\n".join(self._errors) + "\n", encoding="utf-8"
            )
        self._write_activity(
            "\nDONE (with errors -- see errors.log)" if self._errors else "\nDONE (clean)"
        )
        self._activity.close()

    def _write_activity(self, line: str) -> None:
        self._activity.write(line + "\n")
        self._activity.flush()
        if self.echo:
            print(line)
