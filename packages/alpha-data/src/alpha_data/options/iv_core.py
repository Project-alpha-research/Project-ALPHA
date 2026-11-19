"""Shared pieces of the implied-volatility solvers: day count, result types and the root finder.

Pure math. No data reads, no clock. Used by `implied` (closed form) and `implied_american` (tree).

Sources
- Root finder: safeguarded Newton-Raphson that keeps a bracket and bisects whenever the Newton step
  leaves the bracket or does not halve it fast enough. Press, Teukolsky, Vetterling and Flannery,
  "Numerical Recipes", the routine `rtsafe`. The price is strictly increasing in volatility
  (vega > 0), so a sign change of price(vol) - target on the interval guarantees one root.

Rules
- Day count: ACT/365 fixed on calendar time. years = (expiry_ts - snapshot_ts) seconds /
  (365 * 86400), both aware-UTC.
- Search interval for the volatility: [IV_LOW, IV_HIGH] = [0.0001, 10.0] (0.01% to 1000%). The
  tree solver raises the lower end to the smallest volatility its step size allows.
- Typed outcomes, never a silent NaN: `IvSolved` or `IvUnsolved` with a stated reason.
- Low confidence, exact rule: iv_uncertainty = price_resolution / vega (vega per 1.00 of vol at
  the solved vol). The result is "low_vega" when iv_uncertainty > LOW_CONFIDENCE_IV_ERROR (0.005,
  half a vol point); with the default half-cent resolution that is vega < 1.0.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from alpha_data.options.pricing import Conventions, OptionInputs
from alpha_data.options.schema import Greeks, OptionsDataError, aware_utc

if TYPE_CHECKING:
    from alpha_data.options.tree import AmericanInputs

IV_LOW = 1e-4
IV_HIGH = 10.0
DEFAULT_PRICE_RESOLUTION = 0.005
LOW_CONFIDENCE_IV_ERROR = 0.005
_SECONDS_PER_YEAR = 365.0 * 86400.0
_MAX_ITER = 200

Reason = Literal[
    "price_outside_no_arbitrage_bounds",
    "zero_time_to_expiry",
    "american_style_needs_tree_inputs",
    "implied_vol_outside_search_interval",
    "did_not_converge",
    "no_quote",
    "no_mid",
]
_MESSAGES: dict[str, str] = {
    "price_outside_no_arbitrage_bounds": "price outside no-arbitrage bounds",
    "zero_time_to_expiry": "zero time to expiry",
    "american_style_needs_tree_inputs": "American style needs the tree solver",
    "implied_vol_outside_search_interval": f"volatility outside [{IV_LOW:g}, {IV_HIGH:g}]",
    "did_not_converge": "the root finder did not converge",
    "no_quote": "the row has no quote",
    "no_mid": "the quote has no usable mid",
}


def years_between(snapshot_ts: datetime, expiry_ts: datetime) -> float:
    """ACT/365 fixed calendar years from the snapshot to expiry; both must be aware UTC."""
    start, end = aware_utc("snapshot_ts", snapshot_ts), aware_utc("expiry_ts", expiry_ts)
    if end < start:
        raise OptionsDataError("expiry_ts", "is before the snapshot time")
    return (end - start).total_seconds() / _SECONDS_PER_YEAR


def finite(field: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise OptionsDataError(field, f"must be a finite number, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class IvSolved:
    """A solved volatility with how it was found. `confidence` is "normal" or "low_vega".

    `method` is "closed_form" or "crr_tree"; `steps` is the tree step count (None for closed form).
    """

    iv: float
    confidence: str
    vega: float
    iv_uncertainty: float
    iterations: int
    price: float
    model: str
    inputs: OptionInputs | AmericanInputs
    conventions: Conventions
    greeks: Greeks | None = None
    method: str = "closed_form"
    steps: int | None = None


@dataclass(frozen=True)
class IvUnsolved:
    """No volatility, with a typed reason. `message` starts "no implied volatility: "."""

    reason: Reason
    inputs: OptionInputs | AmericanInputs | None

    @property
    def message(self) -> str:
        return f"no implied volatility: {_MESSAGES[self.reason]}"


def safeguarded_root(
    func: Callable[[float], tuple[float, float]],
    target: float,
    *,
    lo: float,
    hi: float,
    guess: float,
    xtol: float,
) -> tuple[float, int] | Reason:
    """Root of price(x) = target on [lo, hi]; `func(x)` returns (price, vega). (x, iterations)."""
    if func(lo)[0] > target or func(hi)[0] < target:
        return "implied_vol_outside_search_interval"
    x = min(max(guess, 2 * lo), hi / 2)
    step = hi - lo
    for iteration in range(1, _MAX_ITER + 1):
        value, vega = func(x)
        diff = value - target
        if diff == 0.0:
            return x, iteration
        if diff < 0:
            lo = x
        else:
            hi = x
        previous = step
        newton = x - diff / vega if vega > 0 else math.inf
        if not lo < newton < hi or abs(2.0 * diff) > abs(previous * vega):
            new_x = 0.5 * (lo + hi)
            step = hi - lo
        else:
            new_x = newton
            step = abs(new_x - x)
        if abs(new_x - x) < xtol or hi - lo < xtol:
            return new_x, iteration
        x = new_x
    return "did_not_converge"
