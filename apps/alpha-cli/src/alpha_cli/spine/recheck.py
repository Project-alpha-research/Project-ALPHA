"""Recheck a stored rule test: compute it again with the current code and compare.

A recheck is not a trial and not a new observation. It runs the same `prepare_asset` and
`write_run` as a normal test, into a scratch folder that is removed afterwards, with the ledger
as it was when the stored run was computed. It writes no ledger row, no run folder and no
manifest, and it changes no stored file. With nothing stored to compare with, it computes
nothing and says so.
"""

from __future__ import annotations

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
from alpha_cli.spine.run import new_result, prepare_asset, write_run
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.trial_reader import spine_snapshot
from alpha_cli.spine.trial_record import TestKey, row_test_key

__all__ = ["MISMATCH_EXIT", "NOTHING", "recheck_idea"]

NOTHING = "no stored result to compare with"
SHOWN = 10


def _stored_run(
    home: Path, rows: list[dict[str, Any]], key: TestKey | None
) -> tuple[str, int] | None:
    """The newest non-error stored run of this test key, and the index of the ledger row that
    first recorded that run (the ledger it was computed with is every row before it)."""
    for row in reversed(rows):
        run_id = row.get("run_id")
        if (
            key is None
            or row_test_key(row) != key
            or "error" in (row.get("labels") or ())
            or not isinstance(run_id, str)
            or not (_artifacts.run_dir(home, run_id) / "manifest.json").is_file()
        ):
            continue
        first = next(
            r for r in rows if r.get("run_id") == run_id and "error" not in (r.get("labels") or ())
        )
        return run_id, int(first["trial_index"])
    return None


def _earlier_ledger(home: Path, scratch: Path, upto: int) -> None:
    """Copy the ledger rows before row `upto` into the scratch folder (the home is only read)."""
    lines = (home / "ledger" / "trials.jsonl").read_bytes().splitlines(keepends=True)
    target = scratch / "ledger" / "trials.jsonl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"".join(lines[: upto - 1]))


def _compute(
    idea: IdeaSpec,
    prepared: Any,
    home: Path,
    knobs: _gauntlet.GauntletParams,
    result: dict[str, Any],
    stored: tuple[str, int],
) -> dict[str, Any]:
    run_id, index = stored
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="alpha-recheck-") as name:
        scratch = Path(name)
        _earlier_ledger(home, scratch, index)
        result["run_dir"] = str(_artifacts.run_dir(scratch, prepared.identity.run_id))
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
        "code_changed": then != prepared.identity.execution_fingerprint,
    }


def _nothing(why: str) -> dict[str, Any]:
    return {"compared_with": None, "computed": False, "match": None, "reason": why}


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
    knobs = _gauntlet.GauntletParams(seed=seed)
    if quick:
        knobs = replace(
            knobs, tier1_paths=20, tier2_paths=4, tier3_paths=4, n_resamples=50, max_workers=1
        )
    rows = read_trials_readonly(home)
    results = []
    for asset in idea.assets:
        result = new_result(asset, quick=quick, no_diagnose=no_diagnose)
        try:
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
            stored = _stored_run(home, rows, key)
            result["recheck"] = (
                _nothing(NOTHING)
                if stored is None
                else _compute(idea, prepared, home, knobs, result, stored)
            )
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
