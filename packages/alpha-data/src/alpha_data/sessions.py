"""Exchange-local session labels and UTC bar availability instants.

This module is the only place in the project that talks to the exchange-calendars library.
The library supports a moving window. Its default start is about 20 years before today, so every
call here builds the calendar from ``WIDE_START`` (or the calendar's own earliest year, if later).
A day inside that window is answered by the library. Two cases remain:

* Before the window start, a daily bar cannot be matched to a real session. The fallback treats
  each bar date as a session and its close as the regular close of the exchange, in exchange-local
  time, DST aware (the latest regular close the calendar knows). A Saturday or Sunday has no
  session and keeps the end-of-day rule. Such a result is labelled ``OUTSIDE_RANGE_LABEL``.
  The fallback may place a decision instant later than the truth, never earlier.
* After the window end (about a year ahead), the library has no sessions and future sessions are
  not research: the home refuses with ``CalendarRangeError``.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from functools import lru_cache

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl
from exchange_calendars.errors import CalendarError  # type: ignore[import-untyped]

from alpha_core import DataError
from alpha_data.timeframe import BarTimeframe

OUTSIDE_RANGE_LABEL = "calendar-outside-supported-range"
WIDE_START = date(1950, 1, 1)


class CalendarRangeError(DataError):
    """A session was asked for after the calendar's last session, or before it with no fallback."""


@dataclass(frozen=True)
class _Table:
    name: str
    zone: tzinfo
    days: tuple[date, ...]
    opens: dict[date, datetime]
    closes: dict[date, datetime]
    regular_close: time
    close_offset: int

    @property
    def first(self) -> date:
        return self.days[0]

    @property
    def last(self) -> date:
        return self.days[-1]


def default_session(calendar: str | None) -> str:
    return "regular" if calendar is not None else "continuous"


def check_session(scope: str, calendar: str | None) -> None:
    if scope not in {"regular", "extended", "continuous"}:
        raise DataError(f"unknown session scope {scope!r}")
    if (scope == "continuous") != (calendar is None):
        raise DataError(f"session scope {scope!r} is incompatible with calendar {calendar!r}")


@lru_cache(maxsize=32)
def _table(name: str) -> _Table:
    try:
        base = xcals.get_calendar(name)
        lowest = type(base).bound_min()
        start = WIDE_START if lowest is None else max(WIDE_START, lowest.date())
        exchange = xcals.get_calendar(name, start=start.isoformat())
    except (ValueError, KeyError, CalendarError) as exc:
        raise DataError(f"invalid exchange calendar {name!r}: {exc}") from exc
    opens = {s.date(): v.to_pydatetime().astimezone(UTC) for s, v in exchange.opens.items()}
    closes = {s.date(): v.to_pydatetime().astimezone(UTC) for s, v in exchange.closes.items()}
    return _Table(
        name=name,
        zone=exchange.tz,
        days=tuple(opens),
        opens=opens,
        closes=closes,
        regular_close=max(t for _, t in exchange.close_times),
        close_offset=int(exchange.close_offset),
    )


def _aware_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise DataError("bar timestamps and cutoffs must be timezone-aware")
    return ts.astimezone(UTC)


def supported_range(calendar: str) -> tuple[date, date]:
    """The first and last session the project can ask `calendar` about."""
    table = _table(calendar)
    return table.first, table.last


def outside_supported_range(calendar: str | None, day: date) -> bool:
    """True when `day` is before the first session: the fallback and its label apply."""
    return calendar is not None and day < _table(calendar).first


def range_label(calendar: str | None, first_day: date) -> str | None:
    """`OUTSIDE_RANGE_LABEL` when bars from `first_day` rest on the fallback, else None."""
    return OUTSIDE_RANGE_LABEL if outside_supported_range(calendar, first_day) else None


def _refuse_after(table: _Table, day: date) -> None:
    if day > table.last:
        raise CalendarRangeError(
            f"the calendar {table.name} has no sessions after {table.last}; "
            f"{day} is a future session and not research"
        )


def _fallback_close(table: _Table, day: date) -> datetime | None:
    """Regular close of a weekday before the window, exchange-local and DST aware."""
    if day.weekday() >= 5:
        return None
    local = datetime.combine(day, table.regular_close, tzinfo=table.zone)
    return local.astimezone(UTC) + timedelta(days=table.close_offset)


def is_session(calendar: str, day: date) -> bool:
    """A real session inside the window; before it, every weekday (fallback); after it, refuse."""
    table = _table(calendar)
    _refuse_after(table, day)
    if day < table.first:
        return day.weekday() < 5
    return day in table.closes


def session_close(calendar: str, day: date) -> datetime:
    """UTC close of the session on `day`; a non-session raises ``DataError``."""
    table = _table(calendar)
    _refuse_after(table, day)
    found = _fallback_close(table, day) if day < table.first else table.closes.get(day)
    if found is None:
        raise DataError(f"invalid session {day} for {calendar}: not a session")
    return found


