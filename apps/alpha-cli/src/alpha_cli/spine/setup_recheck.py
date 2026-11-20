"""Recheck a stored setup study or trade test: compute it again and compare. Writes nothing.

It calls the same `compute_study` or `compute_trade` as the normal command, then compares the
numbers with the stored summary. The ledger count and the label list are left out: they
describe the ledger and the health report at the time, not the computed result.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from polars.exceptions import PolarsError

from alpha_cli.spine import setup_study, setup_trade
from alpha_cli.spine.errors import SpineError, study_error
from alpha_cli.spine.facts import read_study
from alpha_cli.spine.recheck_compare import diff_trees
from alpha_core import DataError

NOTHING = "no stored result to compare with"
SKIPPED = {"labels", "facts", "total_trials", "data_health"}
SHOWN = 10
FAILURES = (ValueError, OSError, DataError, KeyError, TypeError, PolarsError)


def _answer(destination: Path, find_id: str, key: str, compute: Any) -> dict[str, Any]:
    """Compare a fresh summary with the one stored at `destination`."""
    if not (destination / "manifest.json").exists():
        recheck: dict[str, Any] = {"compared_with": None, "computed": False, "match": None}
        recheck["reason"] = NOTHING
        return {"find_id": find_id, key: None, "executed": False, "recheck": recheck}
    started = time.monotonic()
    fresh = compute()
    stored = read_study(destination)
    names = {*stored, *fresh} - SKIPPED
    left = {k: stored.get(k) for k in names}
    right = {k: fresh.get(k) for k in names}
    compared = diff_trees(left, right, "summary")
    recheck = {
        "compared_with": destination.name,
        "computed": True,
        "seconds": round(time.monotonic() - started, 2),
        "match": not compared.differences,
        "bit_identical": compared.bit_identical,
        "differences": compared.differences[:SHOWN],
        "differences_total": len(compared.differences),
        "code_changed": None,
    }
    return {"find_id": find_id, key: destination.name, "executed": True, "recheck": recheck}


def recheck_study(
    find_id: str,
    *,
    home: Path,
    accept_bad_data: str | None = None,
    report_time: datetime | None = None,
) -> dict[str, Any]:
    try:
        item = setup_study.read_inputs(find_id, home, False, accept_bad_data, report_time)
        destination = home / "setup-studies" / item.study_id
        return _answer(
            destination,
            find_id,
            "study_id",
            lambda: setup_study.compute_study(home, find_id, item)[0],
        )
    except FAILURES as exc:
        raise study_error(exc) from exc


def recheck_trade(
    find_id: str,
    *,
    home: Path,
    accept_bad_data: str | None = None,
    report_time: datetime | None = None,
) -> dict[str, Any]:
    try:
        item = setup_trade.read_inputs(find_id, home, False, accept_bad_data, report_time)
        destination = home / "setup-trades" / item.trade_id
        return _answer(
            destination, find_id, "trade_id", lambda: setup_trade.compute_trade(home, item)[0]
        )
    except FAILURES as exc:
        if isinstance(exc, SpineError):
            raise
        raise SpineError(
            "TRADE_FAILED",
            str(exc),
            "Correct the reported data or trade error, then run alpha setup trade again.",
        ) from exc
