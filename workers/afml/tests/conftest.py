"""Pytest fixtures over :mod:`shared_fixtures`: the chapter-4 example and real SPY bars."""

from __future__ import annotations

import polars as pl
import pytest
from shared_fixtures import FIXTURES, daily_ts


@pytest.fixture
def chapter4() -> tuple[pl.Series, pl.DataFrame]:
    """AFML chapter 4 example: six bars, labels spanning bars [0, 2], [2, 3] and [4, 5]."""
    ts = daily_ts(6)
    spans = pl.DataFrame({"start": ts.gather([0, 2, 4]), "end": ts.gather([2, 3, 5])})
    return ts, spans


@pytest.fixture(scope="session")
def spy_bars() -> pl.DataFrame:
    """501 real daily SPY bars, 2022-2023, copied once from ALPHA's Alpaca store."""
    return pl.read_parquet(FIXTURES / "spy_daily_2022_2023.parquet")