def session_bounds(calendar: str, session_date: date) -> tuple[datetime, datetime]:
    """Regular open and close, including DST and shortened sessions. No fallback for the open."""
    table = _table(calendar)
    _refuse_after(table, session_date)
    if session_date < table.first:
        raise CalendarRangeError(
            f"the calendar {calendar} has no session opens before {table.first}: {session_date}"
        )
    if session_date not in table.opens:
        raise DataError(f"invalid session {session_date} for {calendar}: not a session")
    return table.opens[session_date], table.closes[session_date]


def sessions_between(
    calendar: str, first: date, last: date, present: Collection[date] | None = None
) -> list[date]:
    """Every exchange session date from ``first`` to ``last`` inclusive.

    Before the window start the sessions are the dates in ``present`` (the bar dates), or every
    weekday when ``present`` is None. After the window end: ``CalendarRangeError``.
    """
    table = _table(calendar)
    _refuse_after(table, last)
    old: list[date] = []
    if first < table.first:
        stop = min(last, table.first - timedelta(days=1))
        if present is not None:
            old = sorted(d for d in present if first <= d <= stop)
        else:
            old = [
                first + timedelta(n)
                for n in range((stop - first).days + 1)
                if (first + timedelta(n)).weekday() < 5
            ]
    inside = table.days[bisect_left(table.days, first) : bisect_right(table.days, last)]
    return [*old, *inside]


def daily_session_closes(
    calendar: str, first: date, last: date, present: Collection[date] | None = None
) -> dict[date, datetime]:
    """Exchange close instants for an explicit history, including old and shortened sessions."""
    table = _table(calendar)
    out: dict[date, datetime] = {}
    for day in sessions_between(calendar, first, last, present):
        out[day] = table.closes[day] if day >= table.first else _old_close(table, day)
    return out


def _old_close(table: _Table, day: date) -> datetime:
    found = _fallback_close(table, day)
    if found is None:
        raise DataError(f"invalid session {day} for {table.name}: not a session")
    return found


def session_on_or_before(calendar: str, day: date) -> date:
    """The latest session on or before `day`; only inside the window."""
    table = _table(calendar)
    _refuse_after(table, day)
    index = bisect_right(table.days, day)
    if index == 0:
        raise CalendarRangeError(f"the calendar {calendar} has no session on or before {day}")
    return table.days[index - 1]


def session_before(calendar: str, day: date) -> date:
    """The session before `day` (a session or not)."""
    return session_on_or_before(calendar, day - timedelta(days=1))


def session_after(calendar: str, day: date) -> date:
    """The first session after `day`; after the window end: ``CalendarRangeError``."""
    table = _table(calendar)
    index = bisect_right(table.days, day)
    if index == len(table.days):
        raise CalendarRangeError(
            f"the calendar {calendar} has no sessions after {table.last}; "
            f"the session after {day} is a future session and not research"
        )
    return table.days[index]


def session_date_of(ts: datetime, calendar: str | None) -> date:
    ts = _aware_utc(ts)
    return ts.astimezone(_table(calendar).zone).date() if calendar is not None else ts.date()


def calendar_zone(calendar: str) -> tzinfo:
    """The exchange-local time zone."""
    return _table(calendar).zone


def filter_session(
    frame: pl.DataFrame, *, timeframe: BarTimeframe, calendar: str | None, scope: str
) -> pl.DataFrame:
    """Keep only intraday intervals wholly inside the selected regular session."""
    check_session(scope, calendar)
    if timeframe.is_daily or scope in {"extended", "continuous"}:
        return frame
    assert calendar is not None  # check_session establishes this for regular scope
    table = _table(calendar)
    bounds: dict[date, tuple[datetime, datetime] | None] = {}
    keep = []
    for ts in frame["ts"].to_list():
        day = session_date_of(ts, calendar)
        if day not in bounds:
            if not table.first <= day <= table.last:
                raise CalendarRangeError(
                    f"session date {day} outside calendar {calendar}: "
                    f"intraday bars need {table.first} to {table.last}"
                )
            bounds[day] = (table.opens[day], table.closes[day]) if day in table.opens else None
        interval = bounds[day]
        keep.append(
            interval is not None and interval[0] <= ts and ts + timeframe.duration <= interval[1]
        )
    return frame.filter(pl.Series(keep, dtype=pl.Boolean))


def bar_known_at(ts: datetime, *, timeframe: BarTimeframe, calendar: str | None) -> datetime:
    """Daily stock stamps denote session dates; intraday stamps denote interval starts.

    A daily bar dated on a day that is not an exchange session (a vendor row on a holiday) has no
    close to wait for; it is treated as known at the end of its UTC day, never earlier. A daily bar
    before the window start uses the regular-close fallback; after the window end it is refused.
    """
    ts = _aware_utc(ts)
    if timeframe.is_daily and calendar is not None:
        table = _table(calendar)
        day = ts.date()
        _refuse_after(table, day)
        found = _fallback_close(table, day) if day < table.first else table.closes.get(day)
        return found if found is not None else ts + timeframe.duration
    return ts + timeframe.duration
