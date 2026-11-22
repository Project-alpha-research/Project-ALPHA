"""Sharpe-ratio controls: probability, record length, multiple-testing haircut, backtest length."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result, Value
from alpha_cli.toolbox.families.overfit_controls_base import (
    BASIS,
    NO_TRIES,
    POOR,
    TRIES,
    Sample,
    blank,
    check,
    sample,
    tries,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

BENCH = Param(
    "benchmark_sharpe", float, 0.0, None, "Yearly Sharpe ratio the true Sharpe is compared with."
)
CONFIDENCE = Param("confidence", float, 0.95, (0.9, 0.95, 0.99), "Confidence level wanted.")


def _variance(data: Sample) -> float:
    """Sharpe estimator variance factor 1 - g3*SR + (g4 - 1)/4*SR^2 (Mertens 2002)."""
    from scipy import stats

    skew = float(stats.skew(data.returns, bias=True))
    kurt = float(stats.kurtosis(data.returns, fisher=False, bias=True))
    sr = data.sharpe_bar
    factor = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if factor <= 0.0:
        raise ValueError(f"Sharpe standard error is non-positive (variance factor {factor})")
    return factor


def probabilistic(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_validation import probabilistic_sharpe_ratio

    keys = ("sharpe", "benchmark", "probability", "bars")
    data = sample(inputs)
    if data.reason:
        return blank(keys, data.reason, bars=data.bars)
    bench = params["benchmark_sharpe"]
    chance = probabilistic_sharpe_ratio(data.returns, benchmark_sr=bench / math.sqrt(data.ppy))
    values: dict[str, Value] = {
        "sharpe": data.sharpe,
        "benchmark": bench,
        "probability": chance,
        "bars": data.bars,
    }
    return Result(values, {}, basis=BASIS)


def track_record(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from scipy import stats

    keys = ("sharpe", "min_bars", "min_years", "bars")
    data = sample(inputs)
    if data.reason:
        return blank(keys, data.reason, bars=data.bars)
    gap = data.sharpe_bar - params["benchmark_sharpe"] / math.sqrt(data.ppy)
    if gap <= 0.0:
        reason = (
            "The run's Sharpe ratio is not above the benchmark, so no record length shows it is."
        )
        return blank(keys, reason, sharpe=data.sharpe, bars=data.bars)
    z = float(stats.norm.ppf(params["confidence"]))
    needed = 1.0 + _variance(data) * (z / gap) ** 2
    values: dict[str, Value] = {
        "sharpe": data.sharpe,
        "min_bars": needed,
        "min_years": needed / data.ppy,
    }
    return Result({**values, "bars": data.bars}, {}, basis=BASIS)


def haircut(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from scipy import special, stats

    keys = (
        "sharpe",
        "trials",
        "t_stat",
        "p_value",
        "adjusted_p_value",
        "adjusted_sharpe",
        "haircut",
        "bars",
    )
    data = sample(inputs)
    if data.reason:
        return blank(keys, data.reason, bars=data.bars)
    count = tries(inputs, params)
    if count is None:
        return blank(keys, NO_TRIES, sharpe=data.sharpe, bars=data.bars)
    if data.sharpe <= 0.0:
        return blank(keys, POOR, sharpe=data.sharpe, trials=count, bars=data.bars)
    t_stat = data.sharpe_bar * math.sqrt(data.bars)
    # Work on the log of the tail so a very large t-statistic does not underflow to zero.
    log_p = math.log(2.0) + float(stats.norm.logsf(t_stat))
    log_adjusted = min(0.0, math.log(count) + log_p)
    p_value, adjusted = math.exp(log_p), math.exp(log_adjusted)
    adjusted_t = -float(special.ndtri_exp(log_adjusted - math.log(2.0)))
    shrunk = adjusted_t / math.sqrt(data.years)
    values: dict[str, Value] = {
        "sharpe": data.sharpe,
        "trials": count,
        "t_stat": t_stat,
        "p_value": p_value,
        "adjusted_p_value": adjusted,
        "adjusted_sharpe": shrunk,
        "haircut": (data.sharpe - shrunk) / data.sharpe,
        "bars": data.bars,
    }
    return Result(values, {}, basis=BASIS)


def backtest_length(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("trials", "target_sharpe", "min_years", "run_years", "run_bars")
    data = sample(inputs)
    if data.reason:
        return blank(keys, data.reason, run_bars=data.bars)
    count = tries(inputs, params)
    if count is None:
        return blank(keys, NO_TRIES, run_years=data.years, run_bars=data.bars)
    target = params["target_sharpe"] or data.sharpe
    if target <= 0.0:
        reason = "The target Sharpe ratio must be above zero."
        return blank(keys, reason, trials=count, run_years=data.years, run_bars=data.bars)
    values: dict[str, Value] = {
        "trials": count,
        "target_sharpe": target,
        "min_years": 2.0 * math.log(count) / target**2,
        "run_years": data.years,
        "run_bars": data.bars,
    }
    return Result(values, {}, basis=BASIS)


def _out(key: str, label: str, gloss: str, unit: Any) -> Output:
    return Output(key, label, gloss, unit)


PROBABILISTIC_SHARPE = check(
    "probabilistic_sharpe",
    "How likely is the true Sharpe ratio to beat a benchmark Sharpe ratio?",
    answers=("Could the Sharpe ratio be luck on a short, uneven history?",),
    situations=("looks-too-good", "risk-adjusted"),
    params=(BENCH,),
    outputs=(
        _out(
            "probability",
            "Probability",
            "Chance the true Sharpe ratio is above the benchmark.",
            "fraction",
        ),
        _out(
            "sharpe",
            "Sharpe ratio",
            "Yearly Sharpe ratio of the scored after-cost returns.",
            "ratio",
        ),
        _out("benchmark", "Benchmark", "Yearly Sharpe ratio it is compared with.", "ratio"),
        _out("bars", "Scored bars", "Number of scored bar returns.", "count"),
    ),
    reading=(
        "The chance that the true Sharpe ratio is above {benchmark:.2f} is {probability:.1%}."
        " The run's Sharpe ratio was {sharpe:.2f} over {bars} bars."
    ),
    caveat="It allows for skew, fat tails and history length (Bailey and Lopez de Prado"
    " 2012, eq. 9)"
    " but counts no tries: see overfit_controls.deflated_at_tries.",
    compute=probabilistic,
)
MIN_TRACK_RECORD = check(
    "min_track_record",
    "How long a record is needed to trust this Sharpe ratio over a benchmark?",
    answers=("How many years of history does this Sharpe ratio need?",),
    situations=("looks-too-good", "risk-adjusted"),
    params=(BENCH, CONFIDENCE),
    outputs=(
        _out(
            "min_bars",
            "Bars needed",
            "Bars of history at which the Sharpe ratio beats the benchmark.",
            "count",
        ),
        _out("min_years", "Years needed", "The same length in years.", "ratio"),
        _out(
            "sharpe",
            "Sharpe ratio",
            "Yearly Sharpe ratio of the scored after-cost returns.",
            "ratio",
        ),
        _out("bars", "Scored bars", "Number of scored bar returns.", "count"),
    ),
    reading=(
        "At this Sharpe ratio of {sharpe:.2f}, about {min_bars:.0f} bars ({min_years:.1f} years)"
        " are needed to beat the benchmark at the chosen confidence. The run has {bars} bars."
    ),
    caveat="It assumes the observed Sharpe ratio is the true one (Bailey and Lopez de Prado"
    " 2012, eq. 11)."
    " A lucky Sharpe ratio gives a short, falsely comforting length.",
    compute=track_record,
)
HAIRCUT_SHARPE = check(
    "haircut_sharpe",
    "How much should this Sharpe ratio be cut for the number of tries?",
    answers=("How much of this Sharpe ratio survives the number of tries?",),
    situations=("many-tries", "looks-too-good"),
    params=(TRIES,),
    outputs=(
        _out(
            "haircut",
            "Haircut",
            "Share of the Sharpe ratio removed after allowing for the tries.",
            "fraction",
        ),
        _out(
            "adjusted_sharpe",
            "Adjusted Sharpe",
            "Yearly Sharpe ratio after the Bonferroni adjustment.",
            "ratio",
        ),
        _out(
            "sharpe",
            "Sharpe ratio",
            "Yearly Sharpe ratio of the scored after-cost returns.",
            "ratio",
        ),
        _out("trials", "Tries counted", "Number of tries the adjustment allows for.", "count"),
        _out(
            "t_stat",
            "t-statistic",
            "Sharpe ratio times the square root of the years of history.",
            "ratio",
        ),
        _out("p_value", "p-value", "Two-sided normal p-value of the t-statistic.", "p_value"),
        _out(
            "adjusted_p_value",
            "Adjusted p-value",
            "The p-value times the tries, at most 1.",
            "p_value",
        ),
        _out("bars", "Scored bars", "Number of scored bar returns.", "count"),
    ),
    reading=(
        "A Sharpe ratio of {sharpe:.2f} becomes {adjusted_sharpe:.2f} after allowing for"
        " {trials} tries,"
        " a cut of {haircut:.0%} (adjusted p-value {adjusted_p_value:.3f})."
    ),
    caveat="Bonferroni adjustment of one p-value (Harvey and Liu 2015). The Holm"
    " and BHY versions need"
    " the p-values of all tries, which one run does not hold.",
    compute=haircut,
)
MIN_BACKTEST_LENGTH = check(
    "min_backtest_length",
    "How many years of history are needed for this many tries?",
    answers=("Is the history long enough for the number of tries made?",),
    situations=("many-tries", "looks-too-good"),
    kind="diagnostic",
    params=(
        TRIES,
        Param("target_sharpe", float, 0.0, None, "Yearly Sharpe ratio to reach. 0 uses the run's."),
    ),
    outputs=(
        _out(
            "min_years",
            "Years needed",
            "Years at which luck alone is not expected to reach the Sharpe ratio.",
            "ratio",
        ),
        _out("run_years", "Years in the run", "Years of scored history.", "ratio"),
        _out("trials", "Tries counted", "Number of tries allowed for.", "count"),
        _out("target_sharpe", "Sharpe ratio", "Yearly Sharpe ratio looked at.", "ratio"),
        _out("run_bars", "Scored bars", "Number of scored bar returns.", "count"),
    ),
    reading=(
        "With {trials} tries, luck alone is expected to reach a Sharpe ratio of {target_sharpe:.2f}"
        " on histories shorter than about {min_years:.1f} years. This run has {run_years:.1f}."
    ),
    caveat="It uses the upper bound 2 ln(N) / SR^2 (Bailey, Borwein, Lopez de Prado and Zhu 2014)"
    " for independent tries; correlated tries need less.",
    compute=backtest_length,
)
CHECKS = (PROBABILISTIC_SHARPE, MIN_TRACK_RECORD, HAIRCUT_SHARPE, MIN_BACKTEST_LENGTH)
