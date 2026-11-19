"""Implied volatility: day count, mid price, a bracketed root finder and the computed greeks block.

Pure math plus the layer's records. No data reads, no clock.

Sources
- The closed-form models are in `alpha_data.options.pricing` (Black-Scholes-Merton, Black-76); the
  American tree is in `alpha_data.options.tree`, its solver in `implied_american`. The root
  finder, result types and the low-confidence rule are in `iv_core`.

Rules
- Typed outcomes, never a silent NaN: `IvSolved` or `IvUnsolved` with a stated reason. Non-finite
  inputs raise `OptionsDataError` naming the field.
- European: the price must lie strictly inside the no-arbitrage bounds, else "no implied
  volatility: price outside no-arbitrage bounds".
- Mid: a crossed, zero-width or zero-bid quote has no mid. A zero bid is never averaged.
- Expiry time: the contract has only a date. The caller passes the exchange's expiry cut-off in UTC
  (`expiry_time_utc`), for example the settlement-price time of the series.
- `solve_row` prices European-style contracts in closed form and American-style contracts on the
  CRR tree (explicit dividends and step count required; both are recorded in the model tag).
- Quotes are per unit of underlying (per share); the contract multiplier does not scale them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time

from alpha_data.options.implied_american import american_model_tag, solve_american_implied_vol
from alpha_data.options.iv_core import (
    DEFAULT_PRICE_RESOLUTION,
    IV_HIGH,
    IV_LOW,
    LOW_CONFIDENCE_IV_ERROR,
    IvSolved,
    IvUnsolved,
    Reason,
    finite,
    safeguarded_root,
    years_between,
)
from alpha_data.options.pricing import (
    DAY_COUNT,
    OptionInputs,
    greeks,
    price_bounds,
)
from alpha_data.options.schema import (
    STYLES,
    ChainRow,
    Greeks,
    OptionsDataError,
    Quote,
    quote_labels,
)
from alpha_data.options.tree import DEFAULT_STEPS, AmericanInputs, Dividend, TreeRefused
from alpha_data.options.tree_greeks import american_greeks

__all__ = [
    "DEFAULT_PRICE_RESOLUTION",
    "IV_HIGH",
    "IV_LOW",
    "LOW_CONFIDENCE_IV_ERROR",
    "IvSolved",
    "IvUnsolved",
    "Mid",
    "Reason",
    "RowSolve",
    "mid_price",
    "model_tag",
    "solve_implied_vol",
    "solve_row",
    "years_between",
]

_XTOL = 1e-14


@dataclass(frozen=True)
class Mid:
    """The mid of a quote, or None with labels saying why there is none."""

    value: float | None
    labels: tuple[str, ...]


def mid_price(quote: Quote) -> Mid:
    """(bid + ask) / 2. A crossed, zero-width or zero-bid quote has no mid, only its label."""
    labels = quote_labels(quote)
    if labels:
        return Mid(None, labels)
    if quote.bid == 0.0:
        return Mid(None, ("zero_bid",))
    return Mid((quote.bid + quote.ask) / 2.0, ())


def _root(inp: OptionInputs, target: float) -> tuple[float, int] | Reason:
    def func(x: float) -> tuple[float, float]:
        g = greeks(inp, x)
        return g.price, g.vega

    guess = math.sqrt(2.0 * math.pi / inp.years) * target / inp.forward / inp.discount
    return safeguarded_root(func, target, lo=IV_LOW, hi=IV_HIGH, guess=guess, xtol=_XTOL)


def solve_implied_vol(
    inp: OptionInputs,
    target_price: float,
    *,
    style: str,
    price_resolution: float = DEFAULT_PRICE_RESOLUTION,
) -> IvSolved | IvUnsolved:
    """Implied volatility of `target_price` under the model in `inp`, or a typed reason."""
    finite("price", target_price)
    if finite("price_resolution", price_resolution) <= 0:
        raise OptionsDataError("price_resolution", "must be above zero")
    if style not in STYLES:
        raise OptionsDataError("style", f"must be one of {STYLES}, got {style!r}")
    if style == "A":
        return IvUnsolved("american_style_needs_tree_inputs", inp)
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
        conventions=g.conventions,
    )


@dataclass(frozen=True)
class RowSolve:
    """A chain row, with its computed block filled when the solve was normal, and the outcome."""

    row: ChainRow
    outcome: IvSolved | IvUnsolved
    labels: tuple[str, ...] = ()


def model_tag(inp: OptionInputs) -> str:
    """The stored model name: model, the inputs that were used and the conventions.

    Format (stable, parseable): `<model>;r=<rate>;q=<yield or "forward">;day_count=act365f;`
    `theta=per_calendar_day;vega=per_1.00_vol`. Split on ";" then on the first "="; numbers are
    Python's shortest round-trip float text, so float(text) gives the input back exactly.
    """
    q = "forward" if inp.dividend_yield is None else repr(inp.dividend_yield)
    return (
        f"{inp.model};r={inp.rate!r};q={q};day_count={DAY_COUNT};"
        "theta=per_calendar_day;vega=per_1.00_vol"
    )


def _american_row(
    row: ChainRow,
    inp: AmericanInputs,
    mid: float,
    steps: int,
) -> RowSolve:
    out = solve_american_implied_vol(inp, mid, steps=steps)
    if isinstance(out, IvUnsolved) or out.confidence != "normal":
        return RowSolve(row, out)
    g = american_greeks(inp, out.iv, steps)
    if isinstance(g, TreeRefused):  # a bumped tree broke no-arbitrage: keep the IV, label the row
        block = Greeks(source="computed", model=american_model_tag(inp, steps), iv=out.iv)
        return RowSolve(
            replace(row, computed=block), replace(out, greeks=block), ("greeks_not_available",)
        )
    block = Greeks(
        source="computed",
        model=american_model_tag(inp, steps),
        iv=out.iv,
        delta=g.delta,
        gamma=g.gamma,
        vega=g.vega,
        theta=g.theta,
    )
    return RowSolve(replace(row, computed=block), replace(out, greeks=block))


def solve_row(
    row: ChainRow,
    *,
    snapshot_ts: datetime,
    underlying_price: float,
    rate: float,
    dividend_yield: float,
    expiry_time_utc: time,
    dividends: Sequence[Dividend] | None = None,
    steps: int = DEFAULT_STEPS,
) -> RowSolve:
    """Solve one row from its mid. The provided slot is never touched; only `computed` is set.

    European-style contracts use the closed form. American-style contracts use the CRR tree and
    need `dividends` stated (pass `()` for none; `None` raises) and a step count (default 500,
    recorded in the model tag). A low-confidence, unsolved or mid-less row comes back unchanged
    with the reason in `outcome`. If a bumped greek tree breaks no-arbitrage, `computed` holds the
    IV only and `labels` is ("greeks_not_available",).
    """
    contract = row.contract
    expiry_ts = datetime.combine(contract.expiry, expiry_time_utc, UTC)
    american = contract.style == "A"
    if american and dividends is None:
        raise OptionsDataError(
            "dividends",
            "must be stated for an American-style contract: pass dividends=() for none, or the "
            "Dividend(ex_ts, amount) list; None never means no dividends",
        )
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
    if american:
        tree_inp = AmericanInputs(
            spot=underlying_price,
            strike=float(contract.strike),
            valuation_ts=snapshot_ts,
            expiry_ts=expiry_ts,
            rate=rate,
            dividend_yield=dividend_yield,
            dividends=tuple(dividends or ()),
            right=contract.right,
        )
        return _american_row(row, tree_inp, mid, steps)
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
