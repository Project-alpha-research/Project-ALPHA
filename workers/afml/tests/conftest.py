"""Pytest fixtures over :mod:`shared_fixtures`: the chapter-4 example and synthetic bars."""

from __future__ import annotations

import polars as pl
import pytest
from shared_fixtures import daily_ts, synthetic_daily_bars


@pytest.fixture
def chapter4() -> tuple[pl.Series, pl.DataFrame]:
    """AFML chapter 4 example: six bars, labels spanning bars [0, 2], [2, 3] and [4, 5]."""
    ts = daily_ts(6)
    spans = pl.DataFrame({"start": ts.gather([0, 2, 4]), "end": ts.gather([2, 3, 5])})
    return ts, spans


@pytest.fixture(scope="session")
def daily_bars() -> pl.DataFrame:
    """600 seeded synthetic daily bars (no market data is committed)."""
    return synthetic_daily_bars()
