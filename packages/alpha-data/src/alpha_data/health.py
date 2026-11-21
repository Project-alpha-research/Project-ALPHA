"""Point-in-time mechanical health of raw daily OHLCV and membership history."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from statistics import median, stdev
from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, ValidationError

from alpha_core import (
    ActionType,
    Bar,
    CorporateAction,
    DataError,
    UniverseMembership,
    members_as_of,
)
from alpha_data.adapters.yfinance_adapter import split_discontinuity
from alpha_data.corporate import known_actions
from alpha_data.crypto.quality import missing_slot_ranges
from alpha_data.sessions import daily_session_closes
from alpha_data.timeframe import DAILY

SPLIT_RATIOS = (
    2,
    3,
    4,
    5,
    8,
    10,
    15,
    20,
    1 / 2,
    1 / 3,
    1 / 5,
    1 / 10,
    3 / 2,
)  # Common share exchanges.
RATIO_TOLERANCE = 0.03  # Allow ordinary overnight movement around a mechanical price change.
SPLIT_SESSIONS = 3  # Allow a small mismatch between the provider's bar and action dates.
PEER_MOVE = 0.05  # A sharp market-wide move makes the split interpretation uncertain.
EXTREME_RATIO = 50  # Smaller crypto moves need more evidence for a unit change.
DENOMINATIONS = (100, 1000, 10000)  # Common round unit changes have a recognizable size.
TAIL_SESSIONS = 5  # Allow five completed sessions for publication lag.
MISSING_SHARE = 0.02  # More than this fraction of missing sessions materially breaks coverage.
ZERO_SHARE = 0.05  # Occasional zero volume warrants review; frequent zeros undermine liquidity.
SPIKE_FLOOR = 0.15  # A move must be large in price terms even in a quiet market.
SPIKE_SIGMAS = 8  # Exclude moves commensurate with the instrument's recent volatility.
RETURN_WINDOW = 60  # Use recent returns so distant volatility does not mask a current spike.
MIN_RETURNS = 10  # Shorter histories cannot support the volatility threshold.
UNDO_SHARE = 0.8  # A near reversal on the following bar suggests an isolated bad print.
STALE_BARS = 5  # Several bars repeating every price despite trading suggest a frozen quote.
EXAMPLE_LIMIT = 5  # Keep reports readable while retaining the full count.
DAY = timedelta(days=1)
Group = Literal["adjustments", "timestamps", "gaps", "survivorship"]
Status = Literal["pass", "warn", "fail", "not-applicable"]
GROUPS: tuple[Group, ...] = ("adjustments", "timestamps", "gaps", "survivorship")
_RANK: dict[Status, int] = {"not-applicable": 0, "pass": 1, "warn": 2, "fail": 3}
LIMITATION = "A clean report only means these faults were not found. The prices can still be wrong."


class HealthCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    group: Group
    status: Status
    count: int
    example_dates: tuple[date, ...]
    finding: str
    threshold: str


class HealthReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    report_time: datetime
    checks: tuple[HealthCheck, ...]
    verdict: Status


def worst(checks: Iterable[HealthCheck]) -> Status:
    return max((item.status for item in checks), key=_RANK.__getitem__, default="not-applicable")


def _item(
    name: str,
    group: Group,
    dates: Sequence[date],
    severity: Status,
    finding: str,
    threshold: str,
    *,
    count: int | None = None,
) -> HealthCheck:
    n = len(dates) if count is None else count
    status = severity if n or severity == "not-applicable" else "pass"
    return HealthCheck(
        id=name,
        group=group,
        status=status,
        count=n,
        example_dates=tuple(dates[:EXAMPLE_LIMIT]),
        finding=finding,
        threshold=threshold,
    )


def _words(count: int) -> dict[str, str]:
    """Noun and verb endings so each sentence agrees with its count."""
    one = count == 1
    return {
        "n": str(count),
        "s": "" if one else "s",
        "vs": "s" if one else "",
        "are": "is" if one else "are",
        "have": "has" if one else "have",
        "do": "does" if one else "do",
    }


def _fault(
    name: str,
    group: Group,
    dates: Sequence[date],
    fault: str,
    clean: str,
    threshold: str,
    severity: Status = "fail",
) -> HealthCheck:
    """``fault`` is said when dates were found, ``clean`` when none were."""
    finding = fault.format(**_words(len(dates))) if dates else clean
    return _item(name, group, dates, severity, finding, threshold)


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _bar_runs(bars: Mapping[date, Bar], slots: Mapping[date, int]) -> list[list[Bar]]:
    """Only adjacent, unambiguous exchange or UTC sessions form an overnight observation."""
    runs: list[list[Bar]] = []
    previous = -2
    for day in sorted(bars):
        slot = slots.get(day)
        if slot is None:
            continue
        if slot != previous + 1:
            runs.append([])
        runs[-1].append(bars[day])
        previous = slot
    return runs


def _prices(bar: Bar) -> tuple[float, float, float, float]:
    return (bar.open, bar.high, bar.low, bar.close)


def _price_checks(runs: Sequence[list[Bar]]) -> list[HealthCheck]:
    spikes: list[date] = []
    stale: list[date] = []
    for run in runs:
        history: list[float] = []
        same = 0
        for i, bar in enumerate(run):
            # A frozen quote repeats the whole bar; a coarse tick can repeat only the close.
            if bar.volume == 0:
                same = 0
            elif i and _prices(run[i - 1]) == _prices(bar):
                same += 1
            else:
                same = 1
            if same == STALE_BARS:
                stale.append(bar.ts.date())
            if i == 0:
                continue
            prior = run[i - 1].close
            change = bar.close - prior
            # The only check that reads a later bar: it never judges the last bar of a run.
            if i + 1 < len(run) and abs(change) > prior * SPIKE_FLOOR:
                volatility = stdev(history[-RETURN_WINDOW:]) if len(history) >= MIN_RETURNS else 0.0
                undone = (bar.close - run[i + 1].close) / change
                if abs(change) > prior * SPIKE_SIGMAS * volatility and undone >= UNDO_SHARE:
                    spikes.append(bar.ts.date())
            history.append(change / prior)
    return [
        _fault(
            "spike_snaps_back",
            "gaps",
            spikes,
            "{n} price spike{s} reverse{vs} on the next bar.",
            "No price spike reverses on the next bar.",
            f"> max({SPIKE_FLOOR:.0%}, {SPIKE_SIGMAS} × prior {RETURN_WINDOW}-return SD"
            f" with ≥{MIN_RETURNS} returns), ≥{UNDO_SHARE:.0%} undone",
        ),
        _fault(
            "stale_run",
            "gaps",
            stale,
            f"{{n}} time{{s}} every price stayed frozen for {STALE_BARS} bars or more "
            "while volume traded.",
            f"Prices never stay frozen for {STALE_BARS} bars while volume trades.",
            f"≥{STALE_BARS} consecutive bars with identical open, high, low and close",
            "warn",
        ),
    ]


def _peer_moves(
    peers: Sequence[pl.DataFrame],
    closes: Mapping[date, datetime],
    cutoff: datetime,
    slots: Mapping[date, int],
) -> dict[date, list[float]]:
    moves: dict[date, list[float]] = {}
    for frame in peers:
        valid: dict[date, Bar] = {}
        seen: set[date] = set()
        for row in frame.iter_rows(named=True):
            stamp = row["ts"]
            if not _aware(stamp):
                raise DataError("peer timestamps must be timezone-aware")
            stamp = stamp.astimezone(UTC)
            day = stamp.date()
            if stamp > cutoff or day not in closes or closes[day] > cutoff:
                continue
            if not DAILY.is_aligned(stamp):
                raise DataError(f"peer bar at {stamp} is off the daily UTC grid")
            if day in seen:
                raise DataError(f"duplicate peer bar on {day}")
            seen.add(day)
            valid[day] = Bar.model_validate({**row, "symbol": "peer", "ts": stamp})
        for run in _bar_runs(valid, slots):
            for before, after in pairwise(run):
                moves.setdefault(after.ts.date(), []).append(
                    (after.open - before.close) / before.close
                )
    return moves


def _near(value: float, target: float) -> bool:
    return target * (1 - RATIO_TOLERANCE) <= value <= target * (1 + RATIO_TOLERANCE)


def _crypto_jump(ratio: float) -> str:
    named = next((n for n in DENOMINATIONS if _near(ratio, n) or _near(ratio, 1 / n)), None)
    if named:
        direction = "1/" if ratio < 1 else ""
        return f"Possible redenomination (a change of coin unit) near {direction}{named}×."
    factor = max(ratio, 1 / ratio)
    return f"Possible redenomination after an extreme overnight jump of {factor:g}×."


def _split_jump(day: date, peer_moves: Mapping[date, list[float]]) -> tuple[Status, str]:
    moves = peer_moves.get(day, [])
    if not moves:
        return "warn", "No other series was given to compare, so check by hand."
    if median(abs(move) for move in moves) < PEER_MOVE:
        return "fail", "Other series were quiet that day."
    return "warn", "The market also moved sharply that day; check by hand."


def _unflagged(
    pairs: Mapping[date, tuple[Bar, Bar]],
    splits: Sequence[CorporateAction],
    crypto: bool,
    slots: Mapping[date, int],
    peer_moves: Mapping[date, list[float]],
) -> HealthCheck:
    candidates: list[date] = []
    severity: Status = "not-applicable" if crypto else "pass"
    detail = ""
    for day, (before, after) in pairs.items():
        ratio = before.close / after.open
        if crypto:
            if max(ratio, 1 / ratio) < EXTREME_RATIO:
                continue
            level: Status = "warn"
            message = _crypto_jump(ratio)
        else:
            if not any(_near(ratio, r) for r in SPLIT_RATIOS):
                continue
            if any(
                a.ex_date in slots and abs(slots[a.ex_date] - slots[day]) <= SPLIT_SESSIONS
                for a in known_actions(splits, day)
            ):
                continue
            level, message = _split_jump(day, peer_moves)
        candidates.append(day)
        if _RANK[level] > _RANK[severity] or len(candidates) == 1:
            severity, detail = level, message
    words = _words(len(candidates))
    if crypto:
        clean = "Stock splits do not apply to crypto. No overnight jump of 50 times or more."
        finding = f"{words['n']} overnight jump{words['s']} of {EXTREME_RATIO} times or more. "
        threshold = (
            f"factor ≥{EXTREME_RATIO} in either direction, within {RATIO_TOLERANCE:.0%} "
            f"of {DENOMINATIONS} or inverses"
        )
    else:
        clean = "No overnight jump looks like a missing split."
        finding = (
            f"{words['n']} overnight jump{words['s']} look{words['vs']} like a split "
            "that is not recorded. "
        )
        threshold = (
            f"within {RATIO_TOLERANCE:.0%} of {SPLIT_RATIOS}, ±{SPLIT_SESSIONS} sessions, "
            f"median absolute peer overnight move <{PEER_MOVE:.0%}"
        )
    finding = finding + detail if candidates else clean
    return _item("unflagged_split", "adjustments", candidates, severity, finding, threshold)


def _recorded(
    runs: Sequence[list[Bar]],
    pairs: Mapping[date, tuple[Bar, Bar]],
    splits: Sequence[CorporateAction],
    crypto: bool,
) -> HealthCheck:
    compared: list[date] = []
    mismatches: list[date] = []
    unmatched: list[date] = []
    for action in () if crypto or not runs else splits:
        # Splits outside the bars, or too small to see, are not faults in these bars.
        first, last = runs[0][0].ts.date(), runs[-1][-1].ts.date()
        if action.ratio is None or not first < action.ex_date <= last:
            continue
        pair = pairs.get(action.ex_date)
        if pair is None:
            # None means the split is too small to see, whatever the prices.
            if split_discontinuity(2.0, 1.0, action.ratio) is not None:
                unmatched.append(action.ex_date)
            continue
        matched = split_discontinuity(pair[0].close, pair[1].open, action.ratio)
        if matched is not None:
            compared.append(action.ex_date)
            if not matched:
                mismatches.append(action.ex_date)
    status: Status = "not-applicable"
    note = "No recorded split could be compared with the prices."
    if mismatches:
        status = "fail"
        note = "{n} recorded split{s} {do} not show the expected price step.".format(
            **_words(len(mismatches))
        )
    elif unmatched:
        status = "warn"
        note = "{n} recorded split{s} could not be checked: a bar next to it is missing.".format(
            **_words(len(unmatched))
        )
    elif compared:
        status = "pass"
        note = "{n} recorded split{s} show{vs} the expected price step.".format(
            **_words(len(compared))
        )
    return _item(
        "recorded_splits_applied",
        "adjustments",
        mismatches or unmatched or compared,
        status,
        note,
        "Adapter rule: ≥1.25× in either direction, within half the expected log step.",
    )


def _adjustments(
    runs: Sequence[list[Bar]],
    splits: Sequence[CorporateAction],
    crypto: bool,
    slots: Mapping[date, int],
    peer_moves: Mapping[date, list[float]],
) -> list[HealthCheck]:
    pairs = {after.ts.date(): (before, after) for run in runs for before, after in pairwise(run)}
    return [
        _unflagged(pairs, splits, crypto, slots, peer_moves),
        _recorded(runs, pairs, splits, crypto),
    ]


def _survivorship(
    frames: Mapping[str, pl.DataFrame] | None,
    history: Sequence[UniverseMembership] | None,
    cutoff: datetime,
) -> HealthCheck:
    threshold = "At least one leaver has a completed bar during its membership."
    status: Status
    dates: list[date] = []
    count = 0
    if frames is None:
        status, detail = "not-applicable", "This report covers one instrument."
    elif not history:
        status, detail = (
            "fail",
            "Survivors only: every instrument still trades today. No membership history was given.",
        )
    else:
        evidenced: dict[str, date] = {}
        for row in history:
            if (
                row.effective_to is None
                or row.effective_to > cutoff.date()
                or row.symbol not in frames
            ):
                continue
            for ts in frames[row.symbol]["ts"]:
                # A bar before an already effective departure has completed by cutoff.
                if _aware(ts) and ts <= cutoff and members_as_of((row,), ts.astimezone(UTC).date()):
                    evidenced[row.symbol] = row.effective_to
                    break
        dates = sorted(evidenced.values())
        count = len(dates)
        status = "pass" if count else "fail"
        detail = (
            "{n} instrument{s} that left the list {have} bars from {its} time in it.".format(
                its="its" if count == 1 else "their", **_words(count)
            )
            if count
            else "Survivors only: no instrument that left the list has bars from its time in it."
        )
    return HealthCheck(
        id="survivorship",
        group="survivorship",
        status=status,
        count=count,
        example_dates=tuple(dates[:EXAMPLE_LIMIT]),
        finding=detail,
        threshold=threshold,
    )


@dataclass
class _DailyRows:
    """Evidence accumulated in source order, before any price comparisons."""

    duplicates: list[date] = field(default_factory=list)
    disorder: list[date] = field(default_factory=list)
    off_grid: list[date] = field(default_factory=list)
    non_sessions: list[date] = field(default_factory=list)
    invalid: list[date] = field(default_factory=list)
    zeros: list[date] = field(default_factory=list)
    partial: list[date] = field(default_factory=list)
    visible: set[date] = field(default_factory=set)
    valid: dict[date, Bar] = field(default_factory=dict)
    completed: int = 0


def _timestamped_rows(
    bars: pl.DataFrame, report_time: datetime
) -> tuple[list[tuple[datetime, dict[str, object]]], HealthCheck, list[date]]:
    rows = []
    naive: list[date] = []
    invalid_time = 0
    future: list[date] = []
    for row in bars.iter_rows(named=True):
        ts = row["ts"]
        if not _aware(ts):
            invalid_time += 1
            if isinstance(ts, datetime):
                naive.append(ts.date())
        elif ts > report_time:
            future.append(ts.astimezone(UTC).date())
        else:
            rows.append((ts.astimezone(UTC), row))
    timezone_check = _item(
        "timezone",
        "timestamps",
        naive,
        "fail",
        "{n} bar{s} {have} no time zone.".format(**_words(invalid_time))
        if invalid_time
        else "Every bar has a time zone.",
        "Every timestamp must be aware.",
        count=invalid_time,
    )
    return rows, timezone_check, future


def _read_daily_rows(
    rows: list[tuple[datetime, dict[str, object]]],
    closes: Mapping[date, datetime],
    report_time: datetime,
    symbol: str,
) -> _DailyRows:
    observed = _DailyRows()
    seen: set[datetime] = set()
    previous: datetime | None = None
    for ts, row in rows:
        day = ts.date()
        if previous is not None and ts <= previous:
            observed.disorder.append(day)
        previous = ts
        if ts in seen:
            observed.duplicates.append(day)
        seen.add(ts)
        if day not in closes:
            observed.non_sessions.append(day)
        aligned = DAILY.is_aligned(ts)
        if not aligned:
            observed.off_grid.append(day)
        end = closes[day] if day in closes else ts + DAY
        if end > report_time:
            observed.partial.append(day)
            continue
        observed.completed += 1
        if row["volume"] == 0:
            observed.zeros.append(day)
        on_grid = day in closes and aligned
        repeated = day in observed.visible
        if on_grid:
            observed.visible.add(day)
        try:
            bar = Bar.model_validate({**row, "ts": ts, "symbol": symbol})
        except ValidationError:
            observed.invalid.append(day)
        else:
            if on_grid and not repeated:
                observed.valid[day] = bar
        if repeated:
            observed.valid.pop(day, None)
    return observed


def _mechanical_checks(
    observed: _DailyRows,
    closes: Mapping[date, datetime],
    report_time: datetime,
    calendar: str | None,
    dates: list[date],
    timezone_check: HealthCheck,
    future: list[date],
) -> list[HealthCheck]:
    first = min(dates, default=report_time.date())
    last = max(observed.visible, default=first)
    window_end = max(dates, default=first)
    expected = [
        day for day, close in closes.items() if first <= day <= window_end and close <= report_time
    ]
    gaps = [
        expected[i]
        for gap in missing_slot_ranges(
            {i for i, d in enumerate(expected) if d in observed.visible}, len(expected)
        )
        for i in gap
    ]
    tail = [day for day, end in closes.items() if day > last and end <= report_time]
    return [
        timezone_check,
        _fault(
            "increasing",
            "timestamps",
            observed.disorder,
            "{n} bar{s} {are} out of time order.",
            "Bars are in time order.",
            "Strictly increasing in source order.",
        ),
        _fault(
            "daily_grid",
            "timestamps",
            observed.off_grid,
            "{n} bar{s} {are} not stamped at midnight UTC.",
            "Every bar is stamped at midnight UTC.",
            "Daily session dates start at 00:00 UTC.",
        ),
        _item(
            "non_session",
            "timestamps",
            observed.non_sessions,
            "fail" if calendar else "not-applicable",
            (
                "{n} bar{s} fall{vs} on a day the exchange was closed.".format(
                    **_words(len(observed.non_sessions))
                )
                if observed.non_sessions
                else "Every bar falls on a trading day."
            )
            if calendar
            else "Crypto trades every day.",
            calendar or "24/7",
        ),
        _fault(
            "future_bar",
            "timestamps",
            sorted(future),
            "{n} bar{s} {are} dated after the check time.",
            "No bar is dated after the check time.",
            "Timestamp ≤ report time.",
        ),
        _fault(
            "partial_bar",
            "timestamps",
            observed.partial,
            "{n} bar{s} had not closed by the check time.",
            "Every bar had closed by the check time.",
            "Session close or next UTC midnight ≤ report time.",
        ),
        _item(
            "stale_tail",
            "timestamps",
            tail if len(tail) > TAIL_SESSIONS else [],
            "warn",
            f"The data stops {len(tail)} sessions before the check time."
            if len(tail) > TAIL_SESSIONS
            else "The data is up to date.",
            f">{TAIL_SESSIONS} completed sessions.",
        ),
        _fault(
            "duplicate_timestamps",
            "gaps",
            observed.duplicates,
            "{n} bar{s} repeat{vs} the time of an earlier bar.",
            "No two bars share a time.",
            "One bar per timestamp.",
        ),
        _fault(
            "ohlcv",
            "gaps",
            observed.invalid,
            "{n} bar{s} {have} impossible prices or volume.",
            "Every bar has possible prices and volume.",
            "Finite positive prices within low/high and finite nonnegative volume.",
        ),
        _fault(
            "missing_sessions",
            "gaps",
            gaps,
            f"{{n}} of {len(expected)} trading days {{have}} no bar.",
            "No trading day is missing.",
            f"warn above 0, fail above {MISSING_SHARE:.0%} of expected bars",
            "fail" if len(gaps) > len(expected) * MISSING_SHARE else "warn",
        ),
        _fault(
            "zero_volume",
            "gaps",
            observed.zeros,
            f"{{n}} of {observed.completed} bars {{have}} zero volume.",
            "Every bar has volume.",
            f"warn above 0, fail above {ZERO_SHARE:.0%} of completed bars",
            "fail" if len(observed.zeros) > observed.completed * ZERO_SHARE else "warn",
        ),
    ]


def health_report(
    bars: pl.DataFrame,
    *,
    symbol: str,
    report_time: datetime,
    calendar: str | None = "XNYS",
    actions: Sequence[CorporateAction] = (),
    peers: Sequence[pl.DataFrame] = (),
    universe_bars: Mapping[str, pl.DataFrame] | None = None,
    memberships: Sequence[UniverseMembership] | None = None,
) -> HealthReport:
    """Audit raw date-keyed daily bars. A null calendar selects the continuous UTC grid."""
    if not _aware(report_time) or report_time.utcoffset() != timedelta(0):
        raise DataError("health report time must be aware UTC")
    if bars.is_empty():
        raise DataError("no daily bars to audit")
    today = report_time.date()
    rows, timezone_check, future = _timestamped_rows(bars, report_time)
    splits = [
        a
        for a in known_actions(actions, today)
        if a.action_type == ActionType.SPLIT and a.symbol == symbol
    ]
    dates = [ts.date() for ts, _ in rows]
    first = min(dates, default=today)
    closes = (
        daily_session_closes(
            calendar,
            min([first, *(a.ex_date for a in splits)]),
            max([today, *(a.ex_date for a in splits)]),
            present=set(dates),
        )
        if calendar
        else {
            first + DAY * i: datetime.combine(first + DAY * (i + 1), time.min, UTC)
            for i in range((today - first).days + 1)
        }
    )
    slots = {d: i for i, d in enumerate(closes)}
    observed = _read_daily_rows(rows, closes, report_time, symbol)
    runs = _bar_runs(observed.valid, slots)
    moves = _peer_moves(peers, closes, report_time, slots) if calendar else {}
    items = [
        *_adjustments(runs, splits, calendar is None, slots, moves),
        *_mechanical_checks(observed, closes, report_time, calendar, dates, timezone_check, future),
        *_price_checks(runs),
        _survivorship(universe_bars, memberships, report_time),
    ]
    return HealthReport(
        symbol=symbol, report_time=report_time, checks=tuple(items), verdict=worst(items)
    )
