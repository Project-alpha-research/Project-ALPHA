"""Early closes before 1993 are the library's blanket rules, not a checked list: never earlier.

The library applies "Christmas Eve and Black Friday close at 14:00" to every year before 1993, with
no per-year source. A rule that invents an early close moves a decision instant earlier than the
truth. The home keeps the regular close for those days and labels them in the health report.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl

from alpha_data.health import health_report
from alpha_data.sessions import (
    EXACT_CLOSES_FROM,
    OUTSIDE_RANGE_LABEL,
    bar_known_at,
    close_assumed,
    daily_session_closes,
    session_bounds,
    session_close,
    sessions_between,
)
from alpha_data.timeframe import DAILY

NEW_YORK = ZoneInfo("America/New_York")
LIBRARY = xcals.get_calendar("XNYS", start="1950-01-01")


def _regular(day: date) -> datetime:
    return datetime.combine(day, time(16), tzinfo=NEW_YORK).astimezone(UTC)


def _library_close(day: date) -> datetime:
    found: datetime = LIBRARY.session_close(day.isoformat()).to_pydatetime()
    return found


def test_a_library_early_close_before_1993_keeps_the_regular_close() -> None:
    day = date(1990, 12, 24)
    assert _library_close(day) < _regular(day)  # the library says 14:00
    stamp = datetime(day.year, day.month, day.day, tzinfo=UTC)
    assert session_close("XNYS", day) == _regular(day)
    assert bar_known_at(stamp, timeframe=DAILY, calendar="XNYS") == _regular(day)
    assert daily_session_closes("XNYS", day, day) == {day: _regular(day)}
    assert session_bounds("XNYS", day)[1] == _regular(day)
    assert close_assumed("XNYS", day)


def test_no_close_before_1993_is_earlier_than_the_regular_close() -> None:
    days = sessions_between("XNYS", date(1950, 1, 3), date(1992, 12, 31))
    assert all(session_close("XNYS", d) >= _regular(d) for d in days)


def test_early_closes_from_1993_are_the_library_answer() -> None:
    assert date(1993, 1, 1) == EXACT_CLOSES_FROM
    for day in (date(1993, 11, 26), date(1999, 12, 31), date(2012, 11, 23)):
        assert session_close("XNYS", day) == _library_close(day) < _regular(day)
        assert not close_assumed("XNYS", day)
    assert not close_assumed("XNYS", date(1990, 12, 21))  # a full day before 1993 is exact


def test_the_health_report_labels_bars_on_assumed_early_close_days() -> None:
    days = [date(1990, 12, 20), date(1990, 12, 21), date(1990, 12, 24), date(1990, 12, 26)]
    bars = pl.DataFrame(
        {
            "ts": [datetime(d.year, d.month, d.day, tzinfo=UTC) for d in days],
            "open": [100.0] * 4,
            "high": [101.0] * 4,
            "low": [99.0] * 4,
            "close": [100.0, 100.5, 100.2, 100.4],
            "volume": [1.0] * 4,
        }
    )
    result = health_report(
        bars, symbol="X", calendar="XNYS", report_time=datetime(1991, 1, 2, tzinfo=UTC)
    )
    [item] = [c for c in result.checks if c.id == "calendar_range"]
    assert item.status == "pass"
    assert OUTSIDE_RANGE_LABEL in item.finding
    assert "1990-12-24" in item.finding
    assert item.count == 1
