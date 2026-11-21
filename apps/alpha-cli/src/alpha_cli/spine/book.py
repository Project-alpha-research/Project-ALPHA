"""The portfolio book maths: how stored runs moved together, and follows as one paper account.

Pure arithmetic on values the caller already read. Nothing here opens a file, runs the engine
or reads a bar. Readings only: no pass or fail, no advice.

Correlation is the Pearson correlation of simple daily returns. The returns are taken between
the dates both runs have, so two runs with different calendars are compared over the same
intervals. Under `MIN_COMMON_DAYS` common days no correlation is given.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import combinations, pairwise
from typing import Any, TypedDict

MIN_COMMON_DAYS = 60
TOO_FEW = "too few common days to read"
NOT_DEFINED = "not defined: the returns of one run do not change"
CORRELATE_NOTICE = "Readings of stored runs only. Not advice."
ACCOUNT_NOTICE = "Paper only. Forward use; not research. Not advice."


@dataclass(frozen=True)
class DailySeries:
    """One run's stored equity by day. `held[i]` says whether the run was in the market over
    the interval that ends on `days[i]`; `held[0]` has no interval and is not read."""

    run_id: str
    days: tuple[date, ...]
    equity: tuple[float, ...]
    held: tuple[bool, ...] | None
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.equity) != len(self.days):
            raise ValueError(f"run {self.run_id}: needs one equity value per day")
        if any(before >= after for before, after in pairwise(self.days)):
            raise ValueError(f"run {self.run_id}: days must be strictly increasing, one per day")
        if any(not math.isfinite(value) or value <= 0 for value in self.equity):
            raise ValueError(f"run {self.run_id}: stored equity must be finite and positive")
        if self.held is not None and len(self.held) != len(self.days):
            raise ValueError(f"run {self.run_id}: needs one exposure value per day")


def correlation(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Pearson correlation; None when either side does not change (the ratio is 0/0)."""
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("correlation needs two series of the same length, at least 2 values")
    mean_x, mean_y = math.fsum(x) / len(x), math.fsum(y) / len(y)
    dx, dy = [v - mean_x for v in x], [v - mean_y for v in y]
    var_x, var_y = math.fsum(v * v for v in dx), math.fsum(v * v for v in dy)
    if var_x == 0.0 or var_y == 0.0:
        return None
    value = math.fsum(a * b for a, b in zip(dx, dy, strict=True)) / math.sqrt(var_x * var_y)
    if not math.isfinite(value):
        raise ValueError("correlation is not finite")
    return max(-1.0, min(1.0, value))


def _returns(series: DailySeries, common: list[date]) -> list[float]:
    level = dict(zip(series.days, series.equity, strict=True))
    return [level[after] / level[before] - 1.0 for before, after in pairwise(common)]


def _held(series: DailySeries, common: list[date]) -> list[bool] | None:
    """In the market at any time inside each interval between two common dates."""
    if series.held is None:
        return None
    flags = list(zip(series.days, series.held, strict=True))
    return [
        any(flag for day, flag in flags if before < day <= after)
        for before, after in pairwise(common)
    ]


def _moved(value: float) -> str:
    size = abs(value)
    if size < 0.3:
        return "moved mostly independently"
    how = "closely" if size >= 0.7 else "partly"
    return f"moved {how} together" if value > 0 else f"moved {how} in opposite directions"


def _sentence(pair: dict[str, Any]) -> str:
    a, b = pair["runs"]
    n = pair["common_days"]
    head = f"Runs {a} and {b}: "
    if pair["correlation_reason"] == TOO_FEW:
        return f"{head}{n} common day{'s' if n != 1 else ''}: {TOO_FEW}."
    if pair["correlation"] is None:
        body = f"daily returns over {n} common days: {pair['correlation_reason']}"
    else:
        body = (
            f"daily returns {_moved(pair['correlation'])} "
            f"(correlation {pair['correlation']:.2f}) over {n} common days"
        )
    if pair["overlap_share"] is None:
        return f"{head}{body}; time in the market together: {pair['overlap_reason']}."
    return f"{head}{body}; both were in the market on {pair['overlap_share']:.0%} of them."


def pair_reading(a: DailySeries, b: DailySeries) -> dict[str, Any]:
    """Correlation of daily returns over the common dates, and the share of days both held."""
    common = sorted(set(a.days) & set(b.days))
    n = max(len(common) - 1, 0)
    value: float | None = None
    reason: str | None = TOO_FEW
    if n >= MIN_COMMON_DAYS:
        value = correlation(_returns(a, common), _returns(b, common))
        reason = None if value is not None else NOT_DEFINED
    both: int | None = None
    overlap_reason: str | None = None
    held_a, held_b = _held(a, common), _held(b, common)
    if n == 0:
        overlap_reason = "no common days"
    elif held_a is None or held_b is None:
        missing = a.run_id if held_a is None else b.run_id
        overlap_reason = f"run {missing} stored no exposure"
    else:
        both = sum(1 for x, y in zip(held_a, held_b, strict=True) if x and y)
    pair: dict[str, Any] = {
        "runs": [a.run_id, b.run_id],
        "common_days": n,
        "first_day": common[1].isoformat() if n else None,
        "last_day": common[-1].isoformat() if n else None,
        "correlation": value,
        "correlation_reason": reason,
        "both_in_market_days": both,
        "overlap_share": None if both is None else both / n,
        "overlap_reason": overlap_reason,
    }
    return {**pair, "sentence": _sentence(pair)}


