"""Drawdown-path statistics of the stored equity curve: ulcer, pain, Sterling, Burke, recovery."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec, Value
from alpha_cli.toolbox.families.performance_stats_common import (
    EQUITY_BASIS,
    MIN_RETURNS,
    POISON,
    TESTS,
    stored_equity,
    too_few_returns,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

NEVER_BELOW = "The equity curve never fell below an earlier peak."


def _depths(equity: Any) -> Any:
    import numpy as np

    return equity / np.maximum.accumulate(equity) - 1.0


def ulcer(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_validation.metrics import cagr

    run = inputs.stored
    equity = stored_equity(run)
    keys = ("ulcer_index", "martin_ratio", "cagr")
    if equity.size - 1 < MIN_RETURNS:
        return unavailable(keys, too_few_returns(equity.size - 1))
    index = math.sqrt(float(np.mean(_depths(equity) ** 2)))
    growth = cagr(equity, periods_per_year=run.ppy)
    values: dict[str, Value] = {"ulcer_index": index, "cagr": growth, "martin_ratio": None}
    reasons = {}
    if index > 0:
        values["martin_ratio"] = growth / index
    else:
        reasons["martin_ratio"] = NEVER_BELOW
    return Result(values, reasons, basis=EQUITY_BASIS)


ULCER = ToolSpec(
    id="performance.ulcer",
    situations=(
        "drawdown",
        "risk-adjusted",
    ),
    answers=("How painful was the drawdown path, in depth and in time?",),
    family="performance",
    question="How painful was the drawdown path, and what did the return pay per unit of pain?",
    needs=("stored_equity",),
    params=(),
    outputs=(
        Output(
            "ulcer_index",
            "Ulcer index",
            "Root mean square of the drop below the running peak, over every stored equity"
            " point; deep and long drawdowns both raise it.",
            "fraction",
        ),
        Output(
            "martin_ratio",
            "Martin ratio",
            "Compound yearly return divided by the ulcer index (the ulcer performance index).",
            "ratio",
        ),
        Output(
            "cagr",
            "Compound yearly return",
            "Compound growth per year over the stored walk-forward period.",
            "fraction",
        ),
    ),
    reading=(
        "The ulcer index was {ulcer_index:.1%}, and the Martin ratio was {martin_ratio:.2f}"
        " for a compound yearly return of {cagr:.1%}."
    ),
    caveats=(
        "It describes only the path this run took; it cannot tell you how deep a future drawdown"
        " will go. Martin and McCann (1989) used monthly data; bar returns here are daily.",
    ),
    reference=TESTS + "test_ulcer",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=ulcer,
)


def pain(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_validation.metrics import cagr

    run = inputs.stored
    equity = stored_equity(run)
    keys = ("pain_index", "pain_ratio", "cagr")
    if equity.size - 1 < MIN_RETURNS:
        return unavailable(keys, too_few_returns(equity.size - 1))
    index = float(np.mean(np.abs(_depths(equity))))
    growth = cagr(equity, periods_per_year=run.ppy)
    ratio = growth / index if index > 0 else None
    reasons = {} if ratio is not None else {"pain_ratio": NEVER_BELOW}
    values: dict[str, Value] = {"pain_index": index, "pain_ratio": ratio, "cagr": growth}
    return Result(values, reasons, basis=EQUITY_BASIS)


PAIN = ToolSpec(
    id="performance.pain",
    situations=(
        "drawdown",
        "risk-adjusted",
    ),
    answers=("What was the average drawdown, and what did the return pay per unit of it?",),
    family="performance",
    question="How deep was the average drawdown, and what did the return pay per unit of it?",
    needs=("stored_equity",),
    params=(),
    outputs=(
        Output(
            "pain_index",
            "Pain index",
            "Mean of the drop below the running peak over every stored equity point"
            " (Zephyr Associates' pain index); time at a peak counts as zero.",
            "fraction",
        ),
        Output(
            "pain_ratio",
            "Pain ratio",
            "Compound yearly return divided by the pain index.",
            "ratio",
        ),
        Output(
            "cagr",
            "Compound yearly return",
            "Compound growth per year over the stored walk-forward period.",
            "fraction",
        ),
    ),
    reading=(
        "The average drop below the running peak was {pain_index:.1%}; the pain ratio was"
        " {pain_ratio:.2f} for a compound yearly return of {cagr:.1%}."
    ),
    caveats=("It averages the whole path and cannot tell you about the single worst drop.",),
    reference=TESTS + "test_pain",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=pain,
)


def sterling_burke(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_validation.metrics import cagr, drawdown_episodes

    run = inputs.stored
    equity = stored_equity(run)
    keys = ("episodes", "sterling_ratio", "burke_ratio", "cagr")
    if equity.size - 1 < MIN_RETURNS:
        return unavailable(keys, too_few_returns(equity.size - 1))
    depths = [abs(e.depth) for e in drawdown_episodes(equity, top=params["top"])]
    growth = cagr(equity, periods_per_year=run.ppy)
    if not depths:
        return unavailable(keys, NEVER_BELOW, {"episodes": 0, "cagr": growth})
    sterling = growth / (math.fsum(depths) / len(depths))
    burke = growth / math.sqrt(math.fsum(d * d for d in depths))
    values: dict[str, Value] = {
        "episodes": len(depths),
        "sterling_ratio": sterling,
        "burke_ratio": burke,
        "cagr": growth,
    }
    return Result(values, {}, basis=EQUITY_BASIS)


STERLING_BURKE = ToolSpec(
    id="performance.sterling_burke",
    situations=(
        "drawdown",
        "risk-adjusted",
    ),
    answers=("What does the return pay per unit of the worst drawdowns?",),
    family="performance",
    question="How large was the return relative to the typical deep drawdown?",
    needs=("stored_equity",),
    params=(
        Param(
            "top",
            int,
            5,
            range(1, 21),
            "How many of the deepest drawdown episodes enter the two ratios.",
        ),
    ),
    outputs=(
        Output(
            "sterling_ratio",
            "Sterling ratio",
            "Compound yearly return divided by the average depth of the deepest drawdown"
            " episodes (Sterling's idea; conventions differ, this is the stated one).",
            "ratio",
        ),
        Output(
            "burke_ratio",
            "Burke ratio",
            "Compound yearly return divided by the square root of the summed squared depths of"
            " the deepest drawdown episodes (Burke 1994).",
            "ratio",
        ),
        Output(
            "episodes",
            "Episodes used",
            "Drawdown episodes entering the ratios; fewer than asked when the run had fewer.",
            "count",
        ),
        Output(
            "cagr",
            "Compound yearly return",
            "Compound growth per year over the stored walk-forward period.",
            "fraction",
        ),
    ),
    reading=(
        "Over {episodes} deepest drawdown episodes the Sterling ratio was {sterling_ratio:.2f}"
        " and the Burke ratio {burke_ratio:.2f}, for a compound yearly return of {cagr:.1%}."
    ),
    caveats=(
        "Each episode counts once at its own deepest point; the ratios cannot tell you how"
        " long the episodes lasted.",
    ),
    reference=TESTS + "test_sterling_burke",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=sterling_burke,
)

CHECKS = (ULCER, PAIN, STERLING_BURKE)
