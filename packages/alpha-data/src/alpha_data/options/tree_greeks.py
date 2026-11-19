"""Greeks of an American option on the CRR tree: tree levels for delta and gamma, bumps otherwise.

Pure math; the tree and its assumptions are in `alpha_data.options.tree`. Every price is the
average of the N and N + 1 step trees, and every bump (vol, rate, time) re-prices the whole tree.

Conventions (the same as the European code; the result carries a `Conventions` record)
- `delta` and `gamma` are with respect to the spot, read from the tree's first levels
  (`tree_price_delta_gamma`; no bump). A spot bump of 3% was 10 to 100 times less accurate: its
  gamma was 3.1e-3 off on an 18-day call (gamma 0.089) and 5.2e-3 off on a put near the exercise
  boundary, against under 1e-4 from the tree levels.
- `vega` per 1.00 of volatility: central difference, bump 0.01 (one vol point), divided by 0.02.
  If the lower bump breaks the step's no-arbitrage limit, a forward difference is used instead.
- `theta` per CALENDAR DAY: the derivative with respect to calendar time at fixed spot, taken by
  moving the valuation instant one day each way (a smaller bump, a quarter of the time left, for
  an option with under four days to run). Cash dividends and expiry stay at their instants.
- `rho` per 1.00 of the rate: central difference, bump 0.005 (50 basis points), divided by 0.01.
  The cash-dividend present values move with the rate; the spot and the yield are held.

Expected numerical noise at 500 steps (measured against the closed form for a call with no
dividends, S = K = 100, vol 0.2, one year): price 2.5e-4, delta 9e-5, gamma 2.3e-5 (true 0.019),
vega 2e-3 (true 37.5), theta 1e-6 per day, rho 0.011 (true 53). Tree error is of order 1/steps,
so halving the steps roughly doubles it. A bump that makes a tree refuse (see
`TreeRefused`) returns the refusal instead of a number.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from alpha_data.options.pricing import Conventions
from alpha_data.options.tree import (
    DEFAULT_STEPS,
    METHOD,
    AmericanInputs,
    TreeRefused,
    american_price,
    min_tree_vol,
    tree_price_delta_gamma,
)

BUMPS: dict[str, float] = {
    "vol": 0.01,
    "rate": 0.005,
    "time_days": 1.0,
}


@dataclass(frozen=True)
class AmericanGreeks:
    """Price and greeks on the tree, with units in `conventions`, `method` and the step count."""

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    conventions: Conventions
    method: str
    steps: int


class _Refused(Exception):
    """Internal: carries a tree refusal out of the bumped prices."""

    def __init__(self, refusal: TreeRefused) -> None:
        super().__init__(refusal.message)
        self.refusal = refusal


def american_greeks(
    inp: AmericanInputs, vol: float, steps: int = DEFAULT_STEPS
) -> AmericanGreeks | TreeRefused:
    """Price, delta, gamma, vega, theta (per calendar day) and rho by bumping the tree."""
    try:
        return _bumped(inp, vol, steps)
    except _Refused as stop:
        return stop.refusal


def tree_vega(inp: AmericanInputs, vol: float, steps: int, base: float) -> float | TreeRefused:
    """Vega per 1.00 of vol: central bump of 0.01, forward when the lower bump breaks the tree."""
    dv = BUMPS["vol"]
    up = american_price(inp, vol + dv, steps)
    if isinstance(up, TreeRefused):
        return up
    if vol - dv <= min_tree_vol(inp, steps):
        return (up - base) / dv
    down = american_price(inp, vol - dv, steps)
    return down if isinstance(down, TreeRefused) else (up - down) / (2 * dv)


def _bumped(inp: AmericanInputs, vol: float, steps: int) -> AmericanGreeks:
    def px(candidate: AmericanInputs) -> float:
        out = american_price(candidate, vol, steps)
        if isinstance(out, TreeRefused):
            raise _Refused(out)
        return out

    first = tree_price_delta_gamma(inp, vol, steps)
    if isinstance(first, TreeRefused):
        raise _Refused(first)
    base, delta, gamma = first
    vega = tree_vega(inp, vol, steps, base)
    if isinstance(vega, TreeRefused):
        raise _Refused(vega)
    day = min(BUMPS["time_days"], 0.25 * (inp.expiry_ts - inp.valuation_ts).total_seconds() / 86400)
    dr = BUMPS["rate"]
    shift = timedelta(days=day)
    r_up, r_dn = px(replace(inp, rate=inp.rate + dr)), px(replace(inp, rate=inp.rate - dr))
    t_up = px(replace(inp, valuation_ts=inp.valuation_ts + shift))
    t_dn = px(replace(inp, valuation_ts=inp.valuation_ts - shift))
    return AmericanGreeks(
        price=base,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=(t_up - t_dn) / (2 * day),
        rho=(r_up - r_dn) / (2 * dr),
        conventions=Conventions(delta_gamma_wrt="spot"),
        method=METHOD,
        steps=steps,
    )
