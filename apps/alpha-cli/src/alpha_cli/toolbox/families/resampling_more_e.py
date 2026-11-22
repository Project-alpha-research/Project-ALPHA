"""Leave-one-year-out and stress readings on the scored returns."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.resampling_more_common import (
    RETURN_BASIS,
    blank,
    dated_returns,
    make_spec,
    scored,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray


def year_jackknife(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    returns, years = dated_returns(inputs)
    keys = ("total", "lowest", "highest", "driver_year")
    distinct = sorted(set(years))
    if len(distinct) < 2:
        reason = f"The test needs at least 2 calendar years; the run has {len(distinct)}."
        return blank(keys, reason, RETURN_BASIS)
    labels = np.asarray(years)
    growth = np.log1p(returns)
    whole = float(growth.sum())
    # Total return with one calendar year taken out, in the order of `distinct`.
    without = [float(np.expm1(whole - growth[labels == year].sum())) for year in distinct]
    lowest = int(np.argmin(without))
    return Result(
        {
            "total": float(np.expm1(whole)),
            "lowest": without[lowest],
            "highest": max(without),
            "driver_year": str(distinct[lowest]),
        },
        {},
        basis=RETURN_BASIS,
    )


YEAR_JACKKNIFE = make_spec(
    "resampling.year_jackknife",
    question="Does any single calendar year drive the total return?",
    needs=("stored_equity",),
    params=(),
    outputs=(
        Output("total", "Total return", "Compound after-cost return of the whole run.", "fraction"),
        Output(
            "lowest",
            "Lowest total without one year",
            "Smallest compound return after taking out any one calendar year.",
            "fraction",
        ),
        Output(
            "highest",
            "Highest total without one year",
            "Largest compound return after taking out any one calendar year.",
            "fraction",
        ),
        Output(
            "driver_year",
            "Year that matters most",
            "The year whose removal lowers the total return most.",
            "text",
        ),
    ),
    reading=(
        "The run returned {total:+.1%} in total. Taking out any one calendar year left between"
        " {lowest:+.1%} and {highest:+.1%}; removing {driver_year} lowered it most."
    ),
    caveats=(
        "Removing a year joins the years either side of it, and a partial first or last year"
        " counts as a year. It shows dependence on a period, not why the period was good.",
    ),
    reference="test_known_answer_year_jackknife",
    compute=year_jackknife,
    situations=("works-only-sometimes", "lucky-trades"),
    seeded=False,
)


def stress(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_validation.path_montecarlo import path_metric_arrays

    returns = scored(inputs)
    keys = ("observed_drop", "scaled_total", "scaled_drop", "shocked_drop")
    if len(returns) < 2:
        return blank(keys, "The stress needs at least 2 scored bar returns.", RETURN_BASIS)
    scale, shock = params["vol_scale"], params["shock"]
    if not scale > 0 or not -1.0 < shock < 0.0:
        raise ValueError("vol_scale must be above 0 and shock between -1 and 0")
    scaled = returns.mean() + scale * (returns - returns.mean())
    if scaled.min() <= -1.0:
        reason = "Scaling the swings would take a bar return to -100% or lower."
        return blank(keys, reason, RETURN_BASIS)
    peak = int(np.argmax(np.cumprod(np.r_[1.0, 1.0 + returns])))  # bars played before the high
    shocked = np.insert(returns, peak, shock)

    def drop(series: FloatArray) -> float:
        return float(path_metric_arrays(series[None, :]).maximum_drawdown[0])

    return Result(
        {
            "observed_drop": drop(returns),
            "scaled_total": float(np.prod(1.0 + scaled) - 1.0),
            "scaled_drop": drop(scaled),
            "shocked_drop": drop(shocked),
        },
        {},
        basis=RETURN_BASIS,
    )


STRESS_SHOCKS = make_spec(
    "resampling.stress_shocks",
    question="What if the swings were larger, or one sudden loss hit at the high?",
    needs=("stored_equity",),
    params=(
        Param(
            "vol_scale", float, 1.5, None, "Factor applied to each bar's distance from the mean."
        ),
        Param("shock", float, -0.05, None, "Return of one extra bar inserted at the equity high."),
    ),
    outputs=(
        Output(
            "observed_drop", "Worst drop", "Largest peak-to-trough fall in the run.", "fraction"
        ),
        Output(
            "scaled_total",
            "Total return, larger swings",
            "Compound return with every bar's distance from the mean scaled up.",
            "fraction",
        ),
        Output(
            "scaled_drop",
            "Worst drop, larger swings",
            "Worst drop with the scaled bars.",
            "fraction",
        ),
        Output(
            "shocked_drop",
            "Worst drop, one shock",
            "Worst drop with one extra loss bar inserted at the equity high.",
            "fraction",
        ),
    ),
    reading=(
        "The worst drop was {observed_drop:.1%}. With larger swings the total return would be"
        " {scaled_total:+.1%} and the worst drop {scaled_drop:.1%}; one sudden loss at the high"
        " would make it {shocked_drop:.1%}."
    ),
    caveats=(
        "Scaling keeps the average bar return and ignores any change in costs or fills when"
        " markets move more. It is a what-if, not a forecast of either event.",
    ),
    reference="test_known_answer_stress",
    compute=stress,
    situations=("drawdown",),
    seeded=False,
)
CHECKS = (YEAR_JACKKNIFE, STRESS_SHOCKS)
