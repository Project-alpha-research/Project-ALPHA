"""Run-analytics reads for the workstation: forecast cones and paths, nulls, trials, origins.

Each reader loads one parquet artifact (or the tearsheet) from a verified run directory and
projects it to JSON for a run-detail chart. No engine, no subprocess.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from alpha_core import DataError
from alpha_web import _runs


def forecast_series(run_id: str, *, data_dir: Path) -> dict[str, Any] | None:
    """History + forecast-cone closes (median + quantile bands) for a forecast run's chart.

    Reads the CLI's ``quantiles.parquet`` (per-step close quantiles) and ``history.parquet``.
    The median line is ``q50``; the outer q05/q95 band retains the established ``p10``/``p90``
    wire keys for compatibility. The inner band and sample mean use ``q25``/``q75``/``mean``.
    Returns None for runs that wrote no cone artifacts.
    """
    quant = _runs._artifact_frame(run_id, "quantiles.parquet", data_dir=data_dir)
    history = _runs._artifact_frame(run_id, "history.parquet", data_dir=data_dir)
    if quant is None or history is None:
        return None
    ohlcv_columns = {"open", "high", "low", "close", "volume"}
    history_ohlcv_available = ohlcv_columns.issubset(history.columns)
    history_bars = (
        [
            {
                "t": row["ts"].timestamp(),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": float(row["volume"]),
            }
            for row in history.iter_rows(named=True)
        ]
        if history_ohlcv_available
        else []
    )
    return {
        "history": [float(v) for v in history["close"].to_list()],
        "history_bars": history_bars,
        "history_ohlcv_available": history_ohlcv_available,
        "forecast": [float(v) for v in quant["q50"].to_list()],
        "p10": [float(v) for v in quant["q05"].to_list()],
        "p90": [float(v) for v in quant["q95"].to_list()],
        "q25": [float(v) for v in quant["q25"].to_list()],
        "q75": [float(v) for v in quant["q75"].to_list()],
        "mean": [float(v) for v in quant["mean"].to_list()],
        # timestamps (epoch seconds) for the client-side chart's x-axis.
        "history_ts": [t.timestamp() for t in history["ts"].to_list()],
        "forecast_ts": [t.timestamp() for t in quant["ts"].to_list()],
    }


MAX_FORECAST_PATHS = 40  # spaghetti-line cap: more is unreadable and bloats the payload


def forecast_paths(run_id: str, *, data_dir: Path, n: int = 20) -> dict[str, Any] | None:
    """The first ``n`` sampled OHLCV paths of a forecast run (deterministic — no RNG).

    Reads the forecast run's ``paths.parquet`` (per-sample OHLCV, long) and returns
    ``{samples: [{sample, opens, highs, lows, closes, volumes}], ts}`` with epoch seconds.
    [1, MAX_FORECAST_PATHS]. Returns None when the run is absent or wrote no paths.
    """
    rdir = _runs._run_dir(run_id, data_dir=data_dir)
    if rdir is None or rdir.parent.name != "forecast":
        return None
    frame = _runs._artifact_frame(
        run_id, "paths.parquet", data_dir=data_dir, sort=("sample", "step")
    )
    if frame is None:
        return None
    n = max(1, min(n, MAX_FORECAST_PATHS))
    parts = frame.partition_by("sample", maintain_order=True)[:n]
    if not parts:
        raise DataError(f"forecast run {run_id!r} wrote an empty paths.parquet")
    reference_steps = parts[0]["step"].to_list()
    reference_ts = parts[0]["ts"].to_list()
    for part in parts[1:]:
        if part["step"].to_list() != reference_steps or part["ts"].to_list() != reference_ts:
            raise DataError(f"forecast run {run_id!r} wrote misaligned sampled paths")
    return {
        "samples": [
            {
                "sample": int(part["sample"][0]),
                "opens": [float(v) for v in part["open"].to_list()],
                "highs": [float(v) for v in part["high"].to_list()],
                "lows": [float(v) for v in part["low"].to_list()],
                "closes": [float(v) for v in part["close"].to_list()],
                "volumes": [float(v) for v in part["volume"].to_list()],
            }
            for part in parts
        ],
        "ts": [t.timestamp() for t in reference_ts],
    }


def null_distributions(run_id: str, *, data_dir: Path) -> dict[str, Any] | None:
    """A gauntlet run's raw per-tier null distributions, ``{tiers: [{tier, statistics}]}``.

    Reads ``nulls.parquet`` (one row per (tier, path), written sorted). Statistics are served in
    (tier, path_index) order. Returns None when the run is absent or wrote no null artifact.
    """
    frame = _runs._artifact_frame(
        run_id, "nulls.parquet", data_dir=data_dir, sort=("tier", "path_index")
    )
    if frame is None:
        return None
    return {
        "tiers": [
            {
                "tier": str(part["tier"][0]),
                "statistics": [float(v) for v in part["statistic"].to_list()],
            }
            for part in frame.partition_by("tier", maintain_order=True)
        ]
    }


def optim_trials(run_id: str, *, data_dir: Path) -> dict[str, Any] | None:
    """A sweep's per-config OOS return streams, ``{trials: [{trial, returns}]}``.

    Reads ``trials.parquet`` (one row per (trial, step), written sorted); ``trial`` aligns with
    the manifest's ``configs``/``sharpes`` order. No server-side math beyond grouping. Returns
    None when the run is absent or wrote no trials artifact.
    """
    frame = _runs._artifact_frame(
        run_id, "trials.parquet", data_dir=data_dir, sort=("trial", "step")
    )
    if frame is None:
        return None
    return {
        "trials": [
            {
                "trial": int(part["trial"][0]),
                "returns": [float(v) for v in part["oos_return"].to_list()],
            }
            for part in frame.partition_by("trial", maintain_order=True)
        ]
    }


def propfirm_paths(run_id: str, *, data_dir: Path) -> dict[str, Any] | None:
    """A prop-firm run's per-path Monte-Carlo outcomes, columnar.

    Reads ``propfirm_paths.parquet`` (one row per path, sorted by path_index). ``days_to_pass``
    is NaN on disk for never-passed paths — converted to None here (JSON has no NaN). Returns
    None when the run is absent or wrote no paths artifact.
    """
    rdir = _runs._run_dir(run_id, data_dir=data_dir)
    if rdir is None or rdir.parent.name != "propfirm":
        return None
    frame = _runs._artifact_frame(run_id, "propfirm_paths.parquet", data_dir=data_dir)
    if frame is None:
        # Complete pre-hardening runs used the ambiguous filename shared with forecast runs.
        frame = _runs._artifact_frame(run_id, "paths.parquet", data_dir=data_dir)
    if frame is None:
        return None
    frame = frame.sort("path_index")
    return {
        "paths": {
            "passed": [bool(v) for v in frame["passed"].to_list()],
            "busted": [bool(v) for v in frame["busted"].to_list()],
            "days_to_pass": [
                None if math.isnan(v) else float(v) for v in frame["days_to_pass"].to_list()
            ],
            "payout": [float(v) for v in frame["payout"].to_list()],
        }
    }


def forecast_origins(run_id: str, *, data_dir: Path) -> dict[str, Any] | None:
    """A forecast-eval run's per-origin skill scores, columnar (``origin_ts`` in epoch seconds).

    Reads ``origins.parquet`` (one row per rolling origin) and serves the chart/table columns:
    timestamps, cutoff split, CRPS vs both baselines, end returns, and the hit/coverage booleans.
    Returns None when the run is absent or wrote no origins artifact.
    """
    frame = _runs._artifact_frame(
        run_id, "origins.parquet", data_dir=data_dir, sort=("origin_index",)
    )
    if frame is None:
        return None
    return {
        "origin_ts": [t.timestamp() for t in frame["origin_ts"].to_list()],
        "pre_cutoff": [bool(v) for v in frame["pre_cutoff"].to_list()],
        "crps": [float(v) for v in frame["crps"].to_list()],
        "crps_rw": [float(v) for v in frame["crps_rw"].to_list()],
        "crps_bootstrap": [float(v) for v in frame["crps_bootstrap"].to_list()],
        "realized_end_return": [float(v) for v in frame["realized_end_return"].to_list()],
        "median_end_return": [float(v) for v in frame["median_end_return"].to_list()],
        "hit": [bool(v) for v in frame["hit"].to_list()],
        "cover50": [bool(v) for v in frame["cover50"].to_list()],
        "cover80": [bool(v) for v in frame["cover80"].to_list()],
        "cover90": [bool(v) for v in frame["cover90"].to_list()],
    }


def tearsheet_file(run_id: str, *, data_dir: Path) -> Path | None:
    """Path to the run's ``tearsheet.html`` if written (gauntlet/portfolio runs), else None."""
    rdir = _runs._run_dir(run_id, data_dir=data_dir)
    if rdir is None:
        return None
    path = rdir / "tearsheet.html"
    return path if path.exists() else None
