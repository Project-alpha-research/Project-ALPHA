"""Implied volatility: day count, mid price, a bracketed root finder and the computed greeks block.

Pure math plus the layer's records. No data reads, no clock.

Sources
- The models are in `alpha_data.options.pricing` (Black-Scholes-Merton, Black-76).
- Root finder: safeguarded Newton-Raphson that keeps a bracket and bisects whenever the Newton step
  leaves the bracket or does not halve it fast enough. Press, Teukolsky, Vetterling and Flannery,
  "Numerical Recipes", the routine `rtsafe`. The price is strictly increasing in volatility
  (vega > 0), so a sign change of price(vol) - target on the interval guarantees one root.

Rules
- Day count: ACT/365 fixed on calendar time. years = (expiry_ts - snapshot_ts) seconds /
  (365 * 86400), both aware-UTC.
- Search interval for the volatility: [IV_LOW, IV_HIGH] = [0.0001, 10.0] (0.01% to 1000%).
- Typed outcomes, never a silent NaN: `IvSolved` or `IvUnsolved` with a stated reason. Non-finite
  inputs raise `OptionsDataError` naming the field.
- The price must lie strictly inside the no-arbitrage bounds, else "no implied volatility: price
  outside no-arbitrage bounds".
- Low confidence: the price is only known to `price_resolution` (default half a cent). That moves
  the volatility by price_resolution / vega. Above LOW_CONFIDENCE_IV_ERROR (half a vol point) the
  result is labelled "low_vega" and `solve_row` stores no computed block for it.
- American exercise is NOT supported yet: it returns "american_style_not_supported". No
  approximation is invented. A binomial tree is the planned method.
- Quotes are per unit of underlying (per share); the contract multiplier does not scale them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from typing import Literal

from alpha_data.options.pricing import OptionInputs, greeks, price_bounds
from alpha_data.options.schema import (
    STYLES,
    ChainRow,
    Greeks,
    OptionsDataError,
    Quote,
    aware_utc,
    quote_labels,
)

IV_LOW = 1e-4
IV_HIGH = 10.0
DEFAULT_PRICE_RESOLUTION = 0.005
LOW_CONFIDENCE_IV_ERROR = 0.005
DAY_COUNT = "act365f"
_SECONDS_PER_YEAR = 365.0 * 86400.0
_XTOL = 1e-14
_MAX_ITER = 200

Reason = Literal[
    "price_outside_no_arbitrage_bounds",
    "zero_time_to_expiry",
    "american_style_not_supported",
    "implied_vol_outside_search_interval",
    "did_not_converge",
    "no_quote",
    "no_mid",
]
_MESSAGES: dict[str, str] = {
    "price_outside_no_arbitrage_bounds": "price outside no-arbitrage bounds",
    "zero_time_to_expiry": "zero time to expiry",
    "american_style_not_supported": "American style is not supported yet",
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


@dataclass(frozen=True)
class Mid:
    """The mid of a quote, or None with labels saying why there is none."""

    value: float | None
    labels: tuple[str, ...]


def mid_price(quote: Quote) -> Mid:
    """(bid + ask) / 2. A crossed or zero-width quote has no mid. A zero bid is kept, labelled."""
    labels = quote_labels(quote)
    if labels:
        return Mid(None, labels)
    return Mid((quote.bid + quote.ask) / 2.0, ("zero_bid",) if quote.bid == 0.0 else ())


@dataclass(frozen=True)
class IvSolved:
    """A solved volatility with how it was found. `confidence` is "normal" or "low_vega"."""

    iv: float
    confidence: str
    vega: float
    iv_uncertainty: float
    iterations: int
    price: float
    model: str
    inputs: OptionInputs
    greeks: Greeks | None = None


@dataclass(frozen=True)
class IvUnsolved:
    """No volatility, with a typed reason. `message` starts "no implied volatility: "."""

    reason: Reason
    inputs: OptionInputs | None

    @property
    def message(self) -> str:
        return f"no implied volatility: {_MESSAGES[self.reason]}"


def _finite(field: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise OptionsDataError(field, f"must be a finite number, got {value!r}")
    return float(value)


def _root(inp: OptionInputs, target: float) -> tuple[float, int] | Reason:
    """Safeguarded Newton on [IV_LOW, IV_HIGH]; returns (vol, iterations) or a reason."""
    lo, hi = IV_LOW, IV_HIGH
    if greeks(inp, lo).price > target:
        return "implied_vol_outside_search_interval"
    if greeks(inp, hi).price < target:
        return "implied_vol_outside_search_interval"
    guess = math.sqrt(2.0 * math.pi / inp.years) * target / inp.forward / inp.discount
    x = min(max(guess, 2 * lo), hi / 2)
    step = hi - lo
    for iteration in range(1, _MAX_ITER + 1):
        g = greeks(inp, x)
        diff = g.price - target
        if diff == 0.0:
            return x, iteration
        if diff < 0:
            lo = x
        else:
            hi = x
        previous = step
        newton = x - diff / g.vega if g.vega > 0 else math.inf
        if not lo < newton < hi or abs(2.0 * diff) > abs(previous * g.vega):
            new_x = 0.5 * (lo + hi)
            step = hi - lo
        else:
            new_x = newton
            step = abs(new_x - x)
        if abs(new_x - x) < _XTOL or hi - lo < _XTOL:
            return new_x, iteration
        x = new_x
    return "did_not_converge"


def solve_implied_vol(
    inp: OptionInputs,
    target_price: float,
    *,
    style: str,
    price_resolution: float = DEFAULT_PRICE_RESOLUTION,
) -> IvSolved | IvUnsolved:
    """Implied volatility of `target_price` under the model in `inp`, or a typed reason."""
    _finite("price", target_price)
    if _finite("price_resolution", price_resolution) <= 0:
        raise OptionsDataError("price_resolution", "must be above zero")
    if style not in STYLES:
        raise OptionsDataError("style", f"must be one of {STYLES}, got {style!r}")
    if style == "A":
        return IvUnsolved("american_style_not_supported", inp)
    if inp.years <= 0:
        return IvUnsolved("zero_time_to_expiry", inp)
    lower, upper = price_bounds(inp)
    if not lower < target_price < upper:
        return IvUnsolved("price_outside_no_arbitrage_bounds", inp)
    found = _root(inp, target_price)
    if isinstance(found, str):
        return IvUnsolved(found, inp)
    vol, iterations = found
    g = greeks(inp, vol)
    uncertainty = price_resolution / g.vega if g.vega > 0 else math.inf
    return IvSolved(
        iv=vol,
        confidence="low_vega" if uncertainty > LOW_CONFIDENCE_IV_ERROR else "normal",
        vega=g.vega,
        iv_uncertainty=uncertainty,
        iterations=iterations,
        price=target_price,
        model=inp.model,
        inputs=inp,
    )


@dataclass(frozen=True)
class RowSolve:
    """A chain row, with its computed block filled when the solve was normal, and the outcome."""

    row: ChainRow
    outcome: IvSolved | IvUnsolved


def model_tag(inp: OptionInputs) -> str:
    """The stored model name: model, the inputs that were used and the conventions."""
    q = "forward" if inp.dividend_yield is None else repr(inp.dividend_yield)
    return (
        f"{inp.model};r={inp.rate!r};q={q};day_count={DAY_COUNT};"
        "theta=per_calendar_day;vega=per_1.00_vol"
    )


def solve_row(
    row: ChainRow,
    *,
    snapshot_ts: datetime,
    underlying_price: float,
    rate: float,
    dividend_yield: float,
    expiry_time_utc: time,
) -> RowSolve:
    """Solve one row from its mid. The provided slot is never touched; only `computed` is set.

    A low-confidence, unsolved or mid-less row comes back unchanged with the reason in `outcome`.
    """
    contract = row.contract
    expiry_ts = datetime.combine(contract.expiry, expiry_time_utc, UTC)
    inp = OptionInputs(
        underlying=underlying_price,
        kind="spot",
        strike=float(contract.strike),
        years=years_between(snapshot_ts, expiry_ts),
        rate=rate,
        dividend_yield=dividend_yield,
        right=contract.right,
    )
    if row.quote is None:
        return RowSolve(row, IvUnsolved("no_quote", inp))
    mid = mid_price(row.quote).value
    if mid is None:
        return RowSolve(row, IvUnsolved("no_mid", inp))
    out = solve_implied_vol(inp, mid, style=contract.style)
    if isinstance(out, IvUnsolved) or out.confidence != "normal":
        return RowSolve(row, out)
    g = greeks(inp, out.iv)
    block = Greeks(
        source="computed",
        model=model_tag(inp),
        iv=out.iv,
        delta=g.delta,
        gamma=g.gamma,
        vega=g.vega,
        theta=g.theta,
    )
    return RowSolve(replace(row, computed=block), replace(out, greeks=block))
