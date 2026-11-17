"""Daily USD-M settlements, assigned by the UTC instant they became known."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from alpha_core import DataError
from alpha_data.context.binance_bulk import table_path
from alpha_data.context.events import FUNDING_SCHEMA, load_events

SCHEMA = {
    "date": pl.Date,
    "symbol": pl.String,
    "funding_sum": pl.Float64,
    "funding_last": pl.Float64,
    "funding_count": pl.UInt32,
}
RESERVED_DAY = date(2024, 1, 1)


def daily_funding_with_sources(
    data_dir: Path, symbols: Sequence[str], start: date, end: date
) -> tuple[pl.DataFrame, dict[str, str]]:
    """Inclusive days; reject reserved rows anywhere in each table read, before slicing."""
    if start > end:
        raise DataError("funding start must not follow end")
    if end >= RESERVED_DAY:
        raise DataError("funding range reaches reserved window")
    frames: list[pl.DataFrame] = []
    sources: dict[str, str] = {}
    for symbol in sorted(set(symbols)):
        path = table_path(data_dir, "funding", symbol)
        if not path.exists() and not path.with_suffix(".json").exists():
            continue  # No perpetual table: absence stays absence, never zero.
        raw = path.read_bytes()
        frame = load_events(path, source="binance", schema=FUNDING_SCHEMA)
        if raw != path.read_bytes():
            raise DataError("funding table changed during verified read")
        if (
            frame["symbol"].null_count()
            or frame.filter(pl.col("symbol") != symbol).height
            or frame["funding_rate"].null_count()
            or frame["funding_time"].null_count()
            or frame["known_from"].is_duplicated().any()
            or not frame["known_from"].is_sorted()
        ):
            raise DataError("invalid or disordered funding settlements")
        # UTC [d 00:00, (d+1) 00:00): 00:00:00.008 belongs to the NEW day.
        frame = frame.with_columns(pl.col("known_from").dt.date().alias("date"))
        if frame.filter(pl.col("date") >= RESERVED_DAY).height:
            raise DataError("funding table reaches reserved window")
        sources[symbol] = hashlib.sha256(raw).hexdigest()
        frames.append(
            frame.filter(pl.col("date").is_between(start, end))
            .group_by("date", "symbol")
            .agg(
                pl.col("funding_rate").sum().alias("funding_sum"),
                pl.col("funding_rate").last().alias("funding_last"),
                pl.len().alias("funding_count"),
            )
        )
    return (
        pl.concat(frames).sort("date", "symbol") if frames else pl.DataFrame(schema=SCHEMA),
        sources,
    )


def daily_funding(data_dir: Path, symbols: Sequence[str], start: date, end: date) -> pl.DataFrame:
    return daily_funding_with_sources(data_dir, symbols, start, end)[0]
