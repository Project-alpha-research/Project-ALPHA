"""Binance funding and metrics are invisible before their settlement or window end."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from alpha_data.context.binance_bulk import map_binance_csv
from alpha_data.context.events import as_known_events

pytestmark = pytest.mark.bias_guard

FIX = Path(__file__).parents[1] / "fixtures/context/binance"


def test_funding_known_at_settlement_not_before() -> None:
    df = map_binance_csv("funding", (FIX / "funding_2024-01.csv").read_bytes())
    assert as_known_events(df, as_of=datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC)).is_empty()
    assert as_known_events(df, as_of=datetime(2024, 1, 1, tzinfo=UTC)).height == 1


def test_metrics_wait_five_minutes_after_their_stamp() -> None:
    df = map_binance_csv("metrics", (FIX / "metrics_2024-01-02.csv").read_bytes())
    assert as_known_events(df, as_of=datetime(2024, 1, 2, 0, 4, 59, tzinfo=UTC)).is_empty()
    assert as_known_events(df, as_of=datetime(2024, 1, 2, 0, 5, tzinfo=UTC)).height == 1


def test_future_rows_never_change_an_earlier_read() -> None:
    df = map_binance_csv("funding", (FIX / "funding_2024-01.csv").read_bytes())
    cutoff = datetime(2024, 1, 1, 1, tzinfo=UTC)
    poisoned = df.with_columns(
        pl.when(pl.col("known_from") > cutoff)
        .then(1e100)
        .otherwise(pl.col("funding_rate"))
        .alias("funding_rate")
    )
    assert as_known_events(df, as_of=cutoff).equals(as_known_events(poisoned, as_of=cutoff))
    # Leaky control: the same poison must show up once the cutoff passes it.
    later = datetime(2024, 1, 2, tzinfo=UTC)
    assert not as_known_events(df, as_of=later).equals(as_known_events(poisoned, as_of=later))
