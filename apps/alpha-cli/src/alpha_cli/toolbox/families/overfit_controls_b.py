"""Luck benchmarks and hurdles: best-of-noise Sharpe, deflated probability, t-hurdle, trades."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from scipy import stats

from alpha_cli.toolbox.contract import Output, Param, Result, Value
from alpha_cli.toolbox.families.overfit_controls_base import (
    BASIS,
    NO_TRIES,
    TRADE_BASIS,
    TRIES,
    Sample,
    blank,
    check,
    closed_trades,
    sample,
    tries,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs


def _noise_bar(data: Sample, count: int) -> float:
    """Expected best per-bar Sharpe of ``count`` zero-skill tries, each with variance 1/bars."""
    from alpha_validation import expected_max_sharpe

    return expected_max_sharpe(1.0 / data.bars, count)


def noise_best(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("noise_sharpe", "sharpe", "trials", "bars")
    data = sample(inputs)
    if data.reason:
        return blank(keys, data.reason, bars=data.bars)
    count = tries(inputs, params)
    if count is None:
        return blank(keys, NO_TRIES, sharpe=data.sharpe, bars=data.bars)
    values: dict[str, Value] = {
        "noise_sharpe": _noise_bar(data, count) * math.sqrt(data.ppy),
        "sharpe": data.sharpe,
        "trials": count,
        "bars": data.bars,
    }
    return Result(values, {}, basis=BASIS)


def deflated(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_validation import probabilistic_sharpe_ratio

    keys = ("probability", "benchmark", "sharpe", "trials", "bars")
    data = sample(inputs)
    if data.reason:
        return blank(keys, data.reason, bars=data.bars)
    count = tries(inputs, params)
    if count is None:
        return blank(keys, NO_TRIES, sharpe=data.sharpe, bars=data.bars)
    bench = _noise_bar(data, count)
    chance = probabilistic_sharpe_ratio(data.returns, benchmark_sr=bench)
    values: dict[str, Value] = {
        "probability": chance,
        "benchmark": bench * math.sqrt(data.ppy),
        "sharpe": data.sharpe,
        "trials": count,
        "bars": data.bars,
    }
    return Result(values, {}, basis=BASIS)


def hurdle(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("t_stat", "p_value", "hurdle", "hurdle_p_value", "bars")
    data = sample(inputs)
    if data.reason:
        return blank(keys, data.reason, bars=data.bars)
    level = params["hurdle"]
    t_stat = data.sharpe_bar * math.sqrt(data.bars)
    values: dict[str, Value] = {
        "t_stat": t_stat,
        "p_value": 2.0 * float(stats.norm.sf(abs(t_stat))),
        "hurdle": level,
        "hurdle_p_value": 2.0 * float(stats.norm.sf(level)),
        "bars": data.bars,
    }
    return Result(values, {}, basis=BASIS)


def trade_count(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_validation import wilson_interval

    keys = ("trades", "reference", "win_rate", "win_rate_lower", "win_rate_upper")
    pnl = closed_trades(inputs)
    known: dict[str, Any] = {"trades": len(pnl), "reference": params["reference_trades"]}
    if len(pnl) < 1:
        reason = "A win rate needs at least 1 closed trade."
        return blank(keys, reason, TRADE_BASIS, **known)
    box = wilson_interval(int((pnl > 0).sum()), len(pnl))
    known.update(win_rate=box.point, win_rate_lower=box.lower, win_rate_upper=box.upper)
    return Result(known, {}, basis=TRADE_BASIS)


def _out(key: str, label: str, gloss: str, unit: Any) -> Output:
    return Output(key, label, gloss, unit)


NOISE_BEST_SHARPE = check(
    "noise_best_sharpe",
    "What best Sharpe ratio would pure noise reach with this many tries?",
    answers=("What Sharpe ratio would luck alone give after this many tries?",),
    situations=("many-tries", "looks-too-good"),
    kind="control",
    params=(TRIES,),
    outputs=(
        _out(
            "noise_sharpe",
            "Best-of-noise Sharpe",
            "Expected best yearly Sharpe ratio of zero-skill tries.",
            "ratio",
        ),
        _out(
            "sharpe",
            "Sharpe ratio",
            "Yearly Sharpe ratio of the scored after-cost returns.",
            "ratio",
        ),
        _out("trials", "Tries counted", "Number of tries allowed for.", "count"),
        _out("bars", "Scored bars", "Number of scored bar returns.", "count"),
    ),
    reading=(
        "Across {trials} tries of pure noise on this much history, the best yearly Sharpe ratio"
        " averages about {noise_sharpe:.2f}. This run's was {sharpe:.2f}."
    ),
    caveat="It assumes independent tries with equal spread (false strategy theorem, Bailey and"
    " Lopez"
    " de Prado 2014, eq. 6). Correlated tries give a lower bar.",
    compute=noise_best,
)
DEFLATED_AT_TRIES = check(
    "deflated_at_tries",
    "Does the Sharpe ratio beat luck if a stated number of tries was made?",
    answers=("Would this Sharpe ratio still stand out if I had tried N variants?",),
    situations=("many-tries", "looks-too-good"),
    params=(TRIES,),
    outputs=(
        _out(
            "probability",
            "Deflated probability",
            "Chance the true Sharpe ratio beats best-of-noise.",
            "fraction",
        ),
        _out(
            "benchmark",
            "Best-of-noise Sharpe",
            "Yearly Sharpe ratio luck is expected to reach.",
            "ratio",
        ),
        _out(
            "sharpe",
            "Sharpe ratio",
            "Yearly Sharpe ratio of the scored after-cost returns.",
            "ratio",
        ),
        _out("trials", "Tries counted", "Number of tries allowed for.", "count"),
        _out("bars", "Scored bars", "Number of scored bar returns.", "count"),
    ),
    reading=(
        "With {trials} tries, luck is expected to reach a Sharpe ratio of {benchmark:.2f}."
        " The chance this run's Sharpe ratio of {sharpe:.2f} beats that is {probability:.1%}."
    ),
    caveat="Unlike overfit.deflated_sharpe it takes the try count from you, and it sets the"
    " spread of"
    " the tries to that of pure noise (Bailey and Lopez de Prado 2014, eq. 9).",
    compute=deflated,
)
T_STAT_HURDLE = check(
    "t_stat_hurdle",
    "Is the t-statistic of the mean return above the multiple-testing hurdle?",
    answers=("Is the t-statistic high enough for a strategy found by searching?",),
    situations=("many-tries", "looks-too-good"),
    params=(Param("hurdle", float, 3.0, None, "t-statistic used as the reference level."),),
    outputs=(
        _out("t_stat", "t-statistic", "Mean bar return over its standard error.", "ratio"),
        _out("hurdle", "Reference t-statistic", "The reference level used.", "ratio"),
        _out("p_value", "p-value", "Two-sided normal p-value of the t-statistic.", "p_value"),
        _out(
            "hurdle_p_value",
            "p-value at the reference",
            "Two-sided normal p-value of the reference.",
            "p_value",
        ),
        _out("bars", "Scored bars", "Number of scored bar returns.", "count"),
    ),
    reading=(
        "The t-statistic was {t_stat:.2f} (p-value {p_value:.4f}) against a reference of"
        " {hurdle:.1f} (p-value {hurdle_p_value:.4f})."
    ),
    caveat="A t-statistic of about 3 is the level Harvey, Liu and Zhu (2016) suggest for new"
    " factors."
    " It assumes independent bar returns, which overstates the t-statistic if they are not.",
    compute=hurdle,
)
TRADE_COUNT = check(
    "trade_count",
    "Is the sample big enough for any claim about the win rate?",
    answers=("How many closed trades back this result, and how wide is the win-rate range?",),
    situations=("few-trades",),
    needs="run_trades",
    params=(
        Param("reference_trades", int, 30, range(1, 10_001), "Trade count used as the reference."),
    ),
    outputs=(
        _out("trades", "Closed trades", "Number of closed trades.", "count"),
        _out("reference", "Reference count", "Trade count it is compared with.", "count"),
        _out(
            "win_rate", "Win rate", "Share of closed trades with a profit above zero.", "fraction"
        ),
        _out("win_rate_lower", "Lower limit", "Lower end of the 95% Wilson interval.", "fraction"),
        _out("win_rate_upper", "Upper limit", "Upper end of the 95% Wilson interval.", "fraction"),
    ),
    reading=(
        "The run closed {trades} trades; the reference is {reference}. The win rate was"
        " {win_rate:.1%}, with a Wilson range of {win_rate_lower:.1%} to {win_rate_upper:.1%}."
    ),
    caveat="Thirty trades is a rule of thumb, not a proven limit. The range counts a win as a"
    " profit"
    " above zero and does not say how large the wins and losses were.",
    compute=trade_count,
)
CHECKS = (NOISE_BEST_SHARPE, DEFLATED_AT_TRIES, T_STAT_HURDLE, TRADE_COUNT)
