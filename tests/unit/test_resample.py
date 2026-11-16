"""Complete, session-anchored and UTC-grid OHLCV aggregation."""

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.resample import resample_bars
from alpha_data.timeframe import DAILY, BarTimeframe


def bars(start: datetime, count: int, minutes: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [start + timedelta(minutes=i * minutes) for i in range(count)],
            "open": [100.0 + i for i in range(count)],
            "high": [102.0 + i for i in range(count)],
            "low": [99.0 + i for i in range(count)],
            "close": [101.0 + i for i in range(count)],
            "volume": [10.0] * count,
        }
    )


@pytest.mark.parametrize(
    ("source", "target", "count", "expected"), [(1, 5, 10, 2), (5, 60, 24, 2), (60, 1440, 48, 2)]
)
def test_crypto_grid(source: int, target: int, count: int, expected: int) -> None:
    start = datetime(2026, 3, 9, tzinfo=UTC)
    frame = bars(start, count, source)
    result = resample_bars(
        frame, source=BarTimeframe(source), target=BarTimeframe(target), calendar=None
    )
    n = target // source
    assert result.schema == frame.schema
    assert result.height == expected
    assert result["ts"].to_list() == [
        start + timedelta(minutes=i * target) for i in range(expected)
    ]
    assert result.row(0)[1:] == pytest.approx((100, 101 + n, 99, 100 + n, 10 * n))


@pytest.mark.parametrize(("day", "count", "expected"), [(9, 78, 7), (27, 42, 4)])
def test_stock_hour_and_daily(day: int, count: int, expected: int) -> None:
    start = datetime(2026, 3 if day == 9 else 11, day, 13 if day == 9 else 14, 30, tzinfo=UTC)
    frame = bars(start, count, 5)
    hourly = resample_bars(frame, source=BarTimeframe(5), target=BarTimeframe(60), calendar="XNYS")
    assert hourly.height == expected
    assert hourly["ts"][-1] == start + timedelta(hours=expected - 1)
    assert hourly["volume"][-1] == pytest.approx(60)
    daily = resample_bars(frame, source=BarTimeframe(5), target=BarTimeframe(1440), calendar="XNYS")
    assert daily["ts"].to_list() == [start.replace(hour=0, minute=0)]
    assert daily.row(0)[1:] == pytest.approx((100, 101 + count, 99, 100 + count, 10 * count))


def test_two_stock_sessions() -> None:
    frame = pl.concat([bars(datetime(2026, 3, day, 13, 30, tzinfo=UTC), 78, 5) for day in (9, 10)])
    result = resample_bars(
        frame, source=BarTimeframe(5), target=BarTimeframe(1440), calendar="XNYS"
    )
    assert result["ts"].to_list() == [datetime(2026, 3, day, tzinfo=UTC) for day in (9, 10)]


@pytest.mark.parametrize(("source", "target"), [(5, 7), (60, 5)])
def test_invalid_ratio(source: int, target: int) -> None:
    with pytest.raises(DataError):
        resample_bars(
            bars(datetime(2026, 3, 9, tzinfo=UTC), 10, source),
            source=BarTimeframe(source),
            target=BarTimeframe(target),
            calendar=None,
        )


def test_identity() -> None:
    frame = bars(datetime(2026, 3, 9, tzinfo=UTC), 2, 5)
    assert (
        resample_bars(frame, source=BarTimeframe(5), target=BarTimeframe(5), calendar=None) is frame
    )


def test_gap_names_bin_and_first_missing_start() -> None:
    start = datetime(2026, 3, 9, tzinfo=UTC)
    frame = bars(start, 24, 5).filter(pl.col("ts") != start + timedelta(minutes=15))
    with pytest.raises(DataError) as error:
        resample_bars(frame, source=BarTimeframe(5), target=BarTimeframe(60), calendar=None)
    assert str(start) in str(error.value)
    assert str(start + timedelta(minutes=15)) in str(error.value)


def test_entire_interior_bin_missing() -> None:
    start = datetime(2026, 3, 9, tzinfo=UTC)
    frame = pl.concat([bars(start, 12, 5), bars(start + timedelta(hours=2), 12, 5)])
    with pytest.raises(DataError, match="01:00:00"):
        resample_bars(frame, source=BarTimeframe(5), target=BarTimeframe(60), calendar=None)


def test_trailing_unknown_bin_dropped() -> None:
    start = datetime(2026, 3, 9, tzinfo=UTC)
    frame = bars(start, 14, 5)
    result = resample_bars(
        frame,
        source=BarTimeframe(5),
        target=BarTimeframe(60),
        calendar=None,
        known_by=start + timedelta(minutes=70),
    )
    assert result.height == 1
    # Without known_by the data's own end is the cutoff: the forming bin is dropped, not refused.
    unbounded = resample_bars(frame, source=BarTimeframe(5), target=BarTimeframe(60), calendar=None)
    assert unbounded.equals(result)


def test_truncated_stock_session_fails_loud() -> None:
    # 2026-03-09 (New York daylight time): open 13:30 UTC. Bars start at 14:30, so the
    # 13:30-14:30 bin of a session that has already closed is missing.
    late = bars(datetime(2026, 3, 9, 14, 30, tzinfo=UTC), 66, 5)
    with pytest.raises(DataError, match="incomplete bin"):
        resample_bars(
            late,
            source=BarTimeframe(5),
            target=BarTimeframe(60),
            calendar="XNYS",
            known_by=datetime(2026, 3, 10, tzinfo=UTC),
        )


def test_missing_whole_session_fails_loud() -> None:
    frame = pl.concat([bars(datetime(2026, 3, day, 13, 30, tzinfo=UTC), 78, 5) for day in (9, 11)])
    with pytest.raises(DataError, match="missing the whole 2026-03-10 session"):
        resample_bars(frame, source=BarTimeframe(5), target=DAILY, calendar="XNYS")


def test_extended_hours_refused() -> None:
    frame = bars(datetime(2026, 3, 9, 13, 25, tzinfo=UTC), 13, 5)
    with pytest.raises(DataError, match="resample regular-session bars only"):
        resample_bars(frame, source=BarTimeframe(5), target=BarTimeframe(60), calendar="XNYS")


@pytest.mark.bias_guard
@pytest.mark.parametrize("leaky", [False, True])
def test_resample_future_poison_with_leaky_control(leaky: bool) -> None:
    start = datetime(2026, 3, 9, tzinfo=UTC)
    frame = bars(start, 24, 5)

    def read(values: pl.DataFrame) -> pl.DataFrame:
        return resample_bars(
            values,
            source=BarTimeframe(5),
            target=BarTimeframe(60),
            calendar=None,
            known_by=None if leaky else start + timedelta(minutes=65),
        )

    before = read(frame)
    poisoned = frame.with_columns(
        pl.when(pl.col("ts") >= start + timedelta(hours=1))
        .then(999.0)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    if leaky:
        with pytest.raises(AssertionError):
            assert before.equals(read(poisoned))
    else:
        assert before.equals(read(poisoned))
        assert not before.equals(read(frame.with_columns((pl.col("high") + 1).alias("high"))))
