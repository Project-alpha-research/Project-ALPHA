"""Align higher-timeframe bars by their availability, never their interval starts."""

from __future__ import annotations

import polars as pl

from alpha_core import DataError
from alpha_data.sessions import bar_known_at
from alpha_data.timeframe import BarTimeframe


def align_as_known(
    fine: pl.DataFrame,
    *,
    fine_timeframe: BarTimeframe,
    coarse: pl.DataFrame,
    coarse_timeframe: BarTimeframe,
    calendar: str | None,
    prefix: str = "htf_",
) -> pl.DataFrame:
    """Attach the latest fully known coarse OHLCV to each fine bar's close."""
    coarse_known = [
        bar_known_at(ts, timeframe=coarse_timeframe, calendar=calendar)
        for ts in coarse["ts"].to_list()
    ]
    if any(right <= left for left, right in zip(coarse_known, coarse_known[1:], strict=False)):
        raise DataError("coarse known-at values must be strictly increasing")
    fine_known = [
        bar_known_at(ts, timeframe=fine_timeframe, calendar=calendar) for ts in fine["ts"].to_list()
    ]
    known_column = f"{prefix}known_at"
    columns = ["ts", "open", "high", "low", "close", "volume"]
    attached = [f"{prefix}{column}" for column in columns] + [known_column]
    if set(fine.columns) & set(attached):
        raise DataError(f"alignment prefix {prefix!r} collides with fine columns")
    # Pick private join/order names that cannot shadow input or output columns.
    key = "_fine_known_at"
    while key in fine.columns or key in attached:
        key = "_" + key
    order = key + "_order"
    while order in fine.columns or order in attached:
        order = "_" + order
    dtype = pl.Datetime("us", "UTC")
    left = fine.with_columns(pl.Series(key, fine_known, dtype=dtype)).with_row_index(order)
    right = coarse.select(columns).rename({column: f"{prefix}{column}" for column in columns})
    right = right.with_columns(pl.Series(known_column, coarse_known, dtype=dtype))
    return (
        left.sort(key)
        .join_asof(right, left_on=key, right_on=known_column, strategy="backward")
        .sort(order)
        .drop(key, order)
    )
