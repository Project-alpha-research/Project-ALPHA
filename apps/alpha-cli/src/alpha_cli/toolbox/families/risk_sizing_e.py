"""Backtests of the historical loss figure on the scored returns: Kupiec and Christoffersen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.risk_common import (
    BASIS,
    CONFIDENCE,
    PAST,
    bar_returns,
    check,
    unavailable,
)

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

    BoolArray = npt.NDArray[np.bool_]

TESTS = "test_toolbox_risk_sizing_b"
MIN_EVALUATED = 50
HISTORY = Param(
    "min_history",
    int,
    60,
    range(20, 2001),
    "Bars of history before the first loss figure is tested.",
)


def breach_flags(returns: FloatArray, level: float, history: int) -> BoolArray:
    """True where a bar lost more than the historical loss figure known before it."""
    import numpy as np

    from alpha_validation.metrics import value_at_risk

    flags = [
        bool(returns[i] < -value_at_risk(returns[:i], confidence=level))
        for i in range(history, len(returns))
    ]
    return np.array(flags, dtype=bool)


def _flags(inputs: Inputs, params: dict[str, Any]) -> tuple[BoolArray | None, str]:
    returns = bar_returns(inputs)
    evaluated = len(returns) - params["min_history"]
    if evaluated < MIN_EVALUATED:
        return None, (
            f"Needs at least {MIN_EVALUATED} bars after the first {params['min_history']};"
            f" found {max(evaluated, 0)}."
        )
    return breach_flags(returns, params["confidence"], params["min_history"]), ""


def _uc_statistic(breaches: int, n: int, p: float) -> float:
    from scipy.special import xlogy

    rate = breaches / n
    null = xlogy(n - breaches, 1 - p) + xlogy(breaches, p)
    alt = xlogy(n - breaches, 1 - rate) + xlogy(breaches, rate)
    return max(0.0, float(-2 * (null - alt)))


def var_coverage(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from scipy import stats

    keys = ("evaluated", "breaches", "expected_breaches", "breach_rate", "lr", "p_value")
    flags, why = _flags(inputs, params)
    if flags is None:
        return unavailable(keys, why)
    n, x, p = len(flags), int(flags.sum()), 1 - params["confidence"]
    # Kupiec (1995), eq. 5: likelihood ratio of the observed breach rate to the stated rate.
    lr = _uc_statistic(x, n, p)
    values = {
        "evaluated": n,
        "breaches": x,
        "expected_breaches": n * p,
        "breach_rate": x / n,
        "lr": lr,
        "p_value": float(stats.chi2.sf(lr, 1)),
    }
    return Result(values, {}, basis=BASIS)


def var_independence(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from scipy import stats
    from scipy.special import xlogy

    keys = (
        "breaches",
        "breach_after_breach",
        "breach_after_calm",
        "lr_independence",
        "p_independence",
        "lr_conditional",
        "p_conditional",
    )
    flags, why = _flags(inputs, params)
    if flags is None:
        return unavailable(keys, why)
    n, x = len(flags), int(flags.sum())
    if x == 0 or x == n:
        empty: dict[str, Any] = dict.fromkeys(keys)
        empty["breaches"] = x
        reason = (
            "No breach was seen, so independence cannot be read."
            if x == 0
            else ("Every bar was a breach, so independence cannot be read.")
        )
        return Result(empty, {k: reason for k in keys if k != "breaches"}, basis=BASIS)
    before, after = flags[:-1], flags[1:]
    n00, n01 = int((~before & ~after).sum()), int((~before & after).sum())
    n10, n11 = int((before & ~after).sum()), int((before & after).sum())
    p01 = n01 / (n00 + n01) if n00 + n01 else 0.0
    p11 = n11 / (n10 + n11) if n10 + n11 else 0.0
    pooled = (n01 + n11) / (n00 + n01 + n10 + n11)
    null = xlogy(n00 + n10, 1 - pooled) + xlogy(n01 + n11, pooled)
    alt = xlogy(n00, 1 - p01) + xlogy(n01, p01) + xlogy(n10, 1 - p11) + xlogy(n11, p11)
    lr_ind = max(0.0, float(-2 * (null - alt)))
    # Christoffersen (1998): coverage test plus a first-order Markov test for clustering.
    lr_cc = _uc_statistic(x, n, 1 - params["confidence"]) + lr_ind
    values: dict[str, Any] = {
        "breaches": x,
        "breach_after_breach": p11 if n10 + n11 else None,
        "breach_after_calm": p01 if n00 + n01 else None,
        "lr_independence": lr_ind,
        "p_independence": float(stats.chi2.sf(lr_ind, 1)),
        "lr_conditional": lr_cc,
        "p_conditional": float(stats.chi2.sf(lr_cc, 2)),
    }
    reasons = {k: "No pair of bars began with that state." for k, v in values.items() if v is None}
    return Result(values, reasons, basis=BASIS)


CHECKS = (
    check(
        "risk.var_coverage",
        TESTS,
        question="Did losses beyond the loss figure happen as often as the figure says?",
        answers=("Is my loss estimate too low?",),
        situations=("drawdown", "return-range"),
        needs=("stored_equity",),
        params=(CONFIDENCE, HISTORY),
        outputs=(
            Output("evaluated", "Bars tested", "Bars after the first history window.", "count"),
            Output(
                "breaches",
                "Breaches",
                "Bars that lost more than the loss figure known before them.",
                "count",
            ),
            Output(
                "expected_breaches",
                "Expected breaches",
                "Breaches the stated level allows.",
                "count",
            ),
            Output("breach_rate", "Breach rate", "Breaches divided by bars tested.", "fraction"),
            Output(
                "lr", "Kupiec statistic", "Likelihood ratio of observed to stated rate.", "ratio"
            ),
            Output(
                "p_value",
                "p-value",
                "Chance of a gap this large if the stated rate were right (chi-square, 1 df).",
                "p_value",
            ),
        ),
        reading=(
            "{breaches} of {evaluated} bars lost more than the loss figure; the stated level"
            " expects"
            " {expected_breaches:.1f} (p-value {p_value:.3f}; a small p-value means the rate"
            " differs)."
        ),
        caveats=(PAST + " The loss figure for each bar uses only earlier bars.",),
        compute=var_coverage,
        cost="seconds",
    ),
    check(
        "risk.var_independence",
        TESTS,
        question="Do the loss-figure breaches bunch together?",
        answers=("Do my worst bars come in clusters?",),
        situations=("drawdown", "trade-streaks"),
        needs=("stored_equity",),
        params=(CONFIDENCE, HISTORY),
        outputs=(
            Output(
                "breaches",
                "Breaches",
                "Bars that lost more than the loss figure known before them.",
                "count",
            ),
            Output(
                "breach_after_breach",
                "Breach after a breach",
                "Share of breaches followed by another.",
                "fraction",
            ),
            Output(
                "breach_after_calm",
                "Breach after a calm bar",
                "Share of calm bars followed by a breach.",
                "fraction",
            ),
            Output(
                "lr_independence",
                "Independence statistic",
                "Likelihood ratio for clustering.",
                "ratio",
            ),
            Output(
                "p_independence",
                "Independence p-value",
                "Chance of this much clustering if breaches were independent.",
                "p_value",
            ),
            Output(
                "lr_conditional",
                "Coverage and independence statistic",
                "Kupiec plus independence statistic.",
                "ratio",
            ),
            Output(
                "p_conditional",
                "Joint p-value",
                "Chance of a gap this large on rate and clustering together (chi-square, 2 df).",
                "p_value",
            ),
        ),
        reading=(
            "{breaches} breaches. A breach followed another {breach_after_breach:.1%} of the"
            " time against"
            " {breach_after_calm:.1%} after a calm bar (independence p-value {p_independence:.3f},"
            " joint p-value {p_conditional:.3f})."
        ),
        caveats=(PAST + " With few breaches these tests have little power.",),
        compute=var_independence,
        cost="seconds",
    ),
)
