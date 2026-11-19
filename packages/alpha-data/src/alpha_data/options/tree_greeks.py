"""Greeks of an American option by finite differences on the CRR tree.

Pure math; the tree and its assumptions are in `alpha_data.options.tree`. Every price is the
average of the N and N + 1 step trees, and every bump re-prices the whole tree.

Conventions (the same as the European code; the result carries a `Conventions` record)
- `delta` and `gamma` are with respect to the spot. Central differences, bump of 3% of spot:
  delta = (V(S+h) - V(S-h)) / 2h, gamma = (V(S+h) - 2 V(S) + V(S-h)) / h^2.
- `vega` per 1.00 of volatility: central difference, bump 0.01 (one vol point), divided by 0.02.
  If the lower bump breaks the step's no-arbitrage limit, a forward difference is used instead.
- `theta` per CALENDAR DAY: the derivative with respect to calendar time at fixed spot, taken by
  moving the valuation instant one day each way (a smaller bump, a quarter of the time left, for
  an option with under four days to run). Cash dividends and expiry stay at their instants.
- `rho` per 1.00 of the rate: central difference, bump 0.005 (50 basis points), divided by 0.01.
  The cash-dividend present values move with the rate; the spot and the yield are held.

Expected numerical noise at 500 steps (measured against the closed form for a call with no
dividends, S = K = 100, vol 0.2, one year): price 2.5e-4, delta 8e-4, gamma 3.5e-4 (true 0.019),
vega 2e-3 (true 37.5), theta 1e-6 per day, rho 0.011 (true 53). Gamma is the noisiest: a bump of
1% of spot gave errors near 0.0016 (tree-node alignment wiggle), so the bump is 3%. Tree error is of
order 1/steps, so halving the steps roughly doubles it. A bump that makes a tree refuse (see
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
)

BUMPS: dict[str, float] = {
    "spot_relative": 0.03,
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


def _bumped(inp: AmericanInputs, vol: float, steps: int) -> AmericanGreeks:
    def px(candidate: AmericanInputs, v: float = vol) -> float:
        out = american_price(candidate, v, steps)
        if isinstance(out, TreeRefused):
            raise _Refused(out)
        return out

    h = BUMPS["spot_relative"] * inp.spot
    day = min(BUMPS["time_days"], 0.25 * (inp.expiry_ts - inp.valuation_ts).total_seconds() / 86400)
    dv, dr = BUMPS["vol"], BUMPS["rate"]
    shift = timedelta(days=day)
    base = px(inp)
    s_up, s_dn = px(replace(inp, spot=inp.spot + h)), px(replace(inp, spot=inp.spot - h))
    r_up, r_dn = px(replace(inp, rate=inp.rate + dr)), px(replace(inp, rate=inp.rate - dr))
    t_up = px(replace(inp, valuation_ts=inp.valuation_ts + shift))
    t_dn = px(replace(inp, valuation_ts=inp.valuation_ts - shift))
    v_up = px(inp, vol + dv)
    if vol - dv > min_tree_vol(inp, steps):
        vega = (v_up - px(inp, vol - dv)) / (2 * dv)
    else:
        vega = (v_up - base) / dv
    return AmericanGreeks(
        price=base,
        delta=(s_up - s_dn) / (2 * h),
        gamma=(s_up - 2 * base + s_dn) / (h * h),
        vega=vega,
        theta=(t_up - t_dn) / (2 * day),
        rho=(r_up - r_dn) / (2 * dr),
        conventions=Conventions(delta_gamma_wrt="spot"),
        method=METHOD,
        steps=steps,
    )
