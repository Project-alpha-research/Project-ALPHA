"""The Machine learning window's list: stored ML runs (command ``ml_replay``), read-only.

Bounded read of what a finished ``alpha ml run`` already stored: the run manifest and
``folds.parquet``. Nothing here trains, replays or computes a statistic. The split sentence is the
one ``alpha ml run`` prints. A number the run did not store stays null, never zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli.ml_split import split_sentence
from alpha_core import DataError
from alpha_web import _runs

MAX_RUNS = 50
MAX_FOLDS = 200
#: The index is filtered by command before the newest 50 are kept, so the limit must not cut it.
ALL_RUNS = 1_000_000
_METRICS = (
    "total_return",
    "max_drawdown",
    "sharpe",
    "cagr",
    "mean_turnover",
    "total_fees",
    "total_slippage_cost",
)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _day(value: Any) -> str:
    return str(value)[:10]


def _folds(rdir: Path) -> list[dict[str, Any]]:
    path = rdir / "folds.parquet"
    if not path.is_file():
        return []
    frame = pl.read_parquet(path)
    return [
        {
            "fold": int(row["fold"]),
            "train_start": _day(row["train_start"]),
            "train_end": _day(row["train_end"]),
            "test_start": _day(row["test_start"]),
            "test_end": _day(row["test_end"]),
        }
        for row in frame.iter_rows(named=True)
    ]


def _model(manifest: Mapping[str, Any], rdir: Path) -> str:
    worker = manifest.get("worker")
    if not isinstance(worker, Mapping) or worker.get("kind") != "qlib":
        return "not recorded"
    if (rdir / "ensemble_diagnostics.parquet").is_file():
        return "LightGBM and ridge, ranks averaged (Qlib worker)"
    # The run stores the worker kind but not the recipe, and the worker accepts several models.
    return "Qlib worker; the model type is not recorded in the run"


def _costs(manifest: Mapping[str, Any]) -> str:
    costs = manifest.get("costs")
    fee = _number(costs.get("fee_bps")) if isinstance(costs, Mapping) else None
    slip = _number(costs.get("slippage_bps")) if isinstance(costs, Mapping) else None
    if fee is None or slip is None:
        return "not recorded"
    return f"{fee:g} bp fee and {slip:g} bp slippage per trade"


def _row(record: Mapping[str, Any], *, data_dir: Path) -> dict[str, Any]:
    rdir = data_dir / str(record["kind"]) / str(record["run_id"])
    manifest = _runs._verified_manifest(rdir)
    stored = manifest.get("metrics")
    stored = stored if isinstance(stored, Mapping) else {}
    metrics: dict[str, float | str | None] = {
        name: _number(stored.get(name)) for name in (*_METRICS, "benchmark_total_return")
    }
    metrics["sharpe_reason"] = (
        "Fewer than two scored periods, or no variation in returns."
        if metrics["sharpe"] is None
        else None
    )
    all_folds = _folds(rdir)
    folds = all_folds[:MAX_FOLDS]
    universe = manifest.get("universe")
    periods = manifest.get("n_oos_periods")
    return {
        "run_id": str(record["run_id"]),
        "mtime": record["mtime"],
        "assets": [str(a) for a in universe] if isinstance(universe, list) else [],
        "model": _model(manifest, rdir),
        "costs": _costs(manifest),
        "split_sentence": split_sentence(all_folds) if all_folds else None,
        "n_oos_periods": periods if isinstance(periods, int) else None,
        "label": manifest.get("label") if isinstance(manifest.get("label"), str) else None,
        "metrics": metrics,
        "folds": folds,
        "folds_total": len(all_folds),
    }


def ml_runs(*, data_dir: Path) -> dict[str, Any]:
    """The newest stored ML runs; an unreadable run is skipped."""
    listed = _runs.query_runs(data_dir=data_dir, limit=ALL_RUNS)
    found = [r for r in listed["items"] if r.get("command") == "ml_replay"]
    items: list[dict[str, Any]] = []
    for record in found[:MAX_RUNS]:
        try:
            items.append(_row(record, data_dir=data_dir))
        except (DataError, OSError, ValueError, KeyError, pl.exceptions.PolarsError):
            continue
    return {"total": len(found), "items": items}
