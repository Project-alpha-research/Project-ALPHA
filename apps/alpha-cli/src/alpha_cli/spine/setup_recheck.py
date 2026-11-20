"""Recheck a stored setup study or trade test: compute it again and compare. Writes nothing.

It calls the same `compute_study` or `compute_trade` as the normal command, then compares the
stored summary and the stored per-occurrence table (every row) with the fresh ones. Left out:
the ledger count and the health record (they describe the ledger and the health report at the
time), the health labels, and the facts (copies of summary numbers with the labels).
"""

from __future__ import annotations

import io
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from polars.exceptions import PolarsError

from alpha_cli.spine import setup_study, setup_trade
from alpha_cli.spine.errors import SpineError, study_error
from alpha_cli.spine.facts import read_study
from alpha_cli.spine.recheck_compare import diff_trees, table, without_health
from alpha_cli.spine.setup_exits import trades_frame
from alpha_core import DataError

NOTHING = "no stored result to compare with"
SKIPPED = {"facts", "total_trials", "data_health"}
SHOWN = 10
FAILURES = (ValueError, OSError, DataError, KeyError, TypeError, PolarsError)


def _table(frame: Any) -> dict[str, Any]:
    """The fresh table read back from parquet bytes, as the stored one is read from its file."""
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    buffer.seek(0)
    return table(buffer)


def _answer(
    destination: Path, find_id: str, key: str, compute: Any, rows_file: str
) -> dict[str, Any]:
    """Compare a fresh summary and table with the ones stored at `destination`."""
    if not (destination / "manifest.json").exists():
        recheck: dict[str, Any] = {"compared_with": None, "computed": False, "match": None}
        recheck["reason"] = NOTHING
        return {"find_id": find_id, key: None, "executed": False, "recheck": recheck}
    started = time.monotonic()
    fresh, frame = compute()
    stored = read_study(destination)
    left = {k: v for k, v in stored.items() if k not in SKIPPED}
    right = {k: v for k, v in fresh.items() if k not in SKIPPED}
    left["labels"], right["labels"] = (
        without_health(left.get("labels")),
        without_health(right.get("labels")),
    )
    compared = diff_trees(left, right, "summary")
    path = destination / rows_file
    compared.add(diff_trees(table(path) if path.exists() else None, _table(frame), rows_file))
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


def _trade(home: Path, item: Any) -> tuple[dict[str, Any], Any]:
    summary, rows = setup_trade.compute_trade(home, item)
    return summary, trades_frame(rows)


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
            lambda: setup_study.compute_study(home, find_id, item),
            "outcomes.parquet",
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
            destination,
            find_id,
            "trade_id",
            lambda: _trade(home, item),
            "trades.parquet",
        )
    except FAILURES as exc:
        if isinstance(exc, SpineError):
            raise
        raise SpineError(
            "TRADE_FAILED",
            str(exc),
            "Correct the reported data or trade error, then run alpha setup trade again.",
        ) from exc
