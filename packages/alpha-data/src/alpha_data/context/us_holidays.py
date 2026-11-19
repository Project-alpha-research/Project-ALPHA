"""US federal holidays by rule, observed on the nearest weekday; used only to push times later."""

from __future__ import annotations

from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_monday(year: int, month: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=last.weekday())


def _observed(day: date) -> date:
    return (
        day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=day.weekday() == 6)
    )


def federal_holidays(year: int) -> set[date]:
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11)]
    fixed.append(date(year, 12, 25))
    floating = [
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_monday(year, 5),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _nth_weekday(year, 11, 3, 4),
    ]
    return {_observed(day) for day in fixed} | set(floating)


def is_us_federal_holiday(day: date) -> bool:
    """Includes holidays observed across a year end (1 January on a Saturday is observed 31 Dec)."""
    return any(day in federal_holidays(year) for year in (day.year - 1, day.year, day.year + 1))
