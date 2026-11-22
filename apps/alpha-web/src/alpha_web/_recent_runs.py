"""The Overview's recent-tests table: the newest stored runs with the columns the owner reads.

A bounded, read-only read of what is already stored (run manifests and equity curves). Nothing here
computes a statistic: the trade count, the out-of-sample Sharpe and the evidence word are relayed as
the run stored them. The sparkline is the stored equity curve thinned to a fixed number of points.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alpha_web import _rule_test, _runs

SPARK_POINTS = 60


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def thin(values: list[float], points: int = SPARK_POINTS) -> list[float]:
    """Every n-th value, always keeping the first and the last; short series pass unchanged."""
    if len(values) <= points:
        return values
    step = (len(values) - 1) / (points - 1)
    return [values[round(index * step)] for index in range(points)]


def _row(record: dict[str, Any], *, data_dir: Path, spark: bool) -> dict[str, Any]:
    run_id = str(record["run_id"])
    rdir = data_dir / str(record["kind"]) / run_id
    manifest = _runs._verified_manifest(rdir)
    test = _rule_test.rule_test(manifest, rdir) or {}
    full = _map(_map(test.get("diagnostics")).get("full_sample"))
    trades = full.get("trades")
    counts = _map(_map(manifest.get("reading")).get("counts"))
    tries = counts.get("family_trials")
    curve = _runs.equity_series(run_id, data_dir=data_dir)["equity"] if spark else []
    return {
        "run_id": run_id,
        "kind": record["kind"],
        "mtime": record["mtime"],
        "display_name": record["display_name"],
        "symbol": record["symbol"] or record["label"],
        "idea": test.get("idea"),
        "rule_name": test.get("name"),
        "first_ts": test.get("first_ts"),
        "last_ts": test.get("last_ts"),
        "trades": trades if isinstance(trades, int) and not isinstance(trades, bool) else None,
        "tries": tries if isinstance(tries, int) and not isinstance(tries, bool) else None,
        "oos_sharpe": _number(_map(manifest.get("oos_metrics")).get("sharpe")),
        "evidence": record["evidence"],
        "spark": thin(curve),
    }


def recent_runs(*, data_dir: Path, limit: int, spark: bool) -> dict[str, Any]:
    """The newest stored runs with the recent-tests columns; unreadable runs are skipped."""
    listed = _runs.query_runs(data_dir=data_dir, limit=limit)
    items: list[dict[str, Any]] = []
    for record in listed["items"]:
        try:
            items.append(_row(record, data_dir=data_dir, spark=spark))
        except (OSError, ValueError, KeyError):
            continue
    return {"total": listed["total"], "items": items}
