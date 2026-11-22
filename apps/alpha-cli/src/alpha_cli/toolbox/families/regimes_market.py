"""Regime checks that sort bars by what the stored buy-and-hold market was doing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.regimes_base import (
    MARKET_BASIS,
    MIN_GROUP,
    market_pair,
    spec,
    two_group_outputs,
    two_group_result,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs


def _split(
    inputs: Inputs, params: dict[str, Any], names: tuple[str, str], *, trend: bool
) -> Result:
    """Group the strategy's bars by a past-only market state read at the open that starts each."""
    import numpy as np

    _, strategy, _, levels = market_pair(inputs)
    keys = two_group_keys(names)
    window = params["lookback"]
    if window < 1:
        raise ValueError("lookback must be positive")
    if levels.size <= window:
        return unavailable(
            keys,
            f"Needs more than {window} bars to read the market state; found {levels.size}.",
        )
    state = np.full(levels.size, -1, dtype=np.int64)
    ahead = levels[window:]
    behind = levels[:-window]
    if trend:
        step = np.abs(np.diff(levels))
        path = np.convolve(step, np.ones(window), "valid")  # sum of |change| over each window
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(path > 0, np.abs(ahead - behind) / path, np.nan)
        state[window:] = np.where(np.isnan(ratio), -1, np.where(ratio >= params["threshold"], 0, 1))
    else:
        state[window:] = np.where(ahead > behind, 0, np.where(ahead < behind, 1, -1))
    first, second = strategy[state == 0], strategy[state == 1]
    if first.size < MIN_GROUP or second.size < MIN_GROUP:
        return unavailable(
            keys,
            f"Needs at least {MIN_GROUP} bars in each state; found {first.size} and {second.size}.",
        )
    return two_group_result(
        first, second, names, basis=MARKET_BASIS, extra={"unlabelled_bars": int((state < 0).sum())}
    )


def two_group_keys(names: tuple[str, str]) -> tuple[str, ...]:
    a, b = names
    return (f"{a}_mean", f"{b}_mean", "gap", "p_value", f"{a}_bars", f"{b}_bars")


LOOKBACK = Param(
    "lookback", int, 126, None, "Number of bars of market history that define the state."
)


def bull_bear(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    return _split(inputs, params, ("bull", "bear"), trend=False)


BULL_BEAR = spec(
    "regimes.bull_bear",
    "Does it earn in both rising and falling markets?",
    ("stored_benchmark",),
    two_group_outputs(
        ("bull", "bear"), ("rising market", "falling market"), "when the market was in that state"
    ),
    "When the market had risen over the look-back the rule earned {bull_mean:.4%} per bar,"
    " against {bear_mean:.4%} when it had fallen (p-value of the gap {p_value:.3f}).",
    "The state uses only market moves before each bar, but the split is one simple trend rule."
    " Few market turns in the history means few independent bear periods.",
    "test_bull_bear_known_answer",
    bull_bear,
    params=(LOOKBACK,),
)


def trend_range(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    return _split(inputs, params, ("trend", "range"), trend=True)


TREND_RANGE = spec(
    "regimes.trend_range",
    "Does it earn in trending markets, in sideways markets, or both?",
    ("stored_benchmark",),
    two_group_outputs(
        ("trend", "range"), ("trending", "sideways"), "when the market was in that state"
    ),
    "In trending stretches the rule earned {trend_mean:.4%} per bar, against {range_mean:.4%} in"
    " sideways stretches (p-value of the gap {p_value:.3f}).",
    "Trending means the market's efficiency ratio over the look-back (Kaufman 1995: net move"
    " divided by the sum of the bar moves) was at or above the threshold. The threshold is a"
    " convention, not a law.",
    "test_trend_range_known_answer",
    trend_range,
    params=(
        Param("lookback", int, 20, None, "Number of bars of market history that define the state."),
        Param(
            "threshold",
            float,
            0.3,
            None,
            "Efficiency ratio at or above which the market counts as trending.",
        ),
    ),
)

BETA_KEYS = ("up_beta", "down_beta", "difference", "p_value", "up_bars", "down_bars")


def asymmetric_beta(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np
    from scipy import stats

    _, strategy, market, _ = market_pair(inputs)
    up, down = market > 0, market < 0
    if up.sum() < MIN_GROUP or down.sum() < MIN_GROUP:
        return unavailable(
            BETA_KEYS,
            f"Needs at least {MIN_GROUP} up bars and {MIN_GROUP} down bars of the market;"
            f" found {int(up.sum())} and {int(down.sum())}.",
        )
    # One regression with a down-bar intercept and slope: each side's fit equals its own fit.
    flag = down.astype(float)
    design = np.column_stack([np.ones_like(market), market, flag, market * flag])
    coef, *_ = np.linalg.lstsq(design, strategy, rcond=None)
    resid = strategy - design @ coef
    dof = strategy.size - 4
    scale = float(resid @ resid) / dof
    if scale <= 0:
        return unavailable(
            BETA_KEYS,
            "The market explains the strategy exactly, so no test applies.",
            bars=int(strategy.size),
        )
    cov = scale * np.linalg.inv(design.T @ design)
    t_stat = float(coef[3] / np.sqrt(cov[3, 3]))
    return Result(
        {
            "up_beta": float(coef[1]),
            "down_beta": float(coef[1] + coef[3]),
            "difference": float(coef[3]),
            "p_value": float(2 * stats.t.sf(abs(t_stat), dof)),
            "up_bars": int(up.sum()),
            "down_bars": int(down.sum()),
        },
        {},
        details={"t_stat": t_stat, "flat_market_bars": int((~up & ~down).sum())},
        basis=MARKET_BASIS,
    )


ASYMMETRIC_BETA = spec(
    "regimes.asymmetric_beta",
    "Is the market exposure larger on down bars than on up bars?",
    ("stored_benchmark",),
    (
        Output(
            "up_beta",
            "Beta on up bars",
            "Slope of strategy return on market return over bars the market rose.",
            "ratio",
        ),
        Output(
            "down_beta",
            "Beta on down bars",
            "Slope of strategy return on market return over bars the market fell.",
            "ratio",
        ),
        Output("difference", "Down minus up", "Down-bar beta minus up-bar beta.", "ratio"),
        Output(
            "p_value",
            "Two-sided p-value",
            "Chance of a difference this large if the two betas were equal (OLS t-test).",
            "p_value",
        ),
        Output("up_bars", "Up bars", "Number of bars the market rose.", "count"),
        Output("down_bars", "Down bars", "Number of bars the market fell.", "count"),
    ),
    "The rule's market beta was {up_beta:.2f} on up bars and {down_beta:.2f} on down bars"
    " (difference {difference:.2f}, p-value {p_value:.3f}).",
    "Beta here is the slope against the stored buy-and-hold line, with ordinary least squares"
    " standard errors that ignore clustered volatility. A larger down beta means losses follow"
    " the market down more than gains follow it up.",
    "test_asymmetric_beta_known_answer",
    asymmetric_beta,
)
