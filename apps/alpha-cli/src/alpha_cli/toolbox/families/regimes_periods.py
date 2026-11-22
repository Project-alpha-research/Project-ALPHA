"""Regime checks that split the scored history by calendar year or into two halves."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, Value
from alpha_cli.toolbox.families.regimes_base import (
    BASIS,
    MIN_BARS,
    dated_returns,
    spec,
    two_group_outputs,
    two_group_result,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

YEAR_KEYS = ("years", "positive_years", "best_return", "worst_return", "median_return")


def year_by_year(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    dates, returns = dated_returns(inputs)
    by_year: dict[int, list[float]] = {}
    for ts, value in zip(dates, returns, strict=True):
        by_year.setdefault(ts.year, []).append(float(value))
    if len(by_year) < 2:
        return unavailable(
            YEAR_KEYS, f"Needs bars in at least 2 calendar years; found {len(by_year)}."
        )
    rows = [
        {"year": year, "bars": len(rets), "total_return": math.prod(1 + r for r in rets) - 1}
        for year, rets in sorted(by_year.items())
    ]
    totals = np.array([row["total_return"] for row in rows])
    values: dict[str, Value] = {
        "years": len(rows),
        "positive_years": int((totals > 0).sum()),
        "best_return": float(totals.max()),
        "worst_return": float(totals.min()),
        "median_return": float(np.median(totals)),
    }
    return Result(values, {}, details={"years": rows}, basis=BASIS)


YEAR_BY_YEAR = spec(
    "regimes.year_by_year",
    "Does it work in most years or only a few?",
    ("stored_equity",),
    (
        Output("years", "Calendar years", "Calendar years with at least one scored bar.", "count"),
        Output(
            "positive_years",
            "Gaining years",
            "Years whose compound return was above zero.",
            "count",
        ),
        Output(
            "best_return", "Best year", "Compound after-cost return of the best year.", "fraction"
        ),
        Output(
            "worst_return",
            "Worst year",
            "Compound after-cost return of the worst year.",
            "fraction",
        ),
        Output(
            "median_return", "Median year", "Middle compound return across the years.", "fraction"
        ),
    ),
    "{positive_years} of {years} calendar years gained; the best year returned {best_return:.1%},"
    " the worst {worst_return:.1%} and the middle year {median_return:.1%}.",
    "The first and last year may be partial. It describes the past and cannot say why a year was"
    " good or bad.",
    "test_year_by_year_known_answer",
    year_by_year,
)

HALF_KEYS = (
    "first_mean", "second_mean", "gap", "p_value", "first_bars", "second_bars",
    "first_sharpe", "second_sharpe",
)  # fmt: skip


def _sharpe(part: Any, ppy: int) -> float | None:
    import numpy as np

    if part.size < 2 or np.ptp(part) == 0:
        return None
    return float(part.mean() / part.std(ddof=1) * math.sqrt(ppy))


def sub_period_stability(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    dates, returns = dated_returns(inputs)
    if returns.size < MIN_BARS:
        return unavailable(
            HALF_KEYS,
            f"Needs at least {MIN_BARS} scored bars to compare halves; found {returns.size}.",
        )
    half = returns.size // 2
    first, second = returns[:half], returns[half:]
    result = two_group_result(
        first, second, ("first", "second"), extra={"split_date": dates[half].date().isoformat()}
    )
    ppy = inputs.stored.ppy
    sharpes = {"first_sharpe": _sharpe(first, ppy), "second_sharpe": _sharpe(second, ppy)}
    reason = "Returns do not vary in this half, so a Sharpe ratio is undefined."
    return Result(
        {**result.values, **sharpes},
        {**result.reasons, **{k: reason for k, v in sharpes.items() if v is None}},
        details=result.details,
        basis=BASIS,
    )


SUB_PERIOD = spec(
    "regimes.sub_period_stability",
    "Do the early and late halves of the history agree?",
    ("stored_equity",),
    (
        *two_group_outputs(("first", "second"), ("first half", "second half"), "in that half"),
        Output(
            "first_sharpe",
            "Yearly Sharpe, first half",
            "Annualised Sharpe ratio of the first half.",
            "ratio",
        ),
        Output(
            "second_sharpe",
            "Yearly Sharpe, second half",
            "Annualised Sharpe ratio of the second half.",
            "ratio",
        ),
    ),
    "The first half earned {first_mean:.4%} per bar and the second half {second_mean:.4%}"
    " (p-value of the gap {p_value:.3f}; yearly Sharpe {first_sharpe:.2f} then"
    " {second_sharpe:.2f}).",
    "A large p-value does not show the halves are alike, it shows the history is too noisy to tell."
    " One cut at the middle says nothing about other cuts.",
    "test_sub_period_known_answer",
    sub_period_stability,
    kind="test",
)
