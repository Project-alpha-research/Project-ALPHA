"""Synthetic builders for the context attach tests. No real values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_core.reserve import RESERVED_DAY
from alpha_data.context import cftc_cot, finra_short
from alpha_data.context.events import store_events

CUTOFF = datetime.combine(RESERVED_DAY, time.min, tzinfo=UTC) - timedelta(microseconds=1)
CODE = "13874A"


def weekly(start: date, count: int) -> list[date]:
    return [start + timedelta(weeks=n) for n in range(count)]


def daily(start: date, count: int) -> list[date]:
    return [start + timedelta(days=n) for n in range(count)]


def cot_rows(specs: Sequence[Mapping[str, Any]]) -> pl.DataFrame:
    """One COT row per spec: report_date, nl, ns, cl, cs, oi, known_from, basis (all optional)."""
    rows = []
    for spec in specs:
        period: date = spec["report_date"]
        # From 2022-09 a stamp at the rule time: the derived series take it as it is.
        default_basis = "rule-only-era" if period < cftc_cot.RULE_ONLY_BEFORE else "stamp"
        rows.append(
            dict(
                market_code=CODE,
                market_name="SYNTHETIC",
                report_date=period,
                open_interest=spec.get("oi", 1000),
                noncomm_long=spec.get("nl", 0),
                noncomm_short=spec.get("ns", 0),
                noncomm_spread=0,
                comm_long=spec.get("cl", 0),
                comm_short=spec.get("cs", 0),
                nonrept_long=0,
                nonrept_short=0,
                known_from=spec.get("known_from", cftc_cot.known_from(period)),
                known_basis=spec.get("basis", default_basis),
            )
        )
    return pl.DataFrame(rows, schema=cftc_cot.SCHEMA)


def finra_rows(symbol: str, items: Sequence[tuple[date, float]]) -> pl.DataFrame:
    """One row per (trade_date, short/total ratio); total volume is 1000."""
    rows = [
        dict(
            symbol=symbol,
            trade_date=day,
            short_volume=ratio * 1000.0,
            short_exempt_volume=0.0,
            total_volume=1000.0,
            markets="N",
            known_from=finra_short.known_from(day),
        )
        for day, ratio in items
    ]
    return pl.DataFrame(rows, schema=finra_short.SCHEMA)


def _meta(source: str) -> dict[str, Any]:
    return {"source": source, "fetched_at": "2026-01-01T00:00:00+00:00"}


def store_cot(data_dir: Path, df: pl.DataFrame, code: str = CODE) -> None:
    path = cftc_cot.table_path(data_dir, code)
    store_events(path, df, _meta(cftc_cot.SOURCE), schema=cftc_cot.SCHEMA)


def store_finra(data_dir: Path, df: pl.DataFrame, symbol: str) -> None:
    path = finra_short.table_path(data_dir, symbol)
    store_events(path, df, _meta(finra_short.SOURCE), schema=finra_short.SCHEMA)


def bars(days: Sequence[date]) -> pl.DataFrame:
    stamps = [datetime.combine(day, time.min, tzinfo=UTC) for day in days]
    return pl.DataFrame(
        dict(ts=stamps, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0),
        schema=dict(
            ts=pl.Datetime("us", "UTC"),
            open=pl.Float64,
            high=pl.Float64,
            low=pl.Float64,
            close=pl.Float64,
            volume=pl.Float64,
        ),
    )


def approx(value: float) -> Any:
    return pytest.approx(value, rel=1e-9, abs=1e-12)
