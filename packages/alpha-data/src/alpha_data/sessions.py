"""Exchange-local session labels and UTC bar availability instants."""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import lru_cache

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl
from exchange_calendars.exchange_calendar import ExchangeCalendar  # type: ignore[import-untyped]

from alpha_core import DataError
from alpha_data.timeframe import BarTimeframe


def default_session(calendar: str | None) -> str:
    return "regular" if calendar is not None else "continuous"


def check_session(scope: str, calendar: str | None) -> None:
    if scope not in {"regular", "extended", "continuous"}:
        raise DataError(f"unknown session scope {scope!r}")
    if (scope == "continuous") != (calendar is None):
        raise DataError(f"session scope {scope!r} is incompatible with calendar {calendar!r}")


@lru_cache(maxsize=32)
def _calendar(name: str) -> ExchangeCalendar:
    try:
        return xcals.get_calendar(name)
    except (ValueError, KeyError) as exc:
        raise DataError(f"invalid exchange calendar {name!r}: {exc}") from exc


def _aware_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise DataError("bar timestamps and cutoffs must be timezone-aware")
    return ts.astimezone(UTC)


def session_bounds(calendar: str, session_date: date) -> tuple[datetime, datetime]:
    """Regular open and close, including DST and shortened sessions."""
    exchange = _calendar(calendar)
    try:
        opening = exchange.session_open(session_date.isoformat()).to_pydatetime()
        closing = exchange.session_close(session_date.isoformat()).to_pydatetime()
    except ValueError as exc:
        raise DataError(f"invalid session {session_date} for {calendar}: {exc}") from exc
    return opening.astimezone(UTC), closing.astimezone(UTC)


def sessions_between(calendar: str, first: date, last: date) -> list[date]:
    """Every exchange session date from ``first`` to ``last`` inclusive."""
    return [ts.date() for ts in _calendar(calendar).sessions_in_range(first, last)]


def session_date_of(ts: datetime, calendar: str | None) -> date:
    ts = _aware_utc(ts)
    return ts.astimezone(_calendar(calendar).tz).date() if calendar is not None else ts.date()


def filter_session(
    frame: pl.DataFrame, *, timeframe: BarTimeframe, calendar: str | None, scope: str
) -> pl.DataFrame:
    """Keep only intraday intervals wholly inside the selected regular session."""
    check_session(scope, calendar)
    if timeframe.is_daily or scope in {"extended", "continuous"}:
        return frame
    assert calendar is not None  # check_session establishes this for regular scope
    exchange = _calendar(calendar)
    bounds: dict[date, tuple[datetime, datetime] | None] = {}
    keep = []
    for ts in frame["ts"].to_list():
        day = session_date_of(ts, calendar)
        if day not in bounds:
            try:
                is_session = exchange.is_session(day.isoformat())
            except ValueError as exc:
                raise DataError(f"session date {day} outside calendar {calendar}: {exc}") from exc
            bounds[day] = session_bounds(calendar, day) if is_session else None
        interval = bounds[day]
        keep.append(
            interval is not None and interval[0] <= ts and ts + timeframe.duration <= interval[1]
        )
    return frame.filter(pl.Series(keep, dtype=pl.Boolean))


def bar_known_at(ts: datetime, *, timeframe: BarTimeframe, calendar: str | None) -> datetime:
    """Daily stock stamps denote session dates; intraday stamps denote interval starts.

    A daily bar dated on a day that is not an exchange session (a vendor row on a holiday) has no
    close to wait for; it is treated as known at the end of its UTC day, never earlier.
    """
    ts = _aware_utc(ts)
    if timeframe.is_daily and calendar is not None:
        if _calendar(calendar).is_session(ts.date().isoformat()):
            return session_bounds(calendar, ts.date())[1]
        return ts + timeframe.duration
    return ts + timeframe.duration
