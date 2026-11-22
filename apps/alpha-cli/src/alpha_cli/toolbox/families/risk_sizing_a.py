"""Loss-size checks on the scored returns: parametric and Cornish-Fisher VaR, worst windows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result
from alpha_cli.toolbox.families.risk_common import (
    BASIS,
    CONFIDENCE,
    PAST,
    bar_returns,
    check,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

TESTS = "test_toolbox_risk_sizing_a"
MINIMUM = 30


def _sample(inputs: Inputs) -> tuple[FloatArray, str | None]:
    returns = bar_returns(inputs)
    if len(returns) < MINIMUM:
        return returns, f"Needs at least {MINIMUM} scored bar returns; found {len(returns)}."
    if returns.min() == returns.max():
        return returns, "A loss estimate needs varying scored returns."
    return returns, None


def parametric_var(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np
    from scipy import stats

    from alpha_validation.metrics import value_at_risk

    keys = ("normal_var", "t_var", "t_df", "historical_var")
    returns, why = _sample(inputs)
    if why:
        return unavailable(keys, why)
    level = params["confidence"]
    # RiskMetrics (1996): the loss at the normal quantile of the fitted mean and deviation.
    normal = -(float(returns.mean()) + float(returns.std(ddof=1)) * stats.norm.ppf(1 - level))
    values: dict[str, Any] = {
        "normal_var": max(0.0, float(normal)),
        "historical_var": value_at_risk(returns, confidence=level),
    }
    df, loc, scale = stats.t.fit(returns)
    quantile = -float(stats.t.ppf(1 - level, df, loc=loc, scale=scale))
    sd = float(returns.std(ddof=1))
    # Many flat bars (out of the market) pull the fit onto zero: a tiny scale and a tail weight
    # below two (no finite spread). Such a fit says nothing about a loss, so it is not shown.
    if np.isfinite([df, scale, quantile]).all() and df > 2.0 and scale > 1e-3 * sd:
        values.update(t_var=max(0.0, quantile), t_df=float(df))
        return Result(values, {}, basis=BASIS)
    values.update(t_var=None, t_df=None)
    reason = (
        "The Student-t fit did not give a usable tail, often because many bars were flat"
        " (out of the market)."
    )
    return Result(values, {"t_var": reason, "t_df": reason}, basis=BASIS)


def cornish_fisher_var(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from scipy import stats

    keys = ("cf_var", "normal_var", "skew", "excess_kurtosis", "historical_var")
    returns, why = _sample(inputs)
    if why:
        return unavailable(keys, why)
    from alpha_validation.metrics import value_at_risk

    z = float(stats.norm.ppf(1 - params["confidence"]))
    skew, kurt = float(stats.skew(returns)), float(stats.kurtosis(returns))
    mean, sd = float(returns.mean()), float(returns.std(ddof=1))
    # Zangari (1996); Favre and Galeano (2002), eq. 3: the quantile moved by skew and kurtosis.
    z_cf = (
        z + (z**2 - 1) * skew / 6 + (z**3 - 3 * z) * kurt / 24 - (2 * z**3 - 5 * z) * skew**2 / 36
    )
    slope = 1 + z * skew / 3 + (3 * z**2 - 3) * kurt / 24 - (6 * z**2 - 5) * skew**2 / 36
    values: dict[str, Any] = {
        "normal_var": max(0.0, -(mean + sd * z)),
        "skew": skew,
        "excess_kurtosis": kurt,
        "historical_var": value_at_risk(returns, confidence=params["confidence"]),
        "cf_var": max(0.0, -(mean + sd * z_cf)),
    }
    if slope <= 0:
        values["cf_var"] = None
        reason = (
            "Skew and kurtosis are too large for the Cornish-Fisher expansion to hold at this"
            " level."
        )
        return Result(values, {"cf_var": reason}, basis=BASIS)
    return Result(values, {}, basis=BASIS)


CHECKS = (
    check(
        "risk.parametric_var",
        TESTS,
        question="How large a loss does a bell-curve fit give for one bar?",
        answers=("How big a loss should I expect on a bad bar?",),
        situations=("drawdown", "return-range"),
        needs=("stored_equity",),
        params=(CONFIDENCE,),
        outputs=(
            Output("normal_var", "Normal loss", "Loss per bar from a normal fit.", "fraction"),
            Output("t_var", "Student-t loss", "Loss per bar from a Student-t fit.", "fraction"),
            Output(
                "t_df", "Student-t degrees of freedom", "Fitted tail weight: small is fat.", "ratio"
            ),
            Output(
                "historical_var",
                "Historical loss",
                "Loss per bar at the same level read straight from the history.",
                "fraction",
            ),
        ),
        reading=(
            "At the chosen level a bar lost {normal_var:.2%} with a normal fit, {t_var:.2%} with a"
            " Student-t fit and {historical_var:.2%} in the history itself."
        ),
        caveats=(PAST + " A bell-curve fit usually understates the tail.",),
        compute=parametric_var,
    ),
    check(
        "risk.cornish_fisher_var",
        TESTS,
        question="How much does skew and fat tails change the one-bar loss figure?",
        answers=("Does the loss figure change when returns are skewed?",),
        situations=("drawdown", "return-range"),
        needs=("stored_equity",),
        params=(CONFIDENCE,),
        outputs=(
            Output(
                "cf_var",
                "Cornish-Fisher loss",
                "Loss per bar after the skew and kurtosis fix.",
                "fraction",
            ),
            Output(
                "normal_var", "Normal loss", "Loss per bar from a plain normal fit.", "fraction"
            ),
            Output(
                "skew",
                "Skew",
                "Sample skewness of bar returns; negative means a longer loss tail.",
                "ratio",
            ),
            Output(
                "excess_kurtosis",
                "Excess kurtosis",
                "Sample kurtosis minus 3; positive means fatter tails.",
                "ratio",
            ),
            Output(
                "historical_var",
                "Historical loss",
                "Loss per bar at the same level from the history.",
                "fraction",
            ),
        ),
        reading=(
            "The loss per bar was {cf_var:.2%} after allowing for skew {skew:.2f} and excess"
            " kurtosis"
            " {excess_kurtosis:.2f}, against {normal_var:.2%} for a plain normal fit."
        ),
        caveats=(PAST + " The expansion is unreliable when skew and kurtosis are very large.",),
        compute=cornish_fisher_var,
    ),
)
