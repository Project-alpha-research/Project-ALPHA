"""Synthetic homes for the published-factor check: a run, its bar store and a factor file.

The factor file is written in the source's real layout (wide percent file mapped by
``osap_portfolios.map_returns`` and stored with ``store_events``). A strategy is built so that
its compounded calendar-month returns equal a chosen series exactly.
"""

import io
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from alpha_data.adapters.base import DatasetIdentity, FetchReceipt
from alpha_data.context import osap_catalogue, osap_portfolios
from alpha_data.context.events import store_events
from alpha_data.store import ParquetStore
from tests.unit.test_spine_tools import RUN

FIXED = {
    "Mom12m": 1993,
    "STreversal": 1990,
    "Size": 1981,
    "BM": 1980,
    "Beta": 1973,
    "OperProf": 2006,
    "AssetGrowth": 2008,
}
EXTRA = {f"Other{i:02d}": 2000 + i for i in range(9)}
RELEASE = "2026.10"
RELEASED = date(2026, 10, 27)
FIRST = date(2012, 1, 2)
LAST = date(2024, 3, 29)


def month_end(day: date) -> date:
    return osap_portfolios.month_end(day)


def trading_days(first: date = FIRST, last: date = LAST) -> list[date]:
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    return [d for d in days if d.weekday() < 5]


def month_ends(first: date = FIRST, last: date = LAST) -> list[date]:
    return sorted({month_end(d) for d in trading_days(first, last)})


def factor_returns(
    seed: int = 11, first: date = FIRST, last: date = LAST
) -> dict[str, dict[date, float]]:
    """Decimal monthly long-short returns per signal, independent normal draws."""
    rng = np.random.default_rng(seed)
    months = month_ends(first, last)
    names = [*FIXED, *EXTRA]
    return {
        name: dict(zip(months, rng.normal(0.004, 0.04, len(months)).tolist(), strict=True))
        for name in names
    }


def write_factor_file(
    home: Path,
    series: Mapping[str, Mapping[date, float]],
    *,
    release: str = RELEASE,
    released: date = RELEASED,
) -> None:
    months = sorted({m for values in series.values() for m in values})
    columns: dict[str, list[float | None]] = {
        name: [None if m not in values else values[m] * 100.0 for m in months]
        for name, values in series.items()
    }
    frame = pl.DataFrame({"date": months, **columns}, schema_overrides={"date": pl.Date})
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    docs = [
        osap_catalogue.SignalDoc(
            acronym=name,
            short_name=name,
            kind="Predictor",
            authors="Synthetic",
            year=FIXED.get(name, EXTRA.get(name)),
            journal=None,
            data_category="Price",
            category="synthetic",
            sample_start=None,
            sample_end=None,
            sign=None,
        )
        for name in series
    ]
    table = osap_portfolios.map_returns(buffer.getvalue(), docs, release=release, released=released)
    path = osap_portfolios.table_path(home, release)
    store_events(
        path,
        table,
        {"source": osap_portfolios.SOURCE, "fetched_at": "2026-11-19T00:00:00+00:00"},
        schema=osap_portfolios.SCHEMA,
    )


def days_of(kind: str, first: date, last: date) -> list[date]:
    """Weekdays (default), real XNYS sessions, or every calendar day (a 24/7 market)."""
    if kind == "sessions":
        from alpha_data.sessions import sessions_between

        return sessions_between("XNYS", first, last)
    if kind == "everyday":
        return [first + timedelta(days=i) for i in range((last - first).days + 1)]
    return trading_days(first, last)


