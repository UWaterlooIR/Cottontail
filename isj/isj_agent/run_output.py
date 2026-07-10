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
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from isj_agent.protocol.intents import Intents
from isj_agent.protocol.results import SearcherResult


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
