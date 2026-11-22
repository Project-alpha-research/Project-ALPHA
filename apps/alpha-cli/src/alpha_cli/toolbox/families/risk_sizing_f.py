"""Streak and volatility-target checks on closed trades and bar returns."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.risk_common import (
    BASIS,
    PAST,
    TRADE_BASIS,
    bar_returns,
    check,
    closed_trades,
    too_few_trades,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

TESTS = "test_toolbox_risk_sizing_c"
MIN_STREAK_TRADES = 10


def prob_streak(n: int, p: float, length: int) -> float:
    """Chance that n independent trades with loss rate p hold a losing streak of this length.

    Uses the linear recurrence u[m] = u[m-1] - (1-p) p^length u[m-length-1] for the chance of no
    such streak in m trades (Feller 1968, ch. XIII.7), so the cost is linear in n.
    """
    if length > n:
        return 0.0
    tail = (1 - p) * p**length
    none = [1.0] * (n + 1)
    none[length] = 1.0 - p**length
    for m in range(length + 1, n + 1):
        none[m] = none[m - 1] - tail * none[m - length - 1]
    return min(1.0, max(0.0, 1.0 - none[n]))


def expected_longest(n: int, p: float) -> float:
    """Average longest losing streak in n independent trades: the sum of P(longest >= k)."""
    if p >= 1.0:
        return float(n)
    total = 0.0
    for k in range(1, n + 1):
        chance = prob_streak(n, p, k)
        if chance < 1e-15:  # the chance only falls as k grows
            break
        total += chance
    return total


def loss_streaks(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = (
        "trades",
        "loss_rate",
        "longest_losing_streak",
        "expected_longest",
        "p_observed_or_longer",
        "p_streak",
    )
    pnl = closed_trades(inputs).pnl
    if (why := too_few_trades(len(pnl), MIN_STREAK_TRADES)) is not None:
        return unavailable(keys, why, TRADE_BASIS)
    n, longest, run = len(pnl), 0, 0
    for lost in pnl < 0:
        run = run + 1 if lost else 0
        longest = max(longest, run)
    p = float((pnl < 0).mean())
    values: dict[str, Any] = {
        "trades": n,
        "loss_rate": p,
        "longest_losing_streak": longest,
        "expected_longest": expected_longest(n, p),
        "p_observed_or_longer": prob_streak(n, p, longest) if longest else 1.0,
        "p_streak": prob_streak(n, p, params["streak"]),
    }
    return Result(values, {}, basis=TRADE_BASIS)


def vol_target(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view

    from alpha_validation.metrics import max_drawdown

    keys = (
        "bars",
        "raw_sharpe",
        "scaled_sharpe",
        "raw_vol",
        "scaled_vol",
        "raw_max_drawdown",
        "scaled_max_drawdown",
        "average_leverage",
    )
    returns, look = bar_returns(inputs), params["lookback"]
    if len(returns) < look + 30:
        return unavailable(keys, f"Needs {look + 30} scored bar returns; found {len(returns)}.")
    ppy = inputs.stored.ppy
    # Each bar is sized from the deviation of the bars before it, so nothing looks ahead.
    trailing = sliding_window_view(returns, look)[: len(returns) - look].std(axis=1, ddof=1)
    weight = np.full(len(trailing), params["max_leverage"])
    moving = trailing > 0  # A flat window has no volatility to size from, so the cap applies.
    weight[moving] = np.minimum(
        params["target_vol"] / (trailing[moving] * math.sqrt(ppy)), params["max_leverage"]
    )
    raw, scaled = returns[look:], weight * returns[look:]
    values: dict[str, Any] = {"bars": len(raw), "average_leverage": float(weight.mean())}
    reasons = {}
    for label, series in (("raw", raw), ("scaled", scaled)):
        sd = float(series.std(ddof=1))
        values[f"{label}_vol"] = sd * math.sqrt(ppy)
        values[f"{label}_max_drawdown"] = max_drawdown(np.r_[1.0, np.cumprod(1 + series)])
        if sd > 0:
            values[f"{label}_sharpe"] = float(series.mean()) / sd * math.sqrt(ppy)
        else:
            values[f"{label}_sharpe"] = None
            reasons[f"{label}_sharpe"] = "The returns do not vary after the first window."
    return Result(values, reasons, basis=BASIS)


CHECKS = (
    check(
        "risk.loss_streaks",
        TESTS,
        question="How long a losing streak should this loss rate lead you to expect?",
        answers=("How many losses in a row should I expect?",),
        situations=("trade-streaks", "few-trades"),
        needs=("run_trades",),
        params=(
            Param(
                "streak", int, 5, range(2, 51), "Length of losing streak whose chance is reported."
            ),
        ),
        outputs=(
            Output("trades", "Closed trades", "Count of closed trades read.", "count"),
            Output("loss_rate", "Loss rate", "Share of closed trades with a loss.", "fraction"),
            Output(
                "longest_losing_streak",
                "Longest losing streak",
                "Most consecutive losing trades, in entry order.",
                "count",
            ),
            Output(
                "expected_longest",
                "Expected longest streak",
                "Average longest streak if the same trades came in random order.",
                "ratio",
            ),
            Output(
                "p_observed_or_longer",
                "Chance of the observed streak",
                "Chance a random order holds a streak at least as long as the longest seen.",
                "fraction",
            ),
            Output(
                "p_streak",
                "Chance of the chosen streak",
                "Chance a random order holds a losing streak of the chosen length.",
                "fraction",
            ),
        ),
        reading=(
            "The longest losing streak was {longest_losing_streak} in {trades} trades (loss rate"
            " {loss_rate:.0%});"
            " random order would give about {expected_longest:.1f}, and a streak that long or"
            " longer"
            " has a {p_observed_or_longer:.1%} chance."
        ),
        caveats=("It assumes independent trades at a fixed loss rate. " + PAST,),
        compute=loss_streaks,
    ),
    check(
        "risk.vol_target",
        TESTS,
        question="Does scaling the size to a constant volatility help?",
        answers=("What if I sized to a steady volatility?",),
        situations=("risk-adjusted", "calm-or-turbulent"),
        needs=("stored_equity",),
        params=(
            Param(
                "target_vol", float, 0.1, (0.05, 0.1, 0.15, 0.2), "Yearly volatility to size to."
            ),
            Param("lookback", int, 20, range(5, 253), "Bars used to measure recent volatility."),
            Param(
                "max_leverage", float, 2.0, (1.0, 1.5, 2.0, 3.0), "Largest size multiple allowed."
            ),
        ),
        outputs=(
            Output("bars", "Bars compared", "Bars after the first volatility window.", "count"),
            Output(
                "raw_sharpe",
                "Sharpe unscaled",
                "Yearly Sharpe of the same bars at the original size.",
                "ratio",
            ),
            Output(
                "scaled_sharpe",
                "Sharpe scaled",
                "Yearly Sharpe after sizing to the target.",
                "ratio",
            ),
            Output(
                "raw_vol",
                "Volatility unscaled",
                "Yearly volatility at the original size.",
                "fraction",
            ),
            Output(
                "scaled_vol",
                "Volatility scaled",
                "Yearly volatility after sizing to the target.",
                "fraction",
            ),
            Output(
                "raw_max_drawdown",
                "Drawdown unscaled",
                "Deepest peak-to-trough drop at the original size.",
                "fraction",
            ),
            Output(
                "scaled_max_drawdown",
                "Drawdown scaled",
                "Deepest peak-to-trough drop after sizing.",
                "fraction",
            ),
            Output(
                "average_leverage",
                "Average size multiple",
                "Average multiple applied to the original size.",
                "ratio",
            ),
        ),
        reading=(
            "Sizing to the target volatility moved the Sharpe from {raw_sharpe:.2f} to"
            " {scaled_sharpe:.2f},"
            " the volatility from {raw_vol:.1%} to {scaled_vol:.1%} and the deepest drop from"
            " {raw_max_drawdown:.1%} to {scaled_max_drawdown:.1%} (average size"
            " {average_leverage:.2f}x)."
        ),
        caveats=(
            "Each bar is sized from the bars before it, with a cap on the multiple. It ignores the"
            " cost of changing size and of leverage. " + PAST,
        ),
        compute=vol_target,
    ),
)
