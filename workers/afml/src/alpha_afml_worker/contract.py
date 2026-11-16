"""The checked shapes that cross the worker boundary: daily bars in, label spans in or out.

Everything entering the worker is a Polars frame (read from Parquet by the command line). Bad
input fails loud here, before any library sees it: a library that is handed a NaN, a disordered
index or a naive timestamp may answer quietly instead of refusing.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl

BAR_COLUMNS = ("ts", "open", "high", "low", "close")
LABEL_SPAN_COLUMNS = ("start", "end")


class ContractError(ValueError):
    """Input that breaks the worker's contract. The worker exits non-zero on it."""


class AgreementError(RuntimeError):
    """The two libraries disagree where they are required to agree. Never swallowed."""


def _require_utc_datetime(frame: pl.DataFrame, column: str, what: str) -> None:
    dtype = frame.schema[column]
    if not isinstance(dtype, pl.Datetime) or dtype.time_zone != "UTC":
        raise ContractError(f"{what}.{column} must be an aware UTC datetime, got {dtype}")
    if frame[column].null_count():
        raise ContractError(f"{what}.{column} has missing timestamps")


def validate_bars(bars: pl.DataFrame) -> pl.DataFrame:
    """Daily (or intraday) OHLC bars: aware-UTC ``ts`` strictly increasing, prices finite > 0.

    Returns the bars with only the contract columns, as float64 prices and ``ts`` in
    microseconds, so every later step sees one dtype.
    """
    missing = [c for c in BAR_COLUMNS if c not in bars.columns]
    if missing:
        raise ContractError(f"bars are missing columns {missing}")
    if bars.height < 2:
        raise ContractError("bars need at least two rows")
    _require_utc_datetime(bars, "ts", "bars")
    out = bars.select(
        pl.col("ts").dt.cast_time_unit("us"),
        *(pl.col(c).cast(pl.Float64) for c in BAR_COLUMNS[1:]),
    )
    ts = out["ts"].to_numpy()
    if not bool(np.all(ts[1:] > ts[:-1])):
        raise ContractError("bars.ts must be strictly increasing (no duplicates, no disorder)")
    prices = out.select(BAR_COLUMNS[1:]).to_numpy()
    if not bool(np.all(np.isfinite(prices))) or bool(np.any(prices <= 0.0)):
        raise ContractError("bar prices must be finite and strictly positive")
    o, h, lo, c = (prices[:, i] for i in range(4))
    if bool(np.any(h < np.maximum(o, c))) or bool(np.any(lo > np.minimum(o, c))):
        raise ContractError("a bar's high is below its open/close or its low above them")
    return out


def validate_label_spans(spans: pl.DataFrame, bar_ts: pl.Series) -> tuple[np.ndarray, np.ndarray]:
    """Finished label spans ``start``/``end`` (both bar timestamps, end >= start) as positions.

    An unfinished label (``end`` missing) is refused: its uniqueness depends on bars that have
    not happened yet, so it cannot be weighted (study, section 4 table).
    """
    missing = [c for c in LABEL_SPAN_COLUMNS if c not in spans.columns]
    if missing:
        raise ContractError(f"label spans are missing columns {missing}")
    if spans.height == 0:
        raise ContractError("label spans are empty")
    for column in LABEL_SPAN_COLUMNS:
        _require_utc_datetime(spans, column, "labels")
    grid = bar_ts.dt.cast_time_unit("us").to_numpy()
    starts_ts = spans["start"].dt.cast_time_unit("us").to_numpy()
    ends_ts = spans["end"].dt.cast_time_unit("us").to_numpy()
    starts = np.searchsorted(grid, starts_ts)
    ends = np.searchsorted(grid, ends_ts)
    on_grid = (
        (starts < grid.size)
        & (ends < grid.size)
        & (grid[np.minimum(starts, grid.size - 1)] == starts_ts)
        & (grid[np.minimum(ends, grid.size - 1)] == ends_ts)
    )
    if not bool(np.all(on_grid)):
        raise ContractError("every label start and end must be one of the bar timestamps")
    if bool(np.any(ends < starts)):
        raise ContractError("a label ends before it starts")
    if bool(np.any(starts[1:] < starts[:-1])) or len(set(starts.tolist())) != starts.size:
        raise ContractError("label starts must be strictly increasing (one label per start bar)")
    return starts.astype(np.int64), ends.astype(np.int64)


def require_finite_positive(value: float, name: str) -> float:
    """A strictly positive finite float parameter, or a loud refusal."""
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ContractError(f"{name} must be finite and > 0, got {value!r}")
    return number


def require_int_at_least(value: int, name: str, minimum: int) -> int:
    """An integer parameter of at least ``minimum`` (booleans refused)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value
