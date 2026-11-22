"""Return-distribution statistics of the stored equity: Cornish-Fisher Sharpe, worst windows."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, ToolSpec, Value
from alpha_cli.toolbox.families.performance_stats_common import (
    EQUITY_BASIS,
    MIN_RETURNS,
    POISON,
    TESTS,
    stored_equity,
    stored_returns,
    too_few_returns,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

NEVER_BELOW = "The equity curve never fell below an earlier peak."
FLAT = "The stored returns do not vary, so the Sharpe ratio is undefined."
WINDOWS = (1, 5, 21)


def cornish_fisher(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = ("sharpe", "adjusted_sharpe", "skewness", "excess_kurtosis")
    returns, reason = stored_returns(inputs.stored)
    if returns is None:
        return unavailable(keys, reason)
    centred = returns - np.mean(returns)
    variance = float(np.mean(centred**2))
    if variance <= 0:
        return unavailable(keys, FLAT)
    skew = float(np.mean(centred**3)) / variance**1.5
    kurt = float(np.mean(centred**4)) / variance**2 - 3.0
    per_bar = float(np.mean(returns)) / float(np.std(returns, ddof=1))
    factor = 1 + skew / 6 * per_bar - kurt / 24 * per_bar**2
    scale = math.sqrt(inputs.stored.ppy)
    values: dict[str, Value] = {
        "sharpe": per_bar * scale,
        "adjusted_sharpe": per_bar * factor * scale,
        "skewness": skew,
        "excess_kurtosis": kurt,
    }
    return Result(values, {}, basis=EQUITY_BASIS)


CORNISH_FISHER = ToolSpec(
    id="performance.cornish_fisher_sharpe",
    situations=("risk-adjusted",),
    answers=("What is the Sharpe ratio once skew and fat tails are counted?",),
    family="performance",
    question="How does the Sharpe ratio change when skew and fat tails are counted?",
    needs=("stored_equity",),
    params=(),
    outputs=(
        Output(
            "sharpe",
            "Plain yearly Sharpe",
            "Mean over standard deviation of bar returns, times the square root of bars per year.",
            "ratio",
        ),
        Output(
            "adjusted_sharpe",
            "Skew- and kurtosis-adjusted Sharpe",
            "Bar Sharpe times one plus skewness over 6 times the bar Sharpe, minus excess"
            " kurtosis over 24 times its square (Pezier and White 2008), then annualised.",
            "ratio",
        ),
        Output(
            "skewness",
            "Skewness",
            "Third standardised moment of bar returns; negative means a longer left tail.",
            "ratio",
        ),
        Output(
            "excess_kurtosis",
            "Excess kurtosis",
            "Fourth standardised moment of bar returns minus 3; positive means fat tails.",
            "ratio",
        ),
    ),
    reading=(
        "The yearly Sharpe was {sharpe:.2f} plain and {adjusted_sharpe:.2f} after the skew"
        " ({skewness:.2f}) and fat-tail ({excess_kurtosis:.2f}) adjustment."
    ),
    caveats=(
        "The adjustment is a four-moment approximation and cannot tell you how the next tail"
        " event will look; moments from a short run are noisy.",
    ),
    reference=TESTS + "test_cornish_fisher_sharpe",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=cornish_fisher,
)


def worst_windows(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    run = inputs.stored
    frame = run.table("stored_equity", "ts", "equity")
    dates = run.dates(frame, "stored_equity")
    equity = stored_equity(run)
    keys = tuple(f"worst_{w}" for w in WINDOWS) + tuple(f"worst_{w}_end" for w in WINDOWS)
    if equity.size - 1 < MIN_RETURNS:
        return unavailable(keys, too_few_returns(equity.size - 1))
    values: dict[str, Value] = {}
    reasons = {}
    for w in WINDOWS:
        if equity.size - 1 < w:
            for key in (f"worst_{w}", f"worst_{w}_end"):
                values[key] = None
                reasons[key] = f"Fewer than {w} stored returns."
            continue
        rolled = equity[w:] / equity[:-w] - 1.0
        worst = int(np.argmin(rolled))
        values[f"worst_{w}"] = float(rolled[worst])
        values[f"worst_{w}_end"] = dates[worst + w].date().isoformat()
    return Result(values, reasons, basis=EQUITY_BASIS)


def _window_outputs() -> tuple[Output, ...]:
    names = {1: "bar", 5: "5-bar window", 21: "21-bar window"}
    rows: list[Output] = []
    for w in WINDOWS:
        rows.append(
            Output(
                f"worst_{w}",
                f"Worst {names[w]} return",
                f"Lowest compounded return over any {w} consecutive bar{'s' if w > 1 else ''};"
                " negative means a loss.",
                "fraction",
            )
        )
        rows.append(
            Output(
                f"worst_{w}_end",
                f"End of worst {names[w]}",
                f"Date of the last bar in the worst {w}-bar window.",
                "date",
            )
        )
    return tuple(rows)


WORST_WINDOWS = ToolSpec(
    id="performance.worst_windows",
    situations=(
        "drawdown",
        "return-range",
    ),
    answers=("What were the worst day, week and month the run had?",),
    family="performance",
    question="What were the worst one-bar, 5-bar and 21-bar returns?",
    needs=("stored_equity",),
    params=(),
    outputs=_window_outputs(),
    reading=(
        "The worst single bar returned {worst_1:.1%}, the worst five-bar window {worst_5:.1%}"
        " and the worst twenty-one-bar window {worst_21:.1%}."
    ),
    caveats=(
        "On daily bars 1, 5 and 21 bars are about a day, a week and a month. Windows overlap,"
        " and the worst one so far cannot tell you the worst to come.",
    ),
    reference=TESTS + "test_worst_windows",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=worst_windows,
)


def recovery_factor(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    equity = stored_equity(inputs.stored)
    keys = ("net_profit", "max_drawdown_amount", "recovery_factor")
    if equity.size - 1 < MIN_RETURNS:
        return unavailable(keys, too_few_returns(equity.size - 1))
    profit = float(equity[-1] - equity[0])
    drop = float(np.max(np.maximum.accumulate(equity) - equity))
    values: dict[str, Value] = {
        "net_profit": profit,
        "max_drawdown_amount": drop,
        "recovery_factor": profit / drop if drop > 0 else None,
    }
    reasons = {} if drop > 0 else {"recovery_factor": NEVER_BELOW}
    return Result(values, reasons, basis=EQUITY_BASIS)


RECOVERY_FACTOR = ToolSpec(
    id="performance.recovery_factor",
    situations=("drawdown",),
    answers=("How much net profit did the run make per unit of its worst drawdown?",),
    family="performance",
    question="How many times over did the net profit cover the worst drawdown?",
    needs=("stored_equity",),
    params=(),
    outputs=(
        Output(
            "net_profit",
            "Net profit",
            "Last stored equity minus first stored equity, after costs, in account currency.",
            "currency",
        ),
        Output(
            "max_drawdown_amount",
            "Worst drawdown amount",
            "Largest fall from a running peak to a later low, in account currency.",
            "currency",
        ),
        Output(
            "recovery_factor",
            "Recovery factor",
            "Net profit divided by the worst drawdown amount.",
            "ratio",
        ),
    ),
    reading=(
        "Net profit was {net_profit:.2f} and the worst drawdown {max_drawdown_amount:.2f},"
        " so the recovery factor was {recovery_factor:.2f}."
    ),
    caveats=(
        "Both amounts depend on the starting equity and on position size; the factor cannot"
        " tell you how long the recovery took.",
    ),
    reference=TESTS + "test_recovery_factor",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=recovery_factor,
)

CHECKS = (CORNISH_FISHER, WORST_WINDOWS, RECOVERY_FACTOR)
