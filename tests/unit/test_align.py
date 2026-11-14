"""Higher-timeframe values become visible only upon their close."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.align import align_as_known
from alpha_data.timeframe import DAILY, BarTimeframe


def frame(stamps: list[datetime]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": stamps,
            **{
                name: [100.0 + i for i in range(len(stamps))]
                for name in ("open", "high", "low", "close", "volume")
            },
        }
    )


def test_daily_attaches_at_close_and_next_session() -> None:
    coarse = frame([datetime(2026, 3, day, tzinfo=UTC) for day in (9, 10)])
    fine = frame(
        [datetime(2026, 3, 9, 19, minute, tzinfo=UTC) for minute in (50, 55)]
        + [datetime(2026, 3, 10, 13, 30, tzinfo=UTC)]
    )
    result = align_as_known(
        fine, fine_timeframe=BarTimeframe(5), coarse=coarse, coarse_timeframe=DAILY, calendar="XNYS"
    )
    assert result.select(fine.columns).equals(fine)
    assert result["htf_ts"].to_list() == [None, coarse["ts"][0], coarse["ts"][0]]
    assert result["htf_known_at"].to_list() == [
        None,
        datetime(2026, 3, 9, 20, tzinfo=UTC),
        datetime(2026, 3, 9, 20, tzinfo=UTC),
    ]
    for col in ("open", "high", "low", "close", "volume"):
        assert result[f"htf_{col}"].to_list() == [None, 100.0, 100.0]


def test_crypto_hour() -> None:
    coarse = frame([datetime(2026, 3, 9, hour, tzinfo=UTC) for hour in (0, 1)])
    fine = frame([datetime(2026, 3, 9, 0, minute, tzinfo=UTC) for minute in (50, 55)])
    result = align_as_known(
        fine,
        fine_timeframe=BarTimeframe(5),
        coarse=coarse,
        coarse_timeframe=BarTimeframe(60),
        calendar=None,
        prefix="hour_",
    )
    assert result["hour_ts"].to_list() == [None, coarse["ts"][0]]


@pytest.mark.parametrize("hours", [(1, 0), (0, 0)])
def test_coarse_must_be_strictly_increasing(hours: tuple[int, int]) -> None:
    coarse = frame([datetime(2026, 3, 9, hour, tzinfo=UTC) for hour in hours])
    with pytest.raises(DataError, match="strictly increasing"):
        align_as_known(
            coarse,
            fine_timeframe=BarTimeframe(5),
            coarse=coarse,
            coarse_timeframe=BarTimeframe(60),
            calendar=None,
        )


@pytest.mark.bias_guard
@pytest.mark.parametrize("leaky", [False, True])
def test_alignment_future_poison_with_leaky_control(leaky: bool) -> None:
    coarse = frame([datetime(2026, 3, 9, hour, tzinfo=UTC) for hour in (0, 1)])
    fine = frame([datetime(2026, 3, 9, 1, 5, tzinfo=UTC)])

    def read(values: pl.DataFrame) -> pl.DataFrame:
        if leaky:
            return fine.join_asof(values, on="ts", strategy="backward", suffix="_coarse")
        return align_as_known(
            fine,
            fine_timeframe=BarTimeframe(5),
            coarse=values,
            coarse_timeframe=BarTimeframe(60),
            calendar=None,
        )

    before = read(coarse)
    poisoned = coarse.with_columns(
        pl.when(pl.col("ts") == coarse["ts"][1])
        .then(999.0)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    if leaky:
        with pytest.raises(AssertionError):
            assert before.equals(read(poisoned))
    else:
        assert before.equals(read(poisoned))
        assert not before.equals(read(coarse.with_columns((pl.col("close") + 1).alias("close"))))
