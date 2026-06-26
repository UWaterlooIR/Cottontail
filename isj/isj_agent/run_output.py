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

cp-native boundary (doc-6 / TASK-6.3): results are `cp` in memory but **docno on disk**.
This writer rewrites every persisted `cp` to its `docno` via the read-only DocnoMap --
in the RankedList AND in the trace events -- so the saved files are portable. A
docno-less corpus (no map) persists cps.

PURE filesystem: no network, no LLM, no Searcher logic, and no error CATCHING -- C3
runs the pipeline, catches the errors, and passes them in as RunError outcomes / a
run-level error. C2 only persists.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel

from isj_agent.docno_map import DocnoMap
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
    docno_map: DocnoMap | None = None,
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

    rename = docno_map is not None
    cache: dict[int, int | str] = {}

    def resolve(cp: int) -> int | str:
        if docno_map is None:
            return cp
        if cp not in cache:
            d = docno_map.docno(cp)
            cache[cp] = d if d is not None else cp  # unmapped cp -> keep the cp
        return cache[cp]

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
        rl = _ranked_list_dict(outcome.ranked_list, resolve, rename)
        (out_dir / f"intent-{i:02d}.json").write_text(
            json.dumps(rl, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        lines = [
            json.dumps(_event_dict(ev, resolve, rename), ensure_ascii=False)
            for ev in outcome.events
        ]
        (out_dir / f"intent-{i:02d}.trace.jsonl").write_text(
            "".join(line + "\n" for line in lines), encoding="utf-8"
        )

    if run_error:
        errors.append(f"run-level error: {run_error}")
    if errors:
        (out_dir / "errors.log").write_text("\n".join(errors) + "\n", encoding="utf-8")


_Resolve = Callable[[int], "int | str"]


def _rewrite_cp(d: dict, resolve: _Resolve, rename: bool) -> None:
    """Rewrite a dict's scalar `cp` in place; rename the key to `docno` iff rename."""
    cp = d.pop("cp")
    if rename:
        d["docno"] = resolve(cp)
    else:
        d["cp"] = resolve(cp)


def _ranked_list_dict(ranked_list, resolve: _Resolve, rename: bool) -> dict:
    d = ranked_list.model_dump()
    for entry in d["entries"]:
        _rewrite_cp(entry, resolve, rename)
    return d


def _event_dict(event, resolve: _Resolve, rename: bool) -> dict:
    d = event.model_dump()
    t = d.get("type")
    if t == "search_request":  # the request, logged going out: only an exclude cp-list
        if "exclude" in d:
            d["exclude"] = [resolve(cp) for cp in d["exclude"]]
    elif t == "search":
        if "exclude" in d:
            d["exclude"] = [resolve(cp) for cp in d["exclude"]]
        for hit in d.get("results", []):
            _rewrite_cp(hit, resolve, rename)
    elif t == "judge":
        for verdict in d.get("judgements", []):
            _rewrite_cp(verdict, resolve, rename)
    elif t == "bounce":
        if "cps" in d:
            d["cps"] = [resolve(cp) for cp in d["cps"]]
    return d
