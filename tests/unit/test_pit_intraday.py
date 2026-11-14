"""Intraday completion firewall and exchange-local corporate-action clocks."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_core import ActionType, CorporateAction, DataError
from alpha_data.pit import PointInTimeReader
from alpha_data.source import PointInTimeSource
from alpha_data.store import ParquetStore
from alpha_data.timeframe import DAILY, BarTimeframe
from tests.fixtures.cli_fixtures import seed_store


def frame(stamps: list[datetime]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": stamps,
            "open": [100.0] * len(stamps),
            "high": [101.0] * len(stamps),
            "low": [99.0] * len(stamps),
            "close": [100.0] * len(stamps),
            "volume": [1000.0] * len(stamps),
        }
    )


def test_five_minute_firewall_and_typed_source(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    start = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    stamps = [start + timedelta(minutes=5 * i) for i in range(8)]
    store.write_bars("SPY", frame(stamps))
    when = datetime.fromisoformat("2026-03-09T10:02:00-04:00")
    reader = PointInTimeReader(store, {}, timeframe=BarTimeframe(5), calendar="XNYS")
    assert reader.as_of("SPY", when)["ts"].to_list() == stamps[:6]
    source = PointInTimeSource(store, {}, timeframe=BarTimeframe(5), calendar="XNYS")
    assert [bar.ts for bar in source.as_of("SPY", when)] == stamps[:6]
    with pytest.raises(DataError, match="timezone-aware"):
        reader.as_of("SPY", when.replace(tzinfo=None))
    with pytest.raises(DataError, match="timezone-aware"):
        reader.dividends_as_of("SPY", when.replace(tzinfo=None))


def test_split_and_dividend_use_local_date(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    stamps = [datetime(2026, 11, 3, 0, 30, tzinfo=UTC), datetime(2026, 11, 3, 14, 30, tzinfo=UTC)]
    store.write_bars("SPY", frame(stamps))
    split = CorporateAction(
        symbol="SPY", action_type=ActionType.SPLIT, ex_date=date(2026, 11, 3), ratio=2.0
    )
    dividend = CorporateAction(
        symbol="SPY",
        action_type=ActionType.DIVIDEND,
        ex_date=date(2026, 11, 4),
        announce_date=date(2026, 11, 3),
        amount=1.0,
    )
    reader = PointInTimeReader(
        store, {"SPY": [split, dividend]}, timeframe=BarTimeframe(5), calendar="XNYS"
    )
    before = datetime(2026, 11, 3, 1, tzinfo=UTC)
    assert reader.as_of("SPY", before)["close"].to_list() == pytest.approx([100])
    assert reader.dividends_as_of("SPY", before) == []
    after = datetime(2026, 11, 3, 15, tzinfo=UTC)
    adjusted = reader.as_of("SPY", after)
    assert adjusted["close"].to_list() == pytest.approx([50, 100])
    assert adjusted["volume"].to_list() == pytest.approx([2000, 1000])
    assert reader.dividends_as_of("SPY", after) == [dividend]


def test_daily_fixture_unchanged(tmp_path: Path) -> None:
    seed_store(tmp_path, n=30)
    store = ParquetStore(tmp_path / "store")
    cutoff = datetime(2020, 1, 10, tzinfo=UTC)
    expected = store.read_bars("SPY").filter(pl.col("ts") <= cutoff)
    assert PointInTimeReader(store, {}).as_of("SPY", cutoff).equals(expected)
    assert (
        PointInTimeReader(store, {}, timeframe=DAILY, calendar="XNYS")
        .as_of("SPY", cutoff)
        .equals(expected)
    )


@pytest.mark.bias_guard
@pytest.mark.parametrize("leaky", [False, True])
def test_intraday_future_poison_with_leaky_control(tmp_path: Path, leaky: bool) -> None:
    store = ParquetStore(tmp_path)
    start = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    original = frame([start + timedelta(minutes=5 * i) for i in range(8)])
    store.write_bars("SPY", original)
    cutoff = start + timedelta(minutes=32)
    reader = PointInTimeReader(store, {}, timeframe=BarTimeframe(5), calendar="XNYS")

    def read() -> pl.DataFrame:
        return (
            store.read_bars("SPY").filter(pl.col("ts") <= cutoff)
            if leaky
            else reader.as_of("SPY", cutoff)
        )

    before = read()
    poisoned = original.with_columns(
        pl.when(pl.col("ts") + timedelta(minutes=5) > cutoff)
        .then(999.0)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    store.write_bars("SPY", poisoned)
    after = read()
    if leaky:
        with pytest.raises(AssertionError):
            assert before.equals(after)
    else:
        assert before.equals(after)
        store.write_bars("SPY", original.with_columns((pl.col("close") + 1).alias("close")))
        assert not before.equals(read())


def test_crypto_local_gate_uses_utc_and_loader_propagates_intraday_clock(
    tmp_path: Path,
) -> None:
    from alpha_cli._runner import load_bars, load_dividends

    store = ParquetStore(tmp_path / "store-5m")
    start = datetime(2026, 11, 3, 0, 30, tzinfo=UTC)
    store.write_bars("BTC/USD", frame([start, start + timedelta(minutes=5)]))
    dividend = CorporateAction(
        symbol="BTC/USD",
        action_type=ActionType.DIVIDEND,
        ex_date=date(2026, 11, 4),
        announce_date=date(2026, 11, 3),
        amount=1.0,
    )
    store.write_actions("BTC/USD", [dividend])
    cutoff = datetime(2026, 11, 3, 1, tzinfo=UTC)
    assert load_dividends("BTC/USD", data_dir=tmp_path, timeframe="5m", as_of=cutoff) == [dividend]
    result, _ = load_bars("BTC/USD", data_dir=tmp_path, timeframe="5m", as_of=cutoff)
    assert len(result) == 2
    with pytest.raises(DataError, match="incompatible"):
        load_bars("BTC/USD", data_dir=tmp_path, timeframe="5m", session="regular")

    store.write_actions("SPY", [dividend.model_copy(update={"symbol": "SPY"})])
    assert load_dividends("SPY", data_dir=tmp_path, timeframe="5m", as_of=cutoff) == []


def test_invalid_future_bar_cannot_break_intraday_typed_read(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    start = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    values = frame([start, start + timedelta(minutes=5)]).with_columns(
        pl.when(pl.col("ts") > start).then(float("nan")).otherwise(pl.col("close")).alias("close")
    )
    store.write_bars("SPY", values)
    source = PointInTimeSource(store, {}, timeframe=BarTimeframe(5), calendar="XNYS")
    assert len(source.as_of("SPY", start + timedelta(minutes=5))) == 1
    with pytest.raises(DataError, match="invalid bar.*SPY"):
        source.as_of("SPY", start + timedelta(minutes=10))
