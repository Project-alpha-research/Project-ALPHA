"""Return-shape statistics of the stored equity curve: gain-to-pain, kappa, Lo, Cornish-Fisher."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec, Value
from alpha_cli.toolbox.families.performance_stats_common import (
    EQUITY_BASIS,
    POISON,
    TESTS,
    stored_returns,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

FLAT = "The stored returns do not vary, so the Sharpe ratio is undefined."


def gain_to_pain(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = ("gain_to_pain", "return_sum", "loss_sum")
    returns, reason = stored_returns(inputs.stored)
    if returns is None:
        return unavailable(keys, reason)
    total = math.fsum(returns)
    losses = math.fsum(returns[returns < 0])
    values: dict[str, Value] = {"return_sum": total, "loss_sum": losses, "gain_to_pain": None}
    reasons = {}
    if np.any(returns < 0):
        values["gain_to_pain"] = total / abs(losses)
    else:
        reasons["gain_to_pain"] = "No losing bars in the stored equity curve."
    return Result(values, reasons, basis=EQUITY_BASIS)


GAIN_TO_PAIN = ToolSpec(
    id="performance.gain_to_pain",
    situations=("risk-adjusted",),
    answers=("How much did the run gain for each unit of summed losses?",),
    family="performance",
    question="What was the total return per unit of summed losses?",
    needs=("stored_equity",),
    params=(),
    outputs=(
        Output(
            "gain_to_pain",
            "Gain-to-pain ratio",
            "Sum of all bar returns divided by the absolute sum of the losing bar returns"
            " (Schwager 2012).",
            "ratio",
        ),
        Output("return_sum", "Summed returns", "Sum of every bar return.", "fraction"),
        Output("loss_sum", "Summed losses", "Sum of the losing bar returns.", "fraction"),
    ),
    reading=(
        "Bar returns summed to {return_sum:.1%} against summed losses of {loss_sum:.1%}, a"
        " gain-to-pain ratio of {gain_to_pain:.2f}."
    ),
    caveats=(
        "Schwager used monthly returns; with daily bars every small loss counts. It cannot"
        " tell you how the losses were spread in time.",
    ),
    reference=TESTS + "test_gain_to_pain",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=gain_to_pain,
)


def kappa(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = ("kappa", "upside_potential_ratio", "lower_partial_moment")
    returns, reason = stored_returns(inputs.stored)
    if returns is None:
        return unavailable(keys, reason)
    order, threshold = params["order"], params["threshold"]
    moment = float(np.mean(np.maximum(threshold - returns, 0.0) ** order))
    if moment <= 0:
        return unavailable(keys, "No bar return fell below the threshold.")
    kappa_value = (float(np.mean(returns)) - threshold) / moment ** (1 / order)
    upside = float(np.mean(np.maximum(returns - threshold, 0.0)))
    second = float(np.mean(np.maximum(threshold - returns, 0.0) ** 2))
    values: dict[str, Value] = {
        "kappa": kappa_value,
        "upside_potential_ratio": upside / math.sqrt(second),
        "lower_partial_moment": moment,
    }
    return Result(values, {}, basis=EQUITY_BASIS, params={"order": order, "threshold": threshold})


KAPPA = ToolSpec(
    id="performance.kappa",
    situations=("risk-adjusted",),
    answers=("What is the return per unit of downside risk of a chosen order?",),
    family="performance",
    question="How large was the average return relative to its shortfalls below a threshold?",
    needs=("stored_equity",),
    params=(
        Param(
            "order",
            int,
            3,
            (1, 2, 3, 4),
            "Order of the lower partial moment; 1 is Omega minus one, 2 is Sortino.",
        ),
        Param(
            "threshold",
            float,
            0.0,
            (-0.01, -0.005, -0.001, 0.0, 0.001, 0.005, 0.01),
            "Bar return counted as the minimum acceptable one.",
        ),
    ),
    outputs=(
        Output(
            "kappa",
            "Kappa",
            "Mean bar return minus the threshold, divided by the lower partial moment of the"
            " chosen order to the power one over that order (Kaplan and Knowles 2004), per bar.",
            "ratio",
        ),
        Output(
            "upside_potential_ratio",
            "Upside-potential ratio",
            "Mean bar return above the threshold divided by the root of the order-2 lower"
            " partial moment (Sortino, van der Meer and Plantinga 1999), per bar.",
            "ratio",
        ),
        Output(
            "lower_partial_moment",
            "Lower partial moment",
            "Mean of the shortfall below the threshold, raised to the chosen order.",
            "ratio",
        ),
    ),
    reading=(
        "Kappa was {kappa:.3f} and the upside-potential ratio {upside_potential_ratio:.3f}"
        " per bar, against the chosen threshold."
    ),
    caveats=(
        "Both are per bar, not yearly, and cannot tell you which threshold you should accept.",
    ),
    reference=TESTS + "test_kappa",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=kappa,
)


def lo_sharpe(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = ("sharpe", "adjusted_sharpe", "first_autocorrelation", "lags_used")
    returns, reason = stored_returns(inputs.stored)
    if returns is None:
        return unavailable(keys, reason)
    q = inputs.stored.ppy
    centred = returns - np.mean(returns)
    total = float(centred @ centred)
    if total <= 0:
        return unavailable(keys, FLAT)
    lags = min(params["max_lag"], len(returns) - 1, q - 1)
    rho = [float(centred[k:] @ centred[:-k]) / total for k in range(1, lags + 1)]
    spread = q + 2 * math.fsum((q - k) * r for k, r in enumerate(rho, start=1))
    per_bar = float(np.mean(returns)) / float(np.std(returns, ddof=1))
    values: dict[str, Value] = {
        "sharpe": per_bar * math.sqrt(q),
        "adjusted_sharpe": None,
        "first_autocorrelation": rho[0] if rho else None,
        "lags_used": lags,
    }
    reasons = {}
    if spread > 0:
        values["adjusted_sharpe"] = per_bar * q / math.sqrt(spread)
    else:
        reasons["adjusted_sharpe"] = "The estimated serial correlation makes the variance term"
        reasons["adjusted_sharpe"] += " not positive."
    if not rho:
        reasons["first_autocorrelation"] = "No lag could be estimated."
    return Result(values, reasons, basis=EQUITY_BASIS, params={"max_lag": params["max_lag"]})


LO_SHARPE = ToolSpec(
    id="performance.lo_sharpe",
    situations=(
        "risk-adjusted",
        "looks-too-good",
    ),
    answers=("What is the yearly Sharpe ratio once serial correlation is counted?",),
    family="performance",
    question="What is the yearly Sharpe ratio after allowing for serial correlation in returns?",
    needs=("stored_equity",),
    params=(
        Param(
            "max_lag",
            int,
            10,
            range(1, 61),
            "Most bar lags of autocorrelation counted (Lo's sum is cut here, and at the number"
            " of bars per year minus one).",
        ),
    ),
    outputs=(
        Output(
            "sharpe",
            "Plain yearly Sharpe",
            "Mean over standard deviation of bar returns, times the square root of bars per year.",
            "ratio",
        ),
        Output(
            "adjusted_sharpe",
            "Autocorrelation-adjusted Sharpe",
            "Bar Sharpe times q over the root of q plus twice the sum over lags k of (q minus k)"
            " times the lag-k autocorrelation, with q the bars per year (Lo 2002, the eta(q)"
            " factor).",
            "ratio",
        ),
        Output(
            "first_autocorrelation",
            "First-lag autocorrelation",
            "Correlation of each bar return with the one before it.",
            "ratio",
        ),
        Output("lags_used", "Lags counted", "Number of lags in the correction sum.", "count"),
    ),
    reading=(
        "The yearly Sharpe was {sharpe:.2f} plain and {adjusted_sharpe:.2f} adjusted for serial"
        " correlation (first-lag autocorrelation {first_autocorrelation:.3f})."
    ),
    caveats=(
        "Lo's sum runs over all lags up to a year; this check cuts it at the chosen lag, and"
        " autocorrelations estimated from a short run are noisy. It cannot tell you the cause.",
    ),
    reference=TESTS + "test_lo_sharpe",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=lo_sharpe,
)


CHECKS = (GAIN_TO_PAIN, KAPPA, LO_SHARPE)
