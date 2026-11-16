"""Shared fixture data: bar builders, a seeded synthetic daily series and the one seed.

No market data is committed: real-data runs happen outside git (owner/afml).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

SEED = 20261116


def weekday_ts(n: int) -> pl.Series:
    """``n`` consecutive weekday UTC timestamps from 2020-01-01."""
    days, day = [], datetime(2020, 1, 1, tzinfo=UTC)
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return pl.Series("ts", days, dtype=pl.Datetime("us", "UTC"))


def synthetic_daily_bars(n: int = 600, seed: int = SEED) -> pl.DataFrame:
    """A seeded random walk shaped like a liquid stock's daily bars.

    About 1.1% daily volatility with calmer and wilder stretches, overnight gaps (a few of 3-4%),
    and intraday ranges around each open-close body. Deterministic for a given seed.
    """
    rng = np.random.default_rng(seed)
    regime = np.repeat(rng.choice([0.007, 0.011, 0.018], size=n // 50 + 1), 50)[:n]
    overnight = rng.normal(0.0, 0.003, n)
    shocks = rng.choice(n, size=6, replace=False)
    overnight[shocks] += rng.choice([-1.0, 1.0], 6) * rng.uniform(0.03, 0.04, 6)
    intraday = rng.normal(0.0003, 1.0, n) * regime
    close = np.empty(n)
    opens = np.empty(n)
    prev = 100.0
    for t in range(n):
        opens[t] = prev * np.exp(overnight[t])
        close[t] = opens[t] * np.exp(intraday[t])
        prev = close[t]
    body_hi, body_lo = np.maximum(opens, close), np.minimum(opens, close)
    high = body_hi * np.exp(np.abs(rng.normal(0.0, 0.5, n)) * regime)
    low = body_lo * np.exp(-np.abs(rng.normal(0.0, 0.5, n)) * regime)
    return pl.DataFrame(
        {"ts": weekday_ts(n), "open": opens, "high": high, "low": low, "close": close}
    )


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
