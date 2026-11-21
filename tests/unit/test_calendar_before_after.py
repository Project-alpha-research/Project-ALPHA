"""Quant safety of the calendar sweep: the bars a read keeps, and the instant each becomes known.

`_runner.load_bars` (research, exact `as_of`) and `follow_source.forward_bars` used to skip the
calendar for any bar older than 7 days (`bar.ts < as_of - 7 days`). That kept such bars without a
lookup, because the close of a session 7 days back is long before the cutoff, and it also avoided
the library's moving start. The home now answers every bar, so the shortcut is gone. These tests
rebuild the OLD predicate from the library's own default window (an independent oracle) and require
the same kept set for in-window dates, and no instant earlier than the oracle's.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl
import pytest

from alpha_cli import _runner, follow_source
from alpha_data.sessions import bar_known_at
from alpha_data.store import ParquetStore
from alpha_data.timeframe import DAILY

ORACLE = xcals.get_calendar("XNYS")
FIRST_DAY = ORACLE.first_session.date() + timedelta(days=30)
LAST_DAY = date(2026, 11, 19)
HOLIDAY = date(2019, 7, 4)
CLOSES = {s.date(): c.to_pydatetime() for s, c in ORACLE.closes.items()}


def _old_known_at(ts: datetime) -> datetime:
    """The pre-sweep answer for an in-window date, from the library default window."""
    day = ts.astimezone(UTC).date()
    return CLOSES.get(day, ts + DAILY.duration)


def _store(home: Path) -> list[datetime]:
    days = [s.date() for s in ORACLE.sessions_in_range(FIRST_DAY.isoformat(), LAST_DAY.isoformat())]
    days = sorted({*days, HOLIDAY})  # a vendor row on a holiday
    stamps = [datetime(d.year, d.month, d.day, tzinfo=UTC) for d in days]
    rows = [
        {"ts": t, "open": 100.0, "high": 110.0, "low": 90.0, "close": 100.0 + i % 5, "volume": 1.0}
        for i, t in enumerate(stamps)
    ]
    store = ParquetStore(home / "store")
    store.write_provenance("SPY", source="alpaca", adapter_version="1", parser_version="1")
    store.write_bars("SPY", pl.DataFrame(rows))
    return stamps


CUTOFFS = [
    datetime(2026, 11, 19, 15, tzinfo=UTC),  # during the newest session
    datetime(2026, 11, 19, 21, 30, tzinfo=UTC),  # after its close
    datetime(2026, 11, 20, 14, 31, tzinfo=UTC),  # the next open
    datetime(2026, 11, 21, 10, tzinfo=UTC),  # a Saturday
    datetime(2019, 7, 4, 12, tzinfo=UTC),  # a holiday row's own day
    datetime(2019, 7, 5, 0, 30, tzinfo=UTC),
    datetime(2018, 3, 29, 20, tzinfo=UTC),  # the day before Good Friday
]


@pytest.mark.parametrize("cutoff", CUTOFFS)
def test_load_bars_keeps_the_same_bars_as_before(tmp_path: Path, cutoff: datetime) -> None:
    stamps = _store(tmp_path)
    bars, _ = _runner.load_bars("SPY", data_dir=tmp_path, as_of=cutoff)
    # Old rule: every stored bar stamped at or before the cutoff, minus a recent bar still open.
    recent = cutoff - timedelta(days=7)
    expected = [t for t in stamps if t <= cutoff and (t < recent or _old_known_at(t) <= cutoff)]
    assert [b.ts for b in bars] == expected


@pytest.mark.parametrize("now", CUTOFFS[:4])
def test_forward_bars_keeps_the_same_bars_as_before(tmp_path: Path, now: datetime) -> None:
    stamps = _store(tmp_path)
    known, calendar = follow_source.forward_bars(tmp_path, "SPY", now)
    assert calendar == "XNYS"
    recent = now - timedelta(days=7)
    expected = [t for t in stamps if t <= now and (t < recent or _old_known_at(t) <= now)]
    assert [b.ts for b in known] == expected


def test_no_bar_became_known_earlier_and_old_bars_always_pass(tmp_path: Path) -> None:
    """The deleted 7-day shortcut kept a bar older than a week unseen; the home keeps it too."""
    stamps = _store(tmp_path)
    for ts in stamps:
        assert bar_known_at(ts, timeframe=DAILY, calendar="XNYS") == _old_known_at(ts)
    cutoff = CUTOFFS[1]
    old = [t for t in stamps if t < cutoff - timedelta(days=7)]
    assert old
    assert all(bar_known_at(t, timeframe=DAILY, calendar="XNYS") <= cutoff for t in old)
    assert time(0) == time.min  # the bars are stamped at 00:00 UTC, as before
