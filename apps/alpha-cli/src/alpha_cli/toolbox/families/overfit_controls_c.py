"""Sample-size and evidence controls: required history, sequential test, shrunk Sharpe ratio."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np

from alpha_cli.toolbox.contract import Output, Param, Result, Value
from alpha_cli.toolbox.families.overfit_controls_base import BASIS, blank, check, sample

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

ALPHA = 0.05  # one-sided size of the history-length calculation (the library's default)
POSITIVE = "The {name} must be above zero."


def required_history(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from scipy import stats

    from alpha_research import required_observations_known_sigma

    keys = ("required_bars", "required_years", "detectable_sharpe", "run_bars", "run_years")
    data = sample(inputs, spread=False)
    if data.reason:
        return blank(keys, data.reason, run_bars=data.bars)
    target, power = params["target_sharpe"], params["power"]
    if target <= 0.0:
        reason = POSITIVE.format(name="target Sharpe ratio")
        return blank(keys, reason, run_bars=data.bars, run_years=data.years)
    need = required_observations_known_sigma(
        target / math.sqrt(data.ppy), 0.0, 1.0, alpha=ALPHA, target_power=power
    )
    z = float(stats.norm.ppf(1.0 - ALPHA) + stats.norm.ppf(power))
    values: dict[str, Value] = {
        "required_bars": need,
        "required_years": need / data.ppy,
        "detectable_sharpe": z / math.sqrt(data.years),
        "run_bars": data.bars,
        "run_years": data.years,
    }
    return Result(values, {}, basis=BASIS)


def sequential(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("outcome", "first_crossing_bar", "llr", "lower_limit", "upper_limit", "bars")
    data = sample(inputs)
    if data.reason:
        return blank(keys, data.reason, bars=data.bars)
    if params["target_sharpe"] <= 0.0:
        return blank(keys, POSITIVE.format(name="target Sharpe ratio"), bars=data.bars)
    sigma = float(data.returns.std(ddof=1))
    mu = params["target_sharpe"] / math.sqrt(data.ppy) * sigma
    upper = math.log((1.0 - params["beta"]) / params["alpha"])
    lower = math.log(params["beta"] / (1.0 - params["alpha"]))
    llr = np.cumsum(mu * data.returns - mu * mu / 2.0) / sigma**2
    hits = np.flatnonzero((llr >= upper) | (llr <= lower))
    values: dict[str, Any] = {
        "outcome": "no limit reached",
        "first_crossing_bar": None,
        "llr": float(llr[-1]),
        "lower_limit": lower,
        "upper_limit": upper,
        "bars": data.bars,
    }
    reasons = {"first_crossing_bar": f"No limit was crossed in {data.bars} bars."}
    if hits.size:
        values["first_crossing_bar"] = int(hits[0]) + 1
        values["outcome"] = (
            "favours the target Sharpe" if llr[hits[0]] >= upper else "favours no edge"
        )
        reasons = {}
    return Result(values, reasons, basis=BASIS)


def shrunk(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("shrunk_sharpe", "sharpe", "standard_error", "shrink_weight", "prior_sd", "bars")
    data = sample(inputs)
    if data.reason:
        return blank(keys, data.reason, bars=data.bars)
    prior = params["prior_sd"]
    if prior <= 0.0:
        return blank(keys, POSITIVE.format(name="prior spread"), bars=data.bars)
    # Lo (2002): the variance of an iid Sharpe estimate is (1 + SR^2 / 2) / n, per bar.
    error = math.sqrt((1.0 + 0.5 * data.sharpe_bar**2) / data.bars) * math.sqrt(data.ppy)
    weight = prior**2 / (prior**2 + error**2)
    values: dict[str, Value] = {
        "shrunk_sharpe": weight * data.sharpe,
        "sharpe": data.sharpe,
        "standard_error": error,
        "shrink_weight": weight,
        "prior_sd": prior,
        "bars": data.bars,
    }
    return Result(values, {}, basis=BASIS)


def _out(key: str, label: str, gloss: str, unit: Any) -> Output:
    return Output(key, label, gloss, unit)


REQUIRED_HISTORY = check(
    "required_history",
    "How much history is needed to detect a Sharpe ratio of a given size?",
    answers=("How many years would it take to tell a real edge from luck?",),
    situations=("looks-too-good", "risk-adjusted"),
    kind="diagnostic",
    params=(
        Param("target_sharpe", float, 0.5, None, "Yearly Sharpe ratio to detect."),
        Param("power", float, 0.9, (0.8, 0.9, 0.95), "Chance of detecting it when it is real."),
    ),
    outputs=(
        _out(
            "required_bars",
            "Bars needed",
            "Bars of history to detect the target Sharpe ratio.",
            "count",
        ),
        _out("required_years", "Years needed", "The same length in years.", "ratio"),
        _out(
            "detectable_sharpe",
            "Smallest detectable Sharpe",
            "Smallest yearly Sharpe ratio this run's length detects.",
            "ratio",
        ),
        _out("run_bars", "Scored bars", "Number of scored bar returns.", "count"),
        _out("run_years", "Years in the run", "Years of scored history.", "ratio"),
    ),
    reading=(
        "Detecting a yearly Sharpe ratio of the target size takes about {required_bars} bars"
        " ({required_years:.1f} years). This run has {run_bars} bars"
        " ({run_years:.1f} years); at that"
        " length the smallest Sharpe ratio it can detect is {detectable_sharpe:.2f}."
    ),
    caveat="It assumes independent, equal-spread bar returns and a one-sided 5% test. Real returns"
    " need more history. It uses no result of this run beyond its length and bars per year.",
    compute=required_history,
)
SEQUENTIAL_TEST = check(
    "sequential_test",
    "Did the evidence reach a limit of a sequential likelihood-ratio test?",
    answers=("Could this run have been stopped early without inflating error?",),
    situations=("few-trades", "looks-too-good"),
    params=(
        Param("target_sharpe", float, 1.0, None, "Yearly Sharpe ratio tested against zero."),
        Param(
            "alpha",
            float,
            0.05,
            (0.01, 0.05, 0.1),
            "Chance of favouring the target when there is no edge.",
        ),
        Param(
            "beta",
            float,
            0.2,
            (0.1, 0.2, 0.3),
            "Chance of favouring no edge when the target is real.",
        ),
    ),
    outputs=(
        _out("outcome", "Evidence", "Which side the first limit crossed favours.", "text"),
        _out(
            "first_crossing_bar",
            "First crossing",
            "Bar at which a limit was first crossed.",
            "count",
        ),
        _out(
            "llr",
            "Final log-likelihood ratio",
            "Evidence for the target over zero at the last bar.",
            "ratio",
        ),
        _out("lower_limit", "Lower limit", "Crossing it favours no edge.", "ratio"),
        _out("upper_limit", "Upper limit", "Crossing it favours the target Sharpe ratio.", "ratio"),
        _out("bars", "Scored bars", "Number of scored bar returns.", "count"),
    ),
    reading=(
        "The evidence {outcome}. The log-likelihood ratio ended at {llr:.2f}; the limits were"
        " {lower_limit:.2f} and {upper_limit:.2f}."
    ),
    caveat="Wald's sequential test (1945) assumes normal bar returns with known spread; the spread"
    " here comes from the same history. Looking at a finished run is not a"
    " pre-planned stopping rule.",
    compute=sequential,
)
SHRUNK_SHARPE = check(
    "shrunk_sharpe",
    "What is the Sharpe ratio after shrinking it toward a sceptical prior?",
    answers=("What Sharpe ratio is left after doubting the result?",),
    situations=("looks-too-good", "risk-adjusted"),
    kind="diagnostic",
    params=(
        Param(
            "prior_sd",
            float,
            0.5,
            None,
            "Spread of the sceptical prior for the yearly Sharpe ratio, centred on zero.",
        ),
    ),
    outputs=(
        _out("shrunk_sharpe", "Shrunk Sharpe", "Posterior mean yearly Sharpe ratio.", "ratio"),
        _out(
            "sharpe",
            "Sharpe ratio",
            "Yearly Sharpe ratio of the scored after-cost returns.",
            "ratio",
        ),
        _out(
            "standard_error",
            "Standard error",
            "Yearly standard error of the Sharpe ratio.",
            "ratio",
        ),
        _out(
            "shrink_weight",
            "Weight kept",
            "Share of the Sharpe ratio kept after shrinking.",
            "fraction",
        ),
        _out("prior_sd", "Prior spread", "Spread of the prior used.", "ratio"),
        _out("bars", "Scored bars", "Number of scored bar returns.", "count"),
    ),
    reading=(
        "A Sharpe ratio of {sharpe:.2f} shrinks to {shrunk_sharpe:.2f} with a prior spread of"
        " {prior_sd:.2f}; {shrink_weight:.0%} of the observed value is kept."
    ),
    caveat="A normal prior centred on zero and a normal estimate give this update (Gelman and"
    " others,"
    " Bayesian Data Analysis, 3rd ed.); the prior spread is your choice and moves the answer."
    " It does not count tries: use overfit_controls.haircut_sharpe for that.",
    compute=shrunk,
)
CHECKS = (REQUIRED_HISTORY, SEQUENTIAL_TEST, SHRUNK_SHARPE)
