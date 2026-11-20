"""A rule-test run's scored returns as calendar-month returns, and what kind of asset it traded.

Only arithmetic on the run's own stored numbers lives here: compounding and a completeness rule.
No statistic is defined here.

Completeness rule. The stored equity is sampled at each bar's open, so the return between two
neighbouring samples belongs to the day of the first one. A calendar month is complete when
every trading day of the asset in that month is a scored date, and the bar after the month's last
trading day is a scored date too (the last day's return ends there), and each scored date is
followed by the asset's next bar. A month that starts or ends inside the scored period, or has
a gap, is left out and reported.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

from alpha_data.context.osap_portfolios import month_end

if TYPE_CHECKING:
    from alpha_cli.spine.stores import ResolvedAsset
    from alpha_cli.toolbox.inputs import Target

US_ASSET_CLASSES = frozenset(("stock", "etf"))


@dataclass(frozen=True)
class MonthlyReturns:
    """Compounded returns of the complete calendar months; ``incomplete`` lists the rest."""

    months: tuple[date, ...]
    returns: tuple[float, ...]
    incomplete: tuple[date, ...]
    first_day: date
    last_day: date


def compound_complete_months(
    stamps: Sequence[datetime], returns: Sequence[float], trading_days: Sequence[date]
) -> MonthlyReturns:
    """Compound interval returns (one per scored date but the last) into complete months."""
    if len(returns) != len(stamps) - 1:
        raise ValueError("one return is needed for each scored date except the last")
    dates = [stamp.date() for stamp in stamps]
    scored = {day: index for index, day in enumerate(dates)}
    calendar = sorted(set(trading_days))
    following = dict(pairwise(calendar))
    by_month: dict[date, list[date]] = {}
    for day in calendar:
        by_month.setdefault(month_end(day), []).append(day)
    months: list[date] = []
    values: list[float] = []
    incomplete: list[date] = []
    for end in sorted({month_end(day) for day in dates}):
        days = by_month.get(end, [])
        ok = bool(days) and all(
            day in scored
            and scored[day] + 1 < len(dates)
            and following.get(day) == dates[scored[day] + 1]
            for day in days
        )
        if not ok:
            incomplete.append(end)
            continue
        months.append(end)
        values.append(math.prod(1.0 + returns[scored[day]] for day in days) - 1.0)
    return MonthlyReturns(tuple(months), tuple(values), tuple(incomplete), dates[0], dates[-1])


def _resolved(home: Path, target: Target) -> ResolvedAsset:
    from alpha_cli.spine.stores import resolve_asset

    meta = target.manifest["metadata"]
    return resolve_asset(f"{meta['symbol']}@{target.manifest['spine']['store']}", data_dir=home)


def bar_dates(home: Path, target: Target) -> list[date]:
    """The asset's stored daily bar dates up to the run's last timestamp; no price is read."""
    import polars as pl

    path = _resolved(home, target).daily_store()._bars_path(target.manifest["metadata"]["symbol"])
    stamps = pl.scan_parquet(path).select("ts").filter(pl.col("ts") <= target.last_ts).collect()
    return [stamp.date() for stamp in stamps["ts"].sort().to_list()]


def us_asset_class(home: Path, target: Target) -> tuple[str | None, str]:
    """The asset kind and what it rests on: ("stock" | "etf" | "other" | None, basis).

    1. A stored dataset identity decides alone (basis "identity").
    2. Legacy provenance carries only the source name, so the kind is inferred (basis "calendar")
       when the source is an equity source and every stored bar date is a session of the US
       equity calendar (XNYS; XNAS has the same session days). A 24/7 market has weekend bars and
       fails this. The ticker text is never read. The inferred kind is "etf", so the fund
       caution is always printed.
    3. A crypto source is "other"; anything else is None (cannot tell).
    """
    from alpha_cli.spine.setup_costs import CRYPTO_PROVIDERS, EQUITY_PROVIDERS

    resolved = _resolved(home, target)
    provenance = resolved.daily_store().read_provenance(target.manifest["metadata"]["symbol"])
    dataset = provenance.get("dataset") if provenance else None
    if isinstance(dataset, dict):
        kind = dataset.get("asset_class")
        us = kind in US_ASSET_CLASSES and dataset.get("venue") == "US"
        return (str(kind) if us else "other"), "identity"
    if not provenance:
        return None, "none"
    parts = set(str(provenance["source"]).lower().split(":"))
    if parts & CRYPTO_PROVIDERS:
        return "other", "none"
    days = bar_dates(home, target)
    if parts & EQUITY_PROVIDERS and days and set(days) <= set(_us_sessions(days[0], days[-1])):
        return "etf", "calendar"
    return None, "none"


def _us_sessions(first: date, last: date) -> list[date]:
    from alpha_data.sessions import daily_session_closes

    # Unlike sessions_between, this builds the calendar from the first date, so old bars work.
    return sorted(daily_session_closes("XNYS", first, last))


def scored_monthly(home: Path, target: Target) -> MonthlyReturns:
    """The run's after-cost scored returns as complete calendar months."""
    frame = target.table("stored_equity", "ts", "equity")
    stamps = target.dates(frame, "stored_equity")
    return compound_complete_months(
        stamps, target.scored_returns().tolist(), bar_dates(home, target)
    )
