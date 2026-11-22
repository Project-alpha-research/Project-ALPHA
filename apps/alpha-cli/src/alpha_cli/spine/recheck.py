"""Recheck a stored rule test: compute it again with the current code and compare.

A recheck is not a trial and not a new observation. It runs the same `prepare_asset` and
`write_run` as a normal test, into a scratch folder that is removed afterwards, with the ledger
as it was when the stored run was computed. It writes no ledger row, no run folder and no
manifest, and it changes no stored file. With nothing stored to compare with, it computes
nothing and says so.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import tempfile
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from alpha_cli import _artifacts, _gauntlet
from alpha_cli.spine import idea_card
from alpha_cli.spine.deflation import spine_test_key
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import read_json
from alpha_cli.spine.ledger import read_trials_readonly
from alpha_cli.spine.recheck_compare import MISMATCH_EXIT, compare_runs
from alpha_cli.spine.run import gauntlet_knobs, new_result, prepare_asset, write_run
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.trial_reader import spine_snapshot
from alpha_cli.spine.trial_record import TestKey, row_test_key

__all__ = ["MISMATCH_EXIT", "NOTHING", "recheck_idea", "recheck_one"]

NOTHING = "no stored result to compare with"
DATA_CHANGED = (
    "no stored result for this data: the stored bars changed since the last stored run of this "
    "test, so there is nothing to compare with"
)
OTHER_SETTINGS = (
    "no stored result with the same settings: the stored runs of this test used other engine "
    "settings (--quick, --seed or no diagnostics), so there is nothing to compare with"
)
SHOWN = 10
ENGINE_LABELS = ("quick", "no-diagnostics")
# Not settings of the result: the worker count; `tier2_mode` is not recorded in the manifest.
NOT_SETTINGS = ("max_workers", "tier2_mode")


def _settings(knobs: _gauntlet.GauntletParams, labels: list[str]) -> dict[str, Any]:
    """The engine settings a stored run must share: the gauntlet knobs and the engine labels."""
    found = {f.name: getattr(knobs, f.name) for f in dataclasses.fields(knobs)}
    for name in NOT_SETTINGS:
        found.pop(name, None)
    found["labels"] = sorted(set(ENGINE_LABELS) & set(labels))
    return found


def _stored_settings(manifest: dict[str, Any], wanted: dict[str, Any]) -> dict[str, Any]:
    metadata = manifest.get("metadata") or {}
    found = {name: metadata.get(name) for name in wanted if name != "labels"}
    labels = (manifest.get("spine") or {}).get("labels") or []
    return {**found, "labels": sorted(set(ENGINE_LABELS) & set(labels))}


def _stored_run(
    home: Path,
    rows: list[dict[str, Any]],
    key: TestKey | None,
    wanted: dict[str, Any],
    same_asset: tuple[str, str, str | None],
) -> tuple[str, int] | str:
    """The newest non-error stored run of this test key with the same engine settings, and the
    index of the ledger row that first recorded that run (the ledger it was computed with is
    every row before it). Otherwise the reason there is nothing to compare with."""
    same_key = False
    for row in reversed(rows):
        run_id = row.get("run_id")
        manifest = _artifacts.run_dir(home, str(run_id)) / "manifest.json"
        if (
            key is None
            or row_test_key(row) != key
            or "error" in (row.get("labels") or ())
            or not isinstance(run_id, str)
            or not manifest.is_file()
        ):
            continue
        same_key = True
        if _stored_settings(read_json(manifest), wanted) != wanted:
            continue
        first = next(
            r for r in rows if r.get("run_id") == run_id and "error" not in (r.get("labels") or ())
        )
        return run_id, int(first["trial_index"])
    if same_key:
        return OTHER_SETTINGS
    if any(
        row_test_key(row) is not None
        and (row.get("spec_sha256"), row.get("symbol"), row.get("store")) == same_asset
        and "error" not in (row.get("labels") or ())
        for row in rows
    ):
        return DATA_CHANGED
    return NOTHING


def _earlier_ledger(home: Path, scratch: Path, upto: int) -> None:
    """Copy the ledger rows before row `upto` into the scratch folder (the home is only read)."""
    lines = (home / "ledger" / "trials.jsonl").read_bytes().splitlines(keepends=True)
    target = scratch / "ledger" / "trials.jsonl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"".join(lines[: upto - 1]))


def _frozen_costs(idea: IdeaSpec, prepared: Any, run_dir: Path, result: dict[str, Any]) -> Any:
    """A class-default run is rechecked with the costs it stored, never with today's table."""
    if not idea.costs_class_default:
        return prepared
    spine = read_json(run_dir / "manifest.json").get("spine")
    used = spine.get("costs") if isinstance(spine, dict) else None
    if not isinstance(used, dict):
        raise ValueError(f"stored run {run_dir.name} takes class costs but stored none")
    result["costs"] = used
    spec = replace(prepared.spec, fee_bps=used["fee_bps"], slippage_bps=used["slippage_bps"])
    return replace(prepared, spec=spec)


