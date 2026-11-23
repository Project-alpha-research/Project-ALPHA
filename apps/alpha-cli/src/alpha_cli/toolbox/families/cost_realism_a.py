"""Cost realism on the stored equity curve: cost sweep and the churn budget."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, ToolSpec
from alpha_cli.toolbox.families.cost_realism_common import (
    NO_TRADES,
    closed_trades,
    cost_curve,
    make,
    old_run,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

BASIS = "Scored walk-forward returns, with the stored fill costs scaled on each bar."
MULTIPLES = (0, 1, 2, 5)
SWEEP_OUTPUTS = (
    *(
        Output(
            f"return_x{m}",
            f"Return at {m} times costs" if m else "Return with no costs",
            f"Compounded total return with the stored fill costs multiplied by {m}.",
            "fraction",
        )
        for m in MULTIPLES
    ),
    Output(
        "sharpe_x1", "Sharpe at today's costs", "Annualised Sharpe of the bar returns.", "ratio"
    ),
    Output(
        "sharpe_x2", "Sharpe at twice the costs", "Annualised Sharpe at doubled costs.", "ratio"
    ),
)


def _wealth(gross: Any, costs: Any, k: float) -> tuple[float, Any]:
    """Compounded total return and bar returns when each bar's cost is scaled by k."""
    import numpy as np

    after = gross - k * costs
    if (after <= -1).any():
        return -1.0, after  # a bar exhausted the account: later bars cannot restore it
    return math.expm1(math.fsum(np.log1p(after))), after


def cost_sweep(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    curve = cost_curve(inputs)
    if curve is None:
        return unavailable(SWEEP_OUTPUTS, old_run(inputs), BASIS)
    _, _, gross, costs = curve
    values: dict[str, Any] = {}
    reasons: dict[str, str] = {}
    for m in MULTIPLES:
        values[f"return_x{m}"], after = _wealth(gross, costs, m)
        if m in (1, 2):
            sd = float(np.std(after, ddof=1)) if after.size > 1 else 0.0
            if sd > 0 and (after > -1).all():
                values[f"sharpe_x{m}"] = float(np.mean(after) / sd * math.sqrt(inputs.stored.ppy))
            else:
                values[f"sharpe_x{m}"] = None
                reasons[f"sharpe_x{m}"] = "Too little to read: needs two bar returns that differ."
    return Result(values, reasons, basis=BASIS)


COST_SWEEP = make(
    "cost_sweep",
    "How does the return change as trading costs rise?",
    ("stored_equity",),
    (),
    SWEEP_OUTPUTS,
    "Total return was {return_x1:.1%} at today's costs, {return_x0:.1%} with none, "
    "{return_x2:.1%} at twice and {return_x5:.1%} at five times today's costs.",
    "Scaling the recorded costs cannot show wider spreads in stressed markets, partial fills or "
    "whole-share rounding. It does not say which cost level is realistic.",
    cost_sweep,
)

CHURN_OUTPUTS = (
    Output(
        "gross_return",
        "Return before costs",
        "Compounded total return before fill costs.",
        "fraction",
    ),
    Output(
        "net_return", "Return after costs", "Compounded total return after fill costs.", "fraction"
    ),
    Output(
        "trades_per_year",
        "Trades a year",
        "Closed trades per 365.25 days of the scored period.",
        "ratio",
    ),
    Output(
        "cost_drag_per_year",
        "Yearly cost drag",
        "Yearly log-wealth given up to fill costs.",
        "fraction",
    ),
)


def churn_budget(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    curve = cost_curve(inputs)
    if curve is None:
        return unavailable(CHURN_OUTPUTS, old_run(inputs), BASIS)
    dates, _, gross, costs = curve
    trades = closed_trades(inputs)
    years = (dates[-1] - dates[0]).total_seconds() / (365.25 * 86400)
    if trades is None or not trades.height:
        return unavailable(CHURN_OUTPUTS, NO_TRADES, BASIS)
    g, _ = _wealth(gross, costs, 0)
    n, _ = _wealth(gross, costs, 1)
    values: dict[str, Any] = {
        "gross_return": g,
        "net_return": n,
        "trades_per_year": trades.height / years,
        "cost_drag_per_year": (math.log1p(g) - math.log1p(n)) / years if n > -1 else None,
    }
    reasons = {}
    if n <= -1:
        reasons["cost_drag_per_year"] = "The account was wiped out after costs."
    return Result(values, reasons, basis=BASIS)


CHURN_BUDGET = make(
    "churn_budget",
    "How much of the return is left after the cost of trading so often?",
    ("stored_equity", "run_trades"),
    (),
    CHURN_OUTPUTS,
    "{trades_per_year:.1f} trades a year gave up {cost_drag_per_year:.1%} of log wealth a year to "
    "costs: {gross_return:.1%} before costs, {net_return:.1%} after.",
    "It describes this run's own turnover. It does not say whether fewer trades would have kept "
    "the same profit.",
    churn_budget,
)
CHECKS: tuple[ToolSpec, ...] = (COST_SWEEP, CHURN_BUDGET)