def correlate(series: Sequence[DailySeries]) -> dict[str, Any]:
    """Every pair of 2 to 8 runs, in the order given."""
    if not 2 <= len(series) <= 8:
        raise ValueError("correlate needs 2 to 8 runs")
    if len({s.run_id for s in series}) != len(series):
        raise ValueError("a run is named twice")
    return {
        "min_common_days": MIN_COMMON_DAYS,
        "runs": [
            {
                "run_id": s.run_id,
                "labels": list(s.labels),
                "days": len(s.days),
                "first_day": s.days[0].isoformat() if s.days else None,
                "last_day": s.days[-1].isoformat() if s.days else None,
            }
            for s in series
        ],
        "pairs": [pair_reading(a, b) for a, b in combinations(series, 2)],
    }


def render_correlate(result: dict[str, Any]) -> str:
    lines = [
        "Daily returns from the stored walk-forward equity of each run, on the dates they share.",
        *[pair["sentence"] for pair in result["pairs"]],
    ]
    for run in result["runs"]:
        if run.get("reserve_sentence"):
            lines.append(f"Run {run['run_id']}: {run['reserve_sentence']}")
        lines.append(f"{run['run_id']} labels: {', '.join(run['labels']) or 'none'}")
    return "\n".join([*lines, CORRELATE_NOTICE])


class AccountRow(TypedDict):
    """One active follow: its fixed paper size and whether its paper position is open."""

    follow_id: str
    name: str
    assets: list[str]
    size_pct: float
    open: bool


def account_view(rows: Sequence[AccountRow]) -> dict[str, Any]:
    """Every follow as a share of ONE paper account: the total, and the sum per asset.

    A size is the follow's fixed paper size, not marked to market. A follow of several assets
    does not record a split, so its full size counts for each of its assets.
    """
    follows: list[dict[str, Any]] = [
        {**row, "in_market_pct": row["size_pct"] if row["open"] else 0.0} for row in rows
    ]
    assets: dict[str, dict[str, Any]] = {}
    for row in follows:
        for asset in row["assets"]:
            entry = assets.setdefault(
                asset, {"asset": asset, "size_pct": 0.0, "in_market_pct": 0.0, "follows": 0}
            )
            entry["size_pct"] += row["size_pct"]
            entry["in_market_pct"] += row["in_market_pct"]
            entry["follows"] += 1
    total = math.fsum(row["size_pct"] for row in follows)
    above = total > 100.0
    return {
        "follows": follows,
        "total_pct": total,
        "in_market_pct": math.fsum(row["in_market_pct"] for row in follows),
        "assets": [assets[name] for name in sorted(assets)],
        "above_account": above,
        "sentence": f"The follows together use {total:g}% of the paper account." if above else None,
    }


def render_account(view: dict[str, Any]) -> str:
    unreadable = [
        f"Not counted: follow {i} cannot be read: run `alpha follow verify {i}`."
        for i in view.get("unreadable", [])
    ]
    if not view["follows"]:
        start = "Start one: alpha follow start --test <run id>"
        return "\n".join(["No active follows yet (paper).", start, *unreadable, ACCOUNT_NOTICE])
    count = len(view["follows"])
    lines = [f"Paper book: {count} active follow(s), each as a share of one paper account."]
    for row in view["follows"]:
        state = "paper position open" if row["open"] else "paper account flat"
        lines.append(
            f"  {row['follow_id']}  {', '.join(row['assets'])}  "
            f"{row['size_pct']:g}% of the paper account; {state}  {row['name']}"
        )
    lines.append(
        f"Total size: {view['total_pct']:g}% of the paper account. "
        f"In the market now: {view['in_market_pct']:g}%."
    )
    lines.append("Per asset:")
    for entry in view["assets"]:
        held_by = f"{entry['follows']} follow{'s' if entry['follows'] != 1 else ''}"
        lines.append(
            f"  {entry['asset']}  {entry['size_pct']:g}% in {held_by}; "
            f"{entry['in_market_pct']:g}% in the market now"
        )
    if view["sentence"]:
        lines.append(view["sentence"])
    lines += unreadable
    lines.append("Sizes are the fixed paper size of each follow, not marked to market.")
    return "\n".join([*lines, ACCOUNT_NOTICE])