def _compute(
    idea: IdeaSpec,
    prepared: Any,
    home: Path,
    knobs: _gauntlet.GauntletParams,
    result: dict[str, Any],
    stored: tuple[str, int],
) -> dict[str, Any]:
    run_id, index = stored
    current = prepared.identity.execution_fingerprint
    prepared = _frozen_costs(idea, prepared, _artifacts.run_dir(home, run_id), result)
    # The stored run id seeds the price-noise copies: the same seed, so the same test again,
    # even when the code (and so a new run id) changed.
    prepared = replace(prepared, identity=replace(prepared.identity, run_id=run_id))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="alpha-recheck-") as name:
        scratch = Path(name)
        _earlier_ledger(home, scratch, index)
        result["run_dir"] = str(_artifacts.run_dir(scratch, run_id))
        # The report library names the scratch folder, which is gone afterwards: keep it quiet.
        with contextlib.redirect_stdout(io.StringIO()):
            write_run(
                idea,
                prepared,
                home,
                scratch,
                knobs,
                "recheck",
                result,
                snapshot=spine_snapshot(scratch),
                figures=False,
            )
        old = _artifacts.run_dir(home, run_id)
        compared = compare_runs(old, Path(result["run_dir"]))
    then = read_json(old / "manifest.json").get("execution_fingerprint")
    return {
        "compared_with": run_id,
        "computed": True,
        "seconds": round(time.monotonic() - started, 2),
        "match": not compared.differences,
        "bit_identical": compared.bit_identical,
        "differences": compared.differences[:SHOWN],
        "differences_total": len(compared.differences),
        "code_changed": then != current,
    }


def _nothing(why: str) -> dict[str, Any]:
    return {"compared_with": None, "computed": False, "match": None, "reason": why}


def _recheck_asset(
    idea: IdeaSpec,
    asset: str,
    home: Path,
    knobs: _gauntlet.GauntletParams,
    rows: list[dict[str, Any]],
    result: dict[str, Any],
    accept_bad_data: str | None = None,
    report_time: datetime | None = None,
) -> None:
    """Fill ``result`` (from `new_result`) with the recheck of one asset."""
    prepared = prepare_asset(
        idea,
        asset,
        home,
        knobs,
        result,
        accept_bad_data=accept_bad_data,
        report_time=report_time,
    )
    key = spine_test_key(
        idea.spec_sha256,
        result["symbol"],
        result["first_ts"],
        result["last_ts"],
        result["periods_per_year"],
        store=result["store"],
        data_id=result["idea_id"],
    )
    stored = _stored_run(
        home,
        rows,
        key,
        _settings(knobs, result["labels"]),
        (idea.spec_sha256, result["symbol"], result["store"]),
    )
    result["recheck"] = (
        _nothing(stored)
        if isinstance(stored, str)
        else _compute(idea, prepared, home, knobs, result, stored)
    )


def recheck_one(
    idea: IdeaSpec,
    asset: str,
    *,
    home: Path,
    knobs: _gauntlet.GauntletParams,
    quick: bool,
    no_diagnose: bool,
) -> dict[str, Any]:
    """The recheck of one asset with the given engine settings; raises on any failure."""
    result = new_result(asset, quick=quick, no_diagnose=no_diagnose)
    _recheck_asset(idea, asset, home, knobs, read_trials_readonly(home), result)
    return result


def recheck_idea(
    idea: IdeaSpec,
    *,
    home: Path,
    seed: int = 7,
    quick: bool = False,
    no_diagnose: bool = False,
    accept_bad_data: str | None = None,
    report_time: datetime | None = None,
) -> dict[str, Any]:
    """One recheck per asset, in the shape of a rule-test result with a `recheck` block."""
    idea_card.require(home, idea.idea_card)
    knobs = gauntlet_knobs(seed, quick)
    rows = read_trials_readonly(home)
    results = []
    for asset in idea.assets:
        result = new_result(asset, quick=quick, no_diagnose=no_diagnose)
        try:
            _recheck_asset(idea, asset, home, knobs, rows, result, accept_bad_data, report_time)
        except SpineError:
            raise
        except Exception as exc:  # one asset's failure is reported; the others continue
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["recheck"] = _nothing(result["error"])
        found = result["recheck"]
        results.append(
            {
                "asset": asset,
                "symbol": result["symbol"],
                "store": result["store"],
                "run_id": found.get("compared_with"),
                "executed": found["computed"],
                "labels": result["labels"],
                "error": result["error"],
                "recheck": found,
            }
        )
    return {
        "recheck": True,
        "spec_sha256": idea.spec_sha256,
        "name": idea.name,
        "trials_total": len(rows),
        "results": results,
    }
