"""Pure descriptive diagnostics; statistical estimators remain in alpha_validation."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import numpy as np

from alpha_cli.spine.plain_ratio import fall_comparison
from alpha_core import ActionType, Bar, CorporateAction, DataError
from alpha_validation.metrics import (
    FloatSeq,
    cagr,
    drawdown_episodes,
    max_drawdown,
    sharpe_ratio,
    to_returns,
)


def score(returns: FloatSeq, ppy: int) -> tuple[float | None, str | None]:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise DataError("diagnostic returns must be a finite vector")
    if len(values) < 2 or np.std(values, ddof=1) <= 0:
        return None, "Sharpe needs at least two returns with nonzero variance"
    return sharpe_ratio(values, periods_per_year=ppy), None


def performance(equity: FloatSeq, ppy: int, basis: str) -> dict[str, Any]:
    returns = to_returns(equity)
    sharpe, reason = score(returns, ppy)
    return {
        "basis": basis,
        "total_return": float(equity[-1] / equity[0] - 1),
        "cagr": cagr(equity, periods_per_year=ppy),
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(equity),
        "reasons": {"sharpe": reason} if reason else {},
    }


def buy_and_hold(bars: Sequence[Bar], dividends: Sequence[CorporateAction]) -> list[float]:
    """One share bought at the opening baseline, with entitled cash held from pay date."""
    from nautilus_trader.model.objects import Price

    from alpha_backtest.instruments import instrument_for

    if not bars:
        raise DataError("buy and hold requires a starting open")
    first = bars[0]
    precision = instrument_for(first.symbol).price_precision
    initial_open = float(Price(first.open, precision))
    if initial_open <= 0:
        raise DataError("benchmark opening price rounds to zero at engine precision")
    payments = []
    for action in dividends:
        if (
            action.symbol != first.symbol
            or action.action_type != ActionType.DIVIDEND
            or action.amount is None
        ):
            raise DataError("expected a cash dividend on the benchmark asset")
        if first.ts.date() < action.ex_date:
            payments.append((max(action.ex_date, action.pay_date or action.ex_date), action.amount))
    payments.sort()
    cash = 0.0
    paid = 0
    growth = []
    for bar in bars:
        while paid < len(payments) and payments[paid][0] <= bar.ts.date():
            cash += payments[paid][1]
            paid += 1
        growth.append((float(Price(bar.open, precision)) + cash) / initial_open)
    return growth


def drawdowns(equity: FloatSeq, benchmark: FloatSeq, dates: Sequence[datetime]) -> dict[str, Any]:
    to_returns(benchmark)
    if len(equity) != len(benchmark) or len(equity) != len(dates):
        raise DataError("drawdown series must have matching dates")
    episodes = []
    for item in drawdown_episodes(equity, top=5):
        start, trough, recovery = item.peak_index, item.trough_index, item.recovery_index
        market = float(benchmark[trough] / benchmark[start] - 1)
        reasons = {}
        share = market / item.depth if market < 0 and item.depth < 0 else None
        if share is None:
            reasons["share_explained"] = "strategy and benchmark must both fall over the window"
        if recovery is None:
            reasons["recovery"] = "not recovered by the last bar"
        episodes.append(
            {
                "start": dates[start].isoformat(),
                "trough": dates[trough].isoformat(),
                "recovery": dates[recovery].isoformat() if recovery is not None else None,
                "depth": item.depth,
                "benchmark_return": market,
                "share_explained": share,
                "reasons": reasons,
            }
        )
    return {
        "basis": "full-sample backtest, peak to trough; benchmark on the same dates",
        "episodes": episodes,
    }


def yearly(equity: FloatSeq, benchmark: FloatSeq, dates: Sequence[datetime]) -> dict[str, Any]:
    strategy, market = to_returns(equity), to_returns(benchmark)
    if len(strategy) != len(market) or len(dates) != len(equity):
        raise DataError("yearly series must have matching dates")
    years = []
    for year in sorted({date.year for date in dates[1:]}):
        mask = np.array([date.year == year for date in dates[1:]])
        years.append(
            {
                "year": year,
                "strategy_return": float(np.prod(1 + strategy[mask]) - 1),
                "benchmark_return": float(np.prod(1 + market[mask]) - 1),
            }
        )
    return {
        "basis": "full-sample returns grouped by ending calendar year; partial years included",
        "years": years,
        "strategy_positive_years": sum(row["strategy_return"] > 0 for row in years),
        "benchmark_positive_years": sum(row["benchmark_return"] > 0 for row in years),
    }


def concentration(profits: FloatSeq) -> dict[str, Any]:
    values = np.asarray(profits, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise DataError("trade profits must be a finite vector")
    reason = (
        "fewer than three closed trades"
        if len(values) < 3
        else ("total closed-trade profit is not positive" if values.sum() <= 0 else None)
    )
    ordered = np.sort(values)[::-1]
    return {
        "basis": "full-sample closed-trade realized profit",
        "top_1": None if reason else float(ordered[0] / values.sum()),
        "top_3": None if reason else float(ordered[:3].sum() / values.sum()),
        "reasons": {"top_1": reason, "top_3": reason} if reason else {},
    }


def delay(returns: FloatSeq, weights: FloatSeq, costs: FloatSeq, ppy: int) -> dict[str, Any]:
    r, w, c = (np.asarray(values, dtype=float) for values in (returns, weights, costs))
    if r.ndim != 1 or r.shape != w.shape or r.shape != c.shape:
        raise DataError("delay inputs must be aligned vectors")
    if not all(np.all(np.isfinite(values)) for values in (r, w, c)):
        raise DataError("delay inputs must be finite")
    base, base_reason = score(w * r - c, ppy)
    delayed, delayed_reason = score(np.r_[0.0, w[:-1]] * r - np.r_[0.0, c[:-1]], ppy)
    # A share of the base is only meaningful against a positive base Sharpe.
    kept: float | None = None
    kept_reason: str | None = "base or delayed Sharpe is unavailable"
    if base is not None and delayed is not None:
        comparable = math.isfinite(base) and base > 0
        kept = delayed / base if comparable else None
        kept_reason = None if comparable else "base Sharpe is not positive, so no share is defined"
    return {
        "basis": "returns-level approximation; weights and turnover costs shifted one bar later",
        "base_sharpe": base,
        "delayed_sharpe": delayed,
        "delayed_share_of_base": kept,
        "reasons": {
            key: reason
            for key, reason in (
                ("base_sharpe", base_reason),
                ("delayed_sharpe", delayed_reason),
                ("delayed_share_of_base", kept_reason),
            )
            if reason
        },
    }


def flags(sections: dict[str, Any]) -> list[dict[str, str]]:
    """Observations from computed numbers, never a verdict."""
    result = []
    base, benchmark = sections["full_sample"]["sharpe"], sections["benchmark"]["sharpe"]
    if base is not None and benchmark is not None and base < benchmark:
        result.append(
            {
                "flag": "below-benchmark",
                "detail": (
                    f"Strategy Sharpe {base:.3g} is below buy-and-hold Sharpe {benchmark:.3g}."
                ),
            }
        )
    episodes = sections["drawdowns"]["episodes"]
    if episodes and (share := episodes[0]["share_explained"]) is not None and share >= 0.5:
        result.append(
            {
                "flag": "drawdown-with-market",
                "detail": (
                    f"During the worst drawdown ({abs(episodes[0].get('depth') or 0.0):.0%}), "
                    f"buy and hold {fall_comparison(share)} the rule over the same dates "
                    f"({abs(episodes[0]['benchmark_return']):.0%})."
                ),
            }
        )
    top = sections["concentration"]["top_3"]
    if top is not None and top >= 0.8:
        result.append(
            {
                "flag": "concentrated-profit",
                "detail": (
                    f"The top three closed trades made {top:.2g} times the total profit; "
                    "the rest lost money overall."
                    if top > 1
                    else f"The top three closed trades contributed {top:.0%} of total profit."
                ),
            }
        )
    positive = base is not None and math.isfinite(base) and base > 0
    for kind, name in (("costs", "fragile-to-costs"), ("parameter", "fragile-to-parameters")):
        weak = [
            v
            for v in sections["sensitivity"]["variants"]
            if v["kind"] == kind
            and v["sharpe"] is not None
            and (v["sharpe"] <= 0 or (positive and v["sharpe"] < base / 2))
        ]
        if weak:
            shown = "unavailable" if base is None else f"{base:.3g}"
            result.append(
                {
                    "flag": name,
                    "detail": (
                        f"A {kind} variant has Sharpe {weak[0]['sharpe']:.3g}; "
                        f"base Sharpe is {shown}."
                    ),
                }
            )
    delay_section = sections["delay"]
    # Older stored passes lack the share; it is derived the same way, for a positive base only.
    base_delay, later = delay_section["base_sharpe"], delay_section["delayed_sharpe"]
    if (
        base_delay is not None
        and later is not None
        and math.isfinite(base_delay)
        and base_delay > 0
        and later < base_delay / 2
    ):
        result.append(
            {
                "flag": "fragile-to-delay",
                "detail": (
                    f"Delaying weights one bar changes surrogate Sharpe "
                    f"from {base_delay:.3g} to {later:.3g}."
                ),
            }
        )
    noise = sections.get("price_noise", {})
    if "fragile-to-price-noise" in noise.get("labels", []):
        result.append({"flag": "fragile-to-price-noise", "detail": noise["sentence"]})
    result.extend(sections.get("plausibility", []))
    return result
