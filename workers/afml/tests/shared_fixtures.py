"""Shared fixture data: the bar grid builders, the real SPY slice path and the one seed."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

FIXTURES = Path(__file__).parent / "fixtures"
SEED = 20261116


def daily_ts(n: int) -> pl.Series:
    """``n`` consecutive daily UTC timestamps (weekends are irrelevant to bar positions)."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.Series(
        "ts", [start + timedelta(days=i) for i in range(n)], dtype=pl.Datetime("us", "UTC")
    )


def make_bars(
    opens: Sequence[float], highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": daily_ts(len(closes)),
            "open": list(map(float, opens)),
            "high": list(map(float, highs)),
            "low": list(map(float, lows)),
            "close": list(map(float, closes)),
        }
    )
