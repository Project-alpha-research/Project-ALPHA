"""The path, metric and observed-equity tables a Monte Carlo run publishes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import numpy as np
import polars as pl

from alpha_core import DataError
from alpha_validation import (
    MonteCarloFamilySummaryV1,
    path_metric_arrays,
    summarize_path_family,
)

MIN_STATE_SHARE = 0.10


def _regime_caveats(state_observations: tuple[int, int], horizon: int) -> tuple[str, ...]:
    n0, n1 = state_observations
    p0, p1 = n0 / horizon, n1 / horizon
    caveats: tuple[str, ...] = (
        f"Causal states: calm {n0} of {horizon} OOS returns ({p0:.1%}), "
        f"volatile {n1} ({p1:.1%}); the boundary is frozen from the first training prefix.",
    )
    if min(p0, p1) < MIN_STATE_SHARE:
        caveats += (
            f"One state holds under {MIN_STATE_SHARE:.0%} of OOS returns: its emissions and "
            "transitions rest on few observations, and the frozen boundary may not describe "
            "the OOS period; compare this family with the IID empirical family.",
        )
    return caveats


def _path_frame(families: Sequence[tuple[str, np.ndarray]]) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for family, paths in families:
        if paths.ndim != 2:
            raise DataError(f"Monte Carlo path matrix for {family!r} must be two-dimensional")
        n_paths, horizon = paths.shape
        frame = pl.DataFrame(
            {
                "path_index": np.repeat(np.arange(n_paths, dtype=np.int64), horizon),
                "step": np.tile(np.arange(horizon, dtype=np.int64), n_paths),
                "account_return": np.asarray(paths, dtype=np.float64).reshape(-1),
            },
            schema={
                "path_index": pl.Int64,
                "step": pl.Int64,
                "account_return": pl.Float64,
            },
        ).with_columns(pl.lit(family).alias("family"))
        frames.append(frame.select("family", "path_index", "step", "account_return"))
    if not frames:
        raise DataError("at least one Monte Carlo path family is required")
    return pl.concat(frames, how="vertical")


def _metric_frame(families: Sequence[tuple[str, np.ndarray]]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for family, paths in families:
        metrics = path_metric_arrays(paths)
        rows.extend(
            {
                "family": family,
                "path_index": path_index,
                "terminal_return": float(metrics.terminal_return[path_index]),
                "maximum_drawdown": float(metrics.maximum_drawdown[path_index]),
                "longest_loss_streak": int(metrics.longest_loss_streak[path_index]),
                "loss": bool(metrics.loss[path_index]),
                "ruined": bool(metrics.ruined[path_index]),
            }
            for path_index in range(paths.shape[0])
        )
    return pl.DataFrame(
        rows,
        schema={
            "family": pl.String,
            "path_index": pl.Int64,
            "terminal_return": pl.Float64,
            "maximum_drawdown": pl.Float64,
            "longest_loss_streak": pl.Int64,
            "loss": pl.Boolean,
            "ruined": pl.Boolean,
        },
    )


def _summarize_families(
    families: Sequence[tuple[str, np.ndarray]], states: np.ndarray, *, confidence: float
) -> tuple[tuple[int, int], tuple[str, ...], dict[str, MonteCarloFamilySummaryV1]]:
    """Summarize each family; the regime family carries its causal-state disclosure."""
    state_observations = (int(np.sum(states == 0)), int(np.sum(states == 1)))
    regime_caveats = _regime_caveats(state_observations, int(states.size))
    summaries = {
        name: summarize_path_family(
            name,
            values,
            confidence=confidence,
            caveats=regime_caveats if name == "regime_switching" else (),
        )
        for name, values in families
    }
    return state_observations, regime_caveats, summaries


def _observed_frame(equity: Sequence[tuple[datetime, float]]) -> pl.DataFrame:
    """The source run's observed out-of-sample equity, one row per step."""
    return pl.DataFrame(
        {
            "step": range(len(equity)),
            "ts": [timestamp for timestamp, _ in equity],
            "equity": [float(value) for _, value in equity],
        },
        schema={"step": pl.Int64, "ts": pl.Datetime("us", "UTC"), "equity": pl.Float64},
    )
