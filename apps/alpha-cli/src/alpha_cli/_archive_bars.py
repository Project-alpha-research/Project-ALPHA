"""Adapt verified archive chart datasets to the backtest's pair-symbol bar feed."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from alpha_cli import _chart_data, _runner
from alpha_cli.spine import reserve
from alpha_core import Bar, DataError
from alpha_data.crypto.storage import CryptoBulkStore
from alpha_data.resample import resample_bars
from alpha_data.timeframe import DAILY, BarTimeframe, parse_timeframe


def hold_archive(
    store: CryptoBulkStore, manifest_id: str, symbol: str, as_of: str | None
) -> reserve.Hold:
    """The cut-off for an archive read: it ends where the reserved day starts.

    A bar is known when it closes, so the last bar of the day before is kept. The user's own
    earlier cut-off wins and holds nothing back. The count reads timestamps only.
    """
    user = _runner.parse_cutoff(as_of)
    if user is not None and user <= reserve.RESERVED_INSTANT:
        return reserve.Hold(user, as_of, 0)
    held = _chart_data.held_back_chart_rows(
        store, manifest_id, symbol=symbol, start=reserve.RESERVED_INSTANT, until=user
    )
    return reserve.Hold(reserve.RESERVED_INSTANT, reserve.CUTOFF_DATE if held else as_of, held)


def load_archive_bars(
    store: CryptoBulkStore,
    manifest_id: str,
    *,
    symbol: str,
    timeframe: BarTimeframe = DAILY,
    source_timeframe: BarTimeframe | None = None,
    as_of: datetime | None = None,
) -> list[Bar]:
    """Verify the group, enforce its stored frequency, and preserve its base/quote identity."""
    bars, _provenance = _chart_data.load_chart_dataset(
        store, manifest_id, symbol=symbol, as_of=as_of
    )
    dataset = next(
        (
            row
            for row in _chart_data.chart_datasets(store)
            if row["manifest_id"] == manifest_id
            or (isinstance(row["manifest_ids"], list) and manifest_id in row["manifest_ids"])
        ),
        None,
    )
    if dataset is None:
        raise DataError("archive dataset identity is unavailable")
    if any(
        dataset.get(key) != value
        for key, value in {
            "provider": "binance",
            "venue": "binance",
            "family": "market_bars",
            "market_type": "spot",
        }.items()
    ):
        raise DataError("backtest archives require Binance spot market_bars")
    stored = source_timeframe or timeframe
    if parse_timeframe(str(dataset["frequency"])) != stored:
        raise DataError(
            f"archive frequency {dataset['frequency']} differs from stored timeframe "
            f"{stored.canonical}"
        )
    if timeframe < stored or timeframe.minutes % stored.minutes:
        raise DataError(f"cannot resample {stored.canonical} to {timeframe.canonical}")
    base, quote = dataset.get("base_asset"), dataset.get("quote_asset")
    if not isinstance(base, str) or not base or not isinstance(quote, str) or not quote:
        raise DataError("archive dataset requires base_asset and quote_asset")
    pair = f"{base}/{quote}"
    if timeframe != stored and bars:
        frame = pl.DataFrame([bar.model_dump(exclude={"symbol"}) for bar in bars])
        frame = resample_bars(frame, source=stored, target=timeframe, calendar=None, known_by=as_of)
        bars = [Bar(symbol=pair, **row) for row in frame.iter_rows(named=True)]
    else:
        bars = [bar.model_copy(update={"symbol": pair}) for bar in bars]
    return bars