def write_bars(
    home: Path, days: list[date], identity: DatasetIdentity | None, source: str = "alpaca"
) -> None:
    stamps = [datetime(d.year, d.month, d.day, tzinfo=UTC) for d in days]
    bars = pl.DataFrame(
        {
            "ts": stamps,
            "open": [100.0] * len(days),
            "high": [101.0] * len(days),
            "low": [99.0] * len(days),
            "close": [100.0] * len(days),
            "volume": [1000.0] * len(days),
        }
    )
    path = home / "store" / "bars" / "SYN.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(path)
    store = ParquetStore(home / "store")
    if identity is None:
        folder = home / "store" / "provenance"
        folder.mkdir(parents=True, exist_ok=True)
        legacy = {"adapter_version": "1", "parser_version": "1", "source": source}
        (folder / "SYN.json").write_text(json.dumps(legacy))
        return
    receipt = FetchReceipt(
        receipt_id="a" * 32,
        requested_start=days[0],
        requested_end=days[-1],
        fetched_at=datetime(2026, 11, 1, tzinfo=UTC),
        adapter_version="1",
        parser_version="1",
        response_sha256="b" * 64,
        response_bytes=1,
        row_count=len(days),
        action_count=0,
        request_metadata=(),
    )
    store.write_provenance(
        "SYN",
        source=source,
        adapter_version="1",
        parser_version="1",
        identity=identity,
        receipt=receipt,
    )


US_STOCK = DatasetIdentity(
    symbol="SYN",
    provider="alpaca",
    provider_symbol="SYN",
    venue="US",
    asset_class="stock",
    timeframe="1D",
    calendar="XNYS",
    currency="USD",
    price_basis="raw",
)
CRYPTO = replace(US_STOCK, asset_class="crypto", calendar="24x7", venue="BINANCE")


def write_run(
    home: Path,
    monthly: Mapping[date, float],
    *,
    first: date = FIRST,
    last: date = LAST,
    identity: DatasetIdentity | None = US_STOCK,
    bar_first: date = FIRST,
    run_id: str = RUN,
    calendar: str = "weekdays",
    source: str = "alpaca",
) -> list[date]:
    """A run whose daily equity compounds to ``monthly`` in each full month; returns its days."""
    bar_days = days_of(calendar, bar_first, last)
    write_bars(home, bar_days, identity, source)
    days = days_of(calendar, first, last)
    steps: dict[tuple[int, int], int] = {}
    for day in days[:-1]:
        steps[(day.year, day.month)] = steps.get((day.year, day.month), 0) + 1
    equity = [1.0]
    for day in days[:-1]:
        target = monthly.get(month_end(day), 0.0)
        equity.append(equity[-1] * (1.0 + target) ** (1.0 / steps[(day.year, day.month)]))
    stamps = [datetime(d.year, d.month, d.day, tzinfo=UTC) for d in days]
    folder = home / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {
        "metadata": {
            "symbol": "SYN",
            "last_ts": stamps[-1].isoformat(),
            "periods_per_year": 252,
        },
        "spine": {"store": "home", "labels": [], "test_id": "t1", "name": "synthetic"},
        "source_fingerprint": "synthetic",
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    (folder / "spec.json").write_text("{}")
    pl.DataFrame({"ts": stamps, "equity": equity}).write_parquet(folder / "equity_curve.parquet")
    return days


def planted_home(
    home: Path,
    *,
    weights: Mapping[str, float] | None = None,
    noise: float = 0.002,
    seed: int = 1,
    series: dict[str, dict[date, float]] | None = None,
    file_series: dict[str, dict[date, float]] | None = None,
    first: date = FIRST,
    last: date = LAST,
    identity: DatasetIdentity | None = US_STOCK,
) -> dict[str, dict[date, float]]:
    """A home where the strategy's month is sum(weight * factor) plus small normal noise."""
    factors = series if series is not None else factor_returns()
    write_factor_file(home, file_series if file_series is not None else factors)
    rng = np.random.default_rng(seed)
    months = month_ends()
    wanted = weights or {}
    monthly = {
        m: sum(w * factors[name][m] for name, w in wanted.items()) + float(rng.normal(0.0, noise))
        for m in months
    }
    write_run(home, monthly, first=first, last=last, identity=identity)
    return factors
