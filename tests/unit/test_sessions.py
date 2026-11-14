"""Exchange-session boundaries and bar availability."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.sessions import (
    bar_known_at,
    check_session,
    default_session,
    filter_session,
    session_bounds,
    session_date_of,
)
from alpha_data.timeframe import DAILY, BarTimeframe


@pytest.mark.parametrize(
    ("day", "open_hour", "close_hour"),
    [(date(2026, 3, 9), 13, 20), (date(2026, 11, 2), 14, 21), (date(2026, 11, 27), 14, 18)],
)
def test_regular_bounds_and_filter(day, open_hour, close_hour):
    opening, closing = session_bounds("XNYS", day)
    assert opening == datetime.combine(day, datetime.min.time(), UTC).replace(
        hour=open_hour, minute=30
    )
    assert closing == datetime.combine(day, datetime.min.time(), UTC).replace(hour=close_hour)
    stamps = [opening - timedelta(minutes=5), opening, closing - timedelta(minutes=5), closing]
    frame = pl.DataFrame({"ts": stamps})
    result = filter_session(frame, timeframe=BarTimeframe(5), calendar="XNYS", scope="regular")
    assert result["ts"].to_list() == stamps[1:3]
    assert bar_known_at(stamps[2], timeframe=BarTimeframe(5), calendar="XNYS") == closing
    assert (
        bar_known_at(
            datetime.combine(day, datetime.min.time(), UTC), timeframe=DAILY, calendar="XNYS"
        )
        == closing
    )


def test_clock_aligned_hour_and_weekend():
    ny = ZoneInfo("America/New_York")
    stamps = [datetime(2026, 3, 9, h, tzinfo=ny).astimezone(UTC) for h in (9, 10, 15, 16)]
    stamps.append(datetime(2026, 3, 8, 15, tzinfo=UTC))
    result = filter_session(
        pl.DataFrame({"ts": stamps}), timeframe=BarTimeframe(60), calendar="XNYS", scope="regular"
    )
    assert result["ts"].to_list() == stamps[1:3]


@pytest.mark.parametrize(
    ("scope", "calendar", "timeframe"),
    [
        ("extended", "XNYS", BarTimeframe(5)),
        ("continuous", None, BarTimeframe(5)),
        ("regular", "XNYS", DAILY),
    ],
)
def test_passthrough(scope, calendar, timeframe):
    frame = pl.DataFrame({"ts": [datetime(2026, 3, 8, tzinfo=UTC)]})
    assert filter_session(frame, timeframe=timeframe, calendar=calendar, scope=scope) is frame


@pytest.mark.parametrize(
    ("scope", "calendar"),
    [("bad", None), ("continuous", "XNYS"), ("regular", None), ("extended", None)],
)
def test_scope_errors(scope, calendar):
    with pytest.raises(DataError):
        check_session(scope, calendar)


def test_default_local_date_and_continuous_known_at():
    ts = datetime(2026, 11, 3, 1, tzinfo=UTC)
    assert default_session("XNYS") == "regular"
    assert default_session(None) == "continuous"
    assert session_date_of(ts, "XNYS") == date(2026, 11, 2)
    assert session_date_of(ts, None) == date(2026, 11, 3)
    assert bar_known_at(ts, timeframe=DAILY, calendar=None) == ts + timedelta(days=1)
    assert bar_known_at(ts, timeframe=BarTimeframe(60), calendar=None) == ts + timedelta(hours=1)
