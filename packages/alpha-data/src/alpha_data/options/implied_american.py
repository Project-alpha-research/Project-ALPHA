"""Implied volatility for American-style options, priced on the CRR tree.

Pure math. The tree, the escrowed dividends and their assumptions are in `alpha_data.options.tree`;
the root finder, result types and the low-confidence rule are in `iv_core`.

Sources
- Same safeguarded bracketed Newton as the closed-form solver (Numerical Recipes `rtsafe`, see
  `iv_core`). The price on a fixed tree is continuous and strictly increasing in volatility, so a
  sign change on the interval brackets a root. The slope is a forward difference on the tree
  (bump 0.001 in volatility); it only steers Newton, the bracket guarantees convergence.

Rules
- Bounds for American options differ from European ones: the lower bound is the immediate exercise
  value, max(S - K, 0) for a call and max(K - S, 0) for a put (not the discounted European
  bound); the upper bound is S for a call and K for a put. A price at or below the exercise value,
  or at or above the cap, is "price outside no-arbitrage bounds".
- Search interval: [max(IV_LOW, 1.01 |r - q| sqrt(T / steps)), IV_HIGH]. Below that lower end the
  tree breaks no-arbitrage (see `min_tree_vol`), so a price there is the typed outcome
  "implied_vol_outside_search_interval" and never a clamped number.
- Volatility tolerance 1e-9. The low-confidence rule (`iv_uncertainty = price_resolution / vega`
  above 0.005) is the same as for European contracts; vega is the tree's finite difference.
- Time: one solve at 500 steps costs a few dozen tree prices; seconds per solve and per
  100-contract chain are in docs/reference/invariants/data-options.md.
"""

from __future__ import annotations

import math

from alpha_data.options.iv_core import (
    DEFAULT_PRICE_RESOLUTION,
    IV_HIGH,
    IV_LOW,
    LOW_CONFIDENCE_IV_ERROR,
    IvSolved,
    IvUnsolved,
    finite,
    safeguarded_root,
)
from alpha_data.options.pricing import DAY_COUNT
from alpha_data.options.schema import OptionsDataError
from alpha_data.options.tree import (
    CRR_MODEL,
    DEFAULT_STEPS,
    METHOD,
    AmericanInputs,
    TreeRefused,
    american_price,
    min_tree_vol,
)
from alpha_data.options.tree_greeks import american_greeks

_XTOL = 1e-9
_SLOPE_BUMP = 1e-3
_LOW_MARGIN = 1.01


def american_bounds(inp: AmericanInputs) -> tuple[float, float]:
    """(exercise value, cap): max(phi (S - K), 0) and S for a call or K for a put."""
    exercise = max(inp.sign * (inp.spot - inp.strike), 0.0)
    return exercise, inp.spot if inp.right == "C" else inp.strike


def american_model_tag(inp: AmericanInputs, steps: int) -> str:
    """The stored model name. Parseable: split on ";" then on the first "=".

    `crr-tree-escrowed-v1;model=crr_tree;steps=<n>;r=<rate>;q=<yield>;divs=<list>;`
    `day_count=act365f;theta=per_calendar_day;vega=per_1.00_vol`. `divs` is "none" or the dividends
    inside the option's life as `<ex-date ISO instant>:<amount>` joined by "|".
    """
    live = sorted(
        (d for d in inp.dividends if inp.valuation_ts < d.ex_ts < inp.expiry_ts),
        key=lambda d: d.ex_ts,
    )
    divs = "|".join(f"{d.ex_ts.isoformat()}:{d.amount!r}" for d in live) or "none"
    return (
        f"{CRR_MODEL};model={METHOD};steps={steps};r={inp.rate!r};q={inp.dividend_yield!r};"
        f"divs={divs};day_count={DAY_COUNT};theta=per_calendar_day;vega=per_1.00_vol"
    )


def _price(inp: AmericanInputs, vol: float, steps: int) -> float:
    out = american_price(inp, vol, steps)
    if isinstance(out, TreeRefused):
        raise OptionsDataError("vol", out.message)
    return out


def solve_american_implied_vol(
    inp: AmericanInputs,
    target_price: float,
    *,
    steps: int = DEFAULT_STEPS,
    price_resolution: float = DEFAULT_PRICE_RESOLUTION,
) -> IvSolved | IvUnsolved:
    """Implied volatility of `target_price` on the `steps`-step CRR tree, or a typed reason."""
    finite("price", target_price)
    if finite("price_resolution", price_resolution) <= 0:
        raise OptionsDataError("price_resolution", "must be above zero")
    if inp.years <= 0:
        return IvUnsolved("zero_time_to_expiry", inp)
    exercise, cap = american_bounds(inp)
    if not exercise < target_price < cap:
        return IvUnsolved("price_outside_no_arbitrage_bounds", inp)
    low = max(IV_LOW, _LOW_MARGIN * min_tree_vol(inp, steps))

    def func(x: float) -> tuple[float, float]:
        here = _price(inp, x, steps)
        return here, (_price(inp, x + _SLOPE_BUMP, steps) - here) / _SLOPE_BUMP

    guess = math.sqrt(2.0 * math.pi / inp.years) * target_price / inp.spot
    found = safeguarded_root(func, target_price, lo=low, hi=IV_HIGH, guess=guess, xtol=_XTOL)
    if isinstance(found, str):
        return IvUnsolved(found, inp)
    vol, iterations = found
    g = american_greeks(inp, vol, steps)
    if isinstance(g, TreeRefused):
        return IvUnsolved("did_not_converge", inp)
    uncertainty = price_resolution / g.vega if g.vega > 0 else math.inf
    return IvSolved(
        iv=vol,
        confidence="low_vega" if uncertainty > LOW_CONFIDENCE_IV_ERROR else "normal",
        vega=g.vega,
        iv_uncertainty=uncertainty,
        iterations=iterations,
        price=target_price,
        model=american_model_tag(inp, steps),
        inputs=inp,
        conventions=g.conventions,
        method=METHOD,
        steps=steps,
    )
