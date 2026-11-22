"""Workstation desk reads: the recent-tests table and the frame's status dot.

Both are bounded, read-only reads of what is already stored (run manifests and equity curves) or
relays of one CLI command (``alpha nightly status --json``). Nothing here computes a statistic: the
trade count, the out-of-sample Sharpe and the evidence word are relayed as the run stored them.
The sparkline is the stored equity curve thinned to a fixed number of points for display.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alpha_core.reserve import RESERVED_START
from alpha_web import _rule_test, _runs
from alpha_web._catalog import _run_json

SPARK_POINTS = 60
_NIGHTLY_TIMEOUT_SECONDS = 30.0


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
    """The newest stored runs with the columns the desk tables show; unreadable runs are skipped."""
    listed = _runs.query_runs(data_dir=data_dir, limit=limit)
    items: list[dict[str, Any]] = []
    for record in listed["items"]:
        try:
            items.append(_row(record, data_dir=data_dir, spark=spark))
        except (OSError, ValueError, KeyError):
            continue
    return {"total": listed["total"], "items": items}


def desk_status(*, data_dir: Path) -> dict[str, Any]:
    """The reserved start and the last nightly run, or why the nightly record could not be read."""
    nightly: dict[str, Any] | None = None
    problem: str | None = None
    try:
        facts = _run_json(
            ["nightly", "status", "--json"],
            data_dir=data_dir,
            timeout_seconds=_NIGHTLY_TIMEOUT_SECONDS,
        )
    except RuntimeError as exc:
        problem = str(exc)
    else:
        last = _map(_map(facts).get("last"))
        if last:
            nightly = {
                "date": str(last.get("date") or ""),
                "run_number": last.get("run_number")
                if isinstance(last.get("run_number"), int)
                else None,
                "complete": str(last.get("complete") or ""),
                "blocking": int(last.get("blocking") or 0),
                "minor": int(last.get("minor") or 0),
                "ready": bool(_map(facts).get("ready")),
                "reasons": [str(r) for r in _map(facts).get("reasons") or []],
            }
    return {"reserved_start": RESERVED_START, "nightly": nightly, "nightly_problem": problem}
