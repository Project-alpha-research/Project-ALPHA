"""The one calendar home: old history, the window edges, holidays, DST, crypto and the future.

Every boundary is read from the library at run time; nothing is frozen to today's date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pytest

from alpha_core import DataError
from alpha_data import sessions
from alpha_data.sessions import (
    OUTSIDE_RANGE_LABEL,
    CalendarRangeError,
    bar_known_at,
    daily_session_closes,
    is_session,
    outside_supported_range,
    range_label,
    session_after,
    session_before,
    session_bounds,
    session_close,
    session_on_or_before,
    sessions_between,
    supported_range,
)
from alpha_data.timeframe import DAILY, BarTimeframe


def _stamp(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _weekday_before(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _known(day: date, calendar: str | None = "XNYS") -> datetime:
    return bar_known_at(_stamp(day), timeframe=DAILY, calendar=calendar)


def test_a_1995_daily_bar_is_known_at_its_real_close() -> None:
    assert _known(date(1995, 3, 15)) == datetime(1995, 3, 15, 21, tzinfo=UTC)  # EST, 16:00
    assert not outside_supported_range("XNYS", date(1995, 3, 15))
    assert range_label("XNYS", date(1995, 3, 15)) is None


def test_a_known_half_day_closes_early_and_a_holiday_has_no_session() -> None:
    assert _known(date(1995, 7, 3)) == datetime(1995, 7, 3, 17, tzinfo=UTC)  # 13:00 EDT
    assert session_close("XNYS", date(1995, 7, 3)) == datetime(1995, 7, 3, 17, tzinfo=UTC)
    assert not is_session("XNYS", date(1995, 12, 25))
    # a vendor row on a holiday is known at the end of its UTC day, never earlier
    assert _known(date(1995, 12, 25)) == datetime(1995, 12, 26, tzinfo=UTC)
    with pytest.raises(DataError, match="not a session"):
        session_close("XNYS", date(1995, 12, 25))


@pytest.mark.parametrize(
    ("day", "close_hour_utc"),
    [
        (date(1995, 3, 31), 21),
        (date(1995, 4, 3), 20),
        (date(1995, 10, 27), 20),
        (date(1995, 10, 30), 21),
    ],
)
def test_the_close_follows_the_daylight_saving_change(day: date, close_hour_utc: int) -> None:
    assert _known(day) == datetime(day.year, day.month, day.day, close_hour_utc, tzinfo=UTC)


def test_the_first_day_of_the_window_is_a_real_session() -> None:
    first, _ = supported_range("XNYS")
    oracle = xcals.get_calendar("XNYS", start=first.isoformat())
    assert _known(first) == oracle.session_close(first.isoformat()).to_pydatetime()
    assert not outside_supported_range("XNYS", first)


def test_one_day_before_the_window_uses_the_labelled_fallback() -> None:
    first, _ = supported_range("XNYS")
    day = _weekday_before(first)
    assert outside_supported_range("XNYS", day)
    assert range_label("XNYS", day) == OUTSIDE_RANGE_LABEL == "calendar-outside-supported-range"
    local = datetime.combine(day, time(16), tzinfo=ZoneInfo("America/New_York"))
    assert _known(day) == local.astimezone(UTC)
    assert is_session("XNYS", day)
    assert session_close("XNYS", day) == _known(day)


def test_the_fallback_is_never_earlier_than_the_real_close() -> None:
    first, _ = supported_range("XNYS")
    table = sessions._table("XNYS")
    for day in sessions_between("XNYS", first, first + timedelta(days=3650)):
        fallback = sessions._fallback_close(table, day)
        assert fallback is not None
        assert fallback >= session_close("XNYS", day)


def test_the_fallback_follows_daylight_saving_and_skips_weekends() -> None:
    summer = date(1949, 7, 1)
    winter = date(1949, 12, 30)
    assert summer.weekday() < 5 and winter.weekday() < 5
    assert _known(summer).hour == 20
    assert _known(winter).hour == 21
    saturday = date(1940, 6, 1)
    assert saturday.weekday() == 5
    assert _known(saturday) == datetime(1940, 6, 2, tzinfo=UTC)
    assert not is_session("XNYS", saturday)


def test_a_1940_daily_bar_does_not_crash_and_is_labelled() -> None:
    assert _known(date(1940, 6, 3)) == datetime(1940, 6, 3, 20, tzinfo=UTC)
    assert range_label("XNYS", date(1940, 6, 3)) == OUTSIDE_RANGE_LABEL
    days = sessions_between("XNYS", date(1940, 6, 3), date(1940, 6, 9), {date(1940, 6, 4)})
    assert days == [date(1940, 6, 4)]
    assert len(sessions_between("XNYS", date(1940, 6, 3), date(1940, 6, 9))) == 5
    closes = daily_session_closes("XNYS", date(1940, 6, 3), date(1940, 6, 9), {date(1940, 6, 4)})
    assert list(closes) == [date(1940, 6, 4)]


def test_a_range_over_the_window_start_joins_the_fallback_and_the_real_sessions() -> None:
    first, _ = supported_range("XNYS")
    held = {_weekday_before(first)}
    days = sessions_between("XNYS", first - timedelta(days=5), first + timedelta(days=5), held)
    assert days[0] == _weekday_before(first)
    assert days[1] == first
    assert days == sorted(days)


def test_a_crypto_bar_has_no_calendar() -> None:
    day = date(2026, 6, 6)  # a Saturday
    assert _known(day, None) == _stamp(day) + DAILY.duration
    assert not outside_supported_range(None, date(1900, 1, 1))
    assert range_label(None, date(1900, 1, 1)) is None
    hour = bar_known_at(_stamp(day), timeframe=BarTimeframe(60), calendar=None)
    assert hour == _stamp(day) + timedelta(hours=1)


def test_after_the_window_end_everything_refuses_in_plain_words() -> None:
    _, last = supported_range("XNYS")
    later = last + timedelta(days=30)
    with pytest.raises(CalendarRangeError, match="future session"):
        _known(later)
    with pytest.raises(CalendarRangeError):
        is_session("XNYS", later)
    with pytest.raises(CalendarRangeError):
        sessions_between("XNYS", last, later)
    with pytest.raises(CalendarRangeError):
        session_after("XNYS", last)
    with pytest.raises(CalendarRangeError):
        session_on_or_before("XNYS", later)
    with pytest.raises(CalendarRangeError):
        session_bounds("XNYS", later)
    assert issubclass(CalendarRangeError, DataError)
    assert _known(last) == session_close("XNYS", last)


def test_intraday_sessions_before_the_window_refuse_rather_than_guess() -> None:
    first, _ = supported_range("XNYS")
    with pytest.raises(CalendarRangeError):
        session_bounds("XNYS", _weekday_before(first))


def test_a_calendar_with_a_later_first_year_widens_only_as_far_as_it_can() -> None:
    first, last = supported_range("XTKS")
    assert first >= date(1997, 1, 1)
    assert last >= date.today()
    assert outside_supported_range("XTKS", first - timedelta(days=1))


def test_an_unknown_calendar_is_a_data_error() -> None:
    with pytest.raises(DataError, match="invalid exchange calendar"):
        supported_range("NOPE")


@pytest.mark.parametrize("name", ["XNYS", "XLON"])
def test_in_window_answers_equal_the_library_default_window(name: str) -> None:
    """Widening the start must not move any answer the library already gave."""
    default = xcals.get_calendar(name)
    first, last = default.first_session.date(), default.last_session.date()
    expected = [s.date() for s in default.sessions]
    assert sessions_between(name, first, last) == expected
    closes = daily_session_closes(name, first, last)
    for day, opening, closing in zip(expected, default.opens, default.closes, strict=True):
        assert session_bounds(name, day) == (opening.to_pydatetime(), closing.to_pydatetime())
        assert closes[day] == closing.to_pydatetime()
        assert _known(day, name) == closing.to_pydatetime()
    index = {d: i for i, d in enumerate(expected)}
    for offset in range(0, (last - first).days, 11):
        probe = first + timedelta(days=offset)
        before = default.date_to_session(probe, direction="previous").date()
        assert session_on_or_before(name, probe) == before
        if probe in index and index[probe] + 1 < len(expected):
            assert session_after(name, probe) == expected[index[probe] + 1]
            assert session_before(name, expected[index[probe] + 1]) == probe
        if probe not in index:
            assert _known(probe, name) == _stamp(probe) + DAILY.duration
            assert not is_session(name, probe)
