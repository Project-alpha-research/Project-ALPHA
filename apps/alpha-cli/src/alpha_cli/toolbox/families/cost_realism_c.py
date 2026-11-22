"""Cost realism read from the run's own price bars: implied spread and overnight gaps."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec
from alpha_cli.toolbox.families.cost_realism_common import NO_BARS, make, run_bars, unavailable

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

BASIS = "The run's own daily bars, cut at the held-back boundary."
MIN_BARS = 30
FEW = f"Too little to read: needs at least {MIN_BARS} bars, the run has {{n}}."
CS_DENOM = 3 - 2 * math.sqrt(2)

SPREAD_OUTPUTS = (
    Output(
        "roll_bps",
        "Roll spread",
        "Roll (1984) spread implied by close-to-close price changes.",
        "bps",
    ),
    Output(
        "corwin_schultz_bps",
        "Corwin-Schultz spread",
        "Spread implied by two-day high-low ranges.",
        "bps",
    ),
    Output(
        "abdi_ranaldo_bps",
        "Abdi-Ranaldo spread",
        "Spread implied by closes against high-low midpoints.",
        "bps",
    ),
)


def spreads(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    """Roll (1984, eq. 3): 2 sqrt(-cov(dp_t, dp_t-1)). Corwin and Schultz (2012, eqs. 7, 14, 18):
    S = 2 (e^a - 1) / (1 + e^a). Abdi and Ranaldo (2017, eq. 12):
    sqrt(4 E[(c_t - eta_t)(c_t - eta_t+1)])."""
    import numpy as np

    bars = run_bars(inputs)
    if not bars:
        return unavailable(SPREAD_OUTPUTS, NO_BARS, BASIS)
    if len(bars) < MIN_BARS:
        return unavailable(SPREAD_OUTPUTS, FEW.format(n=len(bars)), BASIS)
    high, low, close = (np.array([getattr(b, k) for b in bars]) for k in ("high", "low", "close"))
    values: dict[str, Any] = {}
    reasons: dict[str, str] = {}
    diff = np.diff(close)
    cov = float(np.cov(diff[1:], diff[:-1])[0, 1])
    if cov < 0:
        values["roll_bps"] = 2 * math.sqrt(-cov) / float(close.mean()) * 1e4
    else:
        values["roll_bps"], reasons["roll_bps"] = (
            None,
            "Price changes are not negatively correlated, so the estimate does not exist.",
        )
    hl = np.log(high / low)
    beta = hl[:-1] ** 2 + hl[1:] ** 2
    gamma = np.log(np.maximum(high[:-1], high[1:]) / np.minimum(low[:-1], low[1:])) ** 2
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / CS_DENOM - np.sqrt(gamma / CS_DENOM)
    cs = float(np.mean(2 * np.expm1(alpha) / (1 + np.exp(alpha))))
    mid = (np.log(high) + np.log(low)) / 2
    ar = float(np.mean(4 * (np.log(close)[:-1] - mid[:-1]) * (np.log(close)[:-1] - mid[1:])))
    for key, estimate in (("corwin_schultz_bps", cs), ("abdi_ranaldo_bps", ar)):
        spread = (
            estimate if key.startswith("corwin") else (math.sqrt(estimate) if estimate > 0 else 0.0)
        )
        if estimate > 0:
            values[key] = spread * 1e4
        else:
            values[key], reasons[key] = (
                None,
                "The estimate is not positive, so it implies no spread.",
            )
    return Result(values, reasons, basis=BASIS)


SPREAD = make(
    "spread_estimates",
    "What trading spread do the price bars imply?",
    ("run_bars",),
    (),
    SPREAD_OUTPUTS,
    "Daily bars imply a spread of {roll_bps:.1f} basis points (Roll), {corwin_schultz_bps:.1f} "
    "(Corwin-Schultz) and {abdi_ranaldo_bps:.1f} (Abdi-Ranaldo).",
    "Estimators from daily bars are rough: they can read zero or fail on a quiet or trending "
    "history, and they cannot see the quoted spread at the time of a trade.",
    spreads,
)

GAP_OUTPUTS = (
    Output(
        "down_gap_share",
        "Gaps through a long stop",
        "Share of days the open was below a stop set under the last close.",
        "fraction",
    ),
    Output(
        "down_extra_loss",
        "Loss beyond the stop",
        "Average distance of the open below the stop on those days.",
        "fraction",
    ),
    Output(
        "worst_down_gap",
        "Worst overnight drop",
        "Lowest open over the prior close, less one.",
        "fraction",
    ),
)


def gaps(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    bars = run_bars(inputs)
    if not bars:
        return unavailable(GAP_OUTPUTS, NO_BARS, BASIS)
    if len(bars) < MIN_BARS:
        return unavailable(GAP_OUTPUTS, FEW.format(n=len(bars)), BASIS)
    close = np.array([b.close for b in bars[:-1]])
    open_ = np.array([b.open for b in bars[1:]])
    stop = params["stop_pct"] / 100
    down = close * (1 - stop)
    through = open_ < down
    values: dict[str, Any] = {
        "down_gap_share": float(through.mean()),
        "down_extra_loss": float(np.mean((down[through] - open_[through]) / down[through]))
        if through.any()
        else None,
        "worst_down_gap": float((open_ / close - 1).min()),
    }
    reasons = {} if through.any() else {"down_extra_loss": "No open gapped through the stop."}
    return Result(values, reasons, basis=BASIS)


GAP_STRESS = make(
    "gap_stress",
    "What if stops fill at the next open after an overnight gap?",
    ("run_bars",),
    (Param("stop_pct", float, 3.0, None, "Stop distance from the prior close, in percent."),),
    GAP_OUTPUTS,
    "The open gapped through a long stop on {down_gap_share:.1%} of days, by {down_extra_loss:.2%} "
    "on average; the worst overnight drop was {worst_down_gap:.1%}.",
    "It tests a stop set at a fixed distance from the prior close, not the stops of this rule, and "
    "knows nothing about gaps in bars the run never held.",
    gaps,
)
CHECKS: tuple[ToolSpec, ...] = (SPREAD, GAP_STRESS)
