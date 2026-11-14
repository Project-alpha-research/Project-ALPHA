"""Intraday point-in-time reads: poisoning anything not yet known at the cutoff changes nothing.

A stored bar's ``ts`` is its interval START; an intraday bar is known only at ``ts + duration``.
The reader, the resampler and the multi-timeframe alignment must each return identical output at
a cutoff whether the bars not yet known then are clean or absurd. Each guard has a leaky twin
(a deliberately wrong filter) that must FAIL the same comparison, so the guard can discriminate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_data.align import align_as_known
from alpha_data.pit import PointInTimeReader
from alpha_data.resample import resample_bars
from alpha_data.sessions import filter_session
from alpha_data.store import ParquetStore
from alpha_data.timeframe import DAILY, parse_timeframe

pytestmark = pytest.mark.bias_guard

_FIVE = parse_timeframe("5m")
_HOUR = parse_timeframe("1h")
_POISON = 9.9e9
_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "ts": pl.Datetime(time_zone="UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}


def _session_bars(day: datetime, n: int = 78) -> list[dict[str, object]]:
    """``n`` regular-session 5m bars from 14:30 UTC (09:30 New York, standard time)."""
    rows = []
    for i in range(n):
        price = 100.0 + i * 0.25 + (day.day % 7)
        rows.append(
            {
                "ts": day + timedelta(minutes=5 * i),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.5,
                "volume": 1_000.0 + i,
            }
        )
    return rows


def _frame() -> pl.DataFrame:
    # 2026-11-16 (Mon) and 2026-11-17 (Tue); New York is UTC-5 in November.
    rows = _session_bars(datetime(2026, 11, 16, 14, 30, tzinfo=UTC))
    rows += _session_bars(datetime(2026, 11, 17, 14, 30, tzinfo=UTC))
    return pl.DataFrame(rows, schema=_SCHEMA)


def _poison_unknown(frame: pl.DataFrame, when: datetime, duration: timedelta) -> pl.DataFrame:
    """Every bar not known at ``when`` (``ts + duration > when``) gets absurd prices."""
    unknown = pl.col("ts") + pl.duration(seconds=int(duration.total_seconds())) > when
    return frame.with_columns(
        [
            pl.when(unknown).then(pl.lit(_POISON)).otherwise(pl.col(c)).alias(c)
            for c in _SCHEMA
            if c != "ts"
        ]
    )


# 11:02 New York on the second session: the 10:55 bar is known (closes 11:00), 11:00 is not.
_WHEN = datetime(2026, 11, 17, 16, 2, tzinfo=UTC)


def _read(store: ParquetStore) -> pl.DataFrame:
    return PointInTimeReader(store, actions={}, timeframe=_FIVE, calendar="XNYS").as_of("S", _WHEN)


def test_intraday_reader_ignores_bars_not_yet_closed(tmp_path: Path) -> None:
    clean = _frame()
    store = ParquetStore(tmp_path)
    store.write_bars("S", clean)
    baseline = _read(store)
    store.write_bars("S", _poison_unknown(clean, _WHEN, _FIVE.duration))
    assert baseline.equals(_read(store))
    # the last visible bar is the one that CLOSED by the cutoff, not the one that opened before it
    assert baseline["ts"].max() == datetime(2026, 11, 17, 15, 55, tzinfo=UTC)


def test_leaky_twin_open_time_filter_is_caught() -> None:
    """Filtering on bar START (``ts <= when``) would let the still-forming 11:00 bar through."""
    clean = _frame()
    poisoned = _poison_unknown(clean, _WHEN, _FIVE.duration)

    def leaky(frame: pl.DataFrame) -> pl.DataFrame:
        return frame.filter(pl.col("ts") <= _WHEN)

    assert not leaky(clean).equals(leaky(poisoned))


def _hourly(frame: pl.DataFrame, when: datetime) -> pl.DataFrame:
    regular = filter_session(frame, timeframe=_FIVE, calendar="XNYS", scope="regular")
    known = regular.filter(pl.col("ts") + pl.duration(minutes=5) <= when)
    return resample_bars(known, source=_FIVE, target=_HOUR, calendar="XNYS", known_by=when)


def test_resampler_drops_the_forming_bin_and_ignores_unknown_bars() -> None:
    clean = _frame()
    baseline = _hourly(clean, _WHEN)
    assert baseline.equals(_hourly(_poison_unknown(clean, _WHEN, _FIVE.duration), _WHEN))
    # 09:30 and 10:30 bins of the second session are complete at 11:02; the 10:30-11:30 bin is not
    second = baseline.filter(pl.col("ts") >= datetime(2026, 11, 17, tzinfo=UTC))
    assert second["ts"].to_list() == [datetime(2026, 11, 17, 14, 30, tzinfo=UTC)]


def test_leaky_twin_resampler_without_known_by_is_caught() -> None:
    """Resampling every stored bar and keeping bins that merely STARTED by the cutoff leaks."""
    clean = _frame()
    poisoned = _poison_unknown(clean, _WHEN, _FIVE.duration)

    def leaky(frame: pl.DataFrame) -> pl.DataFrame:
        regular = filter_session(frame, timeframe=_FIVE, calendar="XNYS", scope="regular")
        full = resample_bars(regular, source=_FIVE, target=_HOUR, calendar="XNYS")
        return full.filter(pl.col("ts") <= _WHEN)

    assert not leaky(clean).equals(leaky(poisoned))


def _daily(frame: pl.DataFrame) -> pl.DataFrame:
    return resample_bars(frame, source=_FIVE, target=DAILY, calendar="XNYS")


def test_alignment_attaches_a_daily_bar_only_after_its_session_close() -> None:
    clean = _frame()
    # Poison the second session's daily bar inputs: only bars known after its 16:00 New York
    # close may see them. A 5m row known before that close must carry session one's bar.
    cutoff = datetime(2026, 11, 17, 21, 0, tzinfo=UTC)
    poisoned_fine = clean.with_columns(
        pl.when(pl.col("ts") >= datetime(2026, 11, 17, tzinfo=UTC))
        .then(pl.col("close") * 3.0)
        .otherwise(pl.col("close"))
        .alias("close")
    )

    def aligned(fine: pl.DataFrame) -> pl.DataFrame:
        out = align_as_known(
            fine,
            fine_timeframe=_FIVE,
            coarse=_daily(fine),
            coarse_timeframe=DAILY,
            calendar="XNYS",
        )
        return out.filter(pl.col("ts") + pl.duration(minutes=5) < cutoff).select("ts", "htf_close")

    clean_rows = aligned(clean)
    poisoned_rows = aligned(poisoned_fine)
    assert clean_rows.equals(poisoned_rows)
    first_day_close = _daily(clean)["close"][0]
    second = clean_rows.filter(pl.col("ts") >= datetime(2026, 11, 17, tzinfo=UTC))
    assert second["htf_close"].to_list() == [first_day_close] * second.height


def test_leaky_twin_alignment_on_bar_start_is_caught() -> None:
    """Joining the daily bar on its START stamp would show session two's close all day."""
    clean = _frame()
    poisoned_fine = clean.with_columns(
        pl.when(pl.col("ts") >= datetime(2026, 11, 17, tzinfo=UTC))
        .then(pl.col("close") * 3.0)
        .otherwise(pl.col("close"))
        .alias("close")
    )

    def leaky(fine: pl.DataFrame) -> pl.DataFrame:
        coarse = _daily(fine).select(
            pl.col("ts").alias("htf_ts"), pl.col("close").alias("htf_close")
        )
        out = fine.sort("ts").join_asof(coarse.sort("htf_ts"), left_on="ts", right_on="htf_ts")
        return out.filter(pl.col("ts") < datetime(2026, 11, 17, 21, 0, tzinfo=UTC)).select(
            "ts", "htf_close"
        )

    assert not leaky(clean).equals(leaky(poisoned_fine))
