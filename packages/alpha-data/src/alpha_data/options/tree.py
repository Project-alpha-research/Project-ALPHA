"""American option pricing on a Cox-Ross-Rubinstein binomial tree, with escrowed cash dividends.

Pure math. No data, no network, no clock. Every input is explicit: spot, strike, the valuation and
expiry instants, the rate, the continuous yield, the list of discrete cash dividends and the step
count. Nothing here has a default for the rate or the dividends.

Sources
- Cox, J. C., Ross, S. A. and Rubinstein, M. (1979), "Option pricing: A simplified approach",
  Journal of Financial Economics 7(3): 229-263. Up and down factors u = exp(vol sqrt(dt)) and
  d = 1/u. With a continuous dividend yield q the risk-neutral probability of an up move is
  p = (exp((r - q) dt) - d) / (u - d). Early exercise is checked at every node: the node value
  is max(exercise value, discounted expected value).
- Discrete cash dividends, escrowed-dividend method: the stock is split into a risky part S* and
  the present value of the dividends still to come. The tree is built on S*; at each node the
  exercise value uses S* plus the present value of the dividends not yet paid. This is the
  treatment for known cash dividends in Hull, "Options, Futures, and Other Derivatives" (the
  binomial-tree chapter; edition and page not checked here). Haug, Haug and Lewis (2003), "Back to
  basics: a new approach to the discrete dividend problem", Wilmott Magazine, show its weakness.
- Cross-check: QuantLib 1.44 `FdBlackScholesVanillaEngine` with its Escrowed cash-dividend model
  agrees to a few 1e-4 at 2000 steps (American puts and dividend calls, with and without a yield).

Assumptions, in plain words (all must hold for the number to mean something)
- One constant volatility, constant rate and constant continuous yield to expiry. Trading is
  continuous and there are no transaction costs.
- The volatility is the volatility of S*, the stock less the present value of its dividends. It is
  not the volatility of the quoted stock price. This escrowed treatment is an APPROXIMATION: the
  stock jumps down by the dividend on the ex-date in reality, but here the dividends are folded
  into the starting price. For a large dividend relative to spot, or a long expiry, the value is
  biased against the jump treatments; do not read it as exact. Known weakness (Haug, Haug and
  Lewis): the volatility of S* is not the volatility of S, so one volatility for both misprices,
  most for large dividends and long expiries.
- Escrowed amount: sum D exp(-(r - q)(t_div - t)), so the forward is the usual
  S exp((r - q) T) - sum D exp((r - q)(T - t_div)). With q = 0 it is the plain present value.
- A dividend counts only when valuation < ex-date < expiry. One at or before the valuation
  instant, or at or after expiry, is ignored. A node at time t sees a dividend as unpaid while its
  ex-date is later than t, so exercise "just before the ex-date" is the node before it, up to
  one step early. Measured worst case (a 2.00 dividend on a 100 call, 11 days before a one-year
  expiry, vol 0.25): 7.4e-3 off an 8000-step tree at 500 steps; under 2e-3 for an ex-date far
  from expiry. Pass more steps when an ex-date is close to expiry.
- A dividend whose present value is at or above the spot is an error (S* would be zero or less).
- Time is ACT/365 fixed from aware-UTC instants (same rule as `years_between`).
- No-arbitrage on a step: d < exp((r - q) dt) < u, which is 0 < p < 1. If a step violates it the
  result is a typed `TreeRefused`, never a number. It fails when vol < |r - q| sqrt(dt).
- The price is the average of the N and N + 1 step trees, which damps the odd-even swing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from alpha_data.options.iv_core import years_between
from alpha_data.options.schema import RIGHTS, OptionsDataError, aware_utc

CRR_MODEL = "crr-tree-escrowed-v1"
METHOD = "crr_tree"
DEFAULT_STEPS = 500
MIN_STEPS = 2


def _finite(field: str, value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise OptionsDataError(field, f"must be a finite number, got {value!r}")
    if positive and value <= 0:
        raise OptionsDataError(field, f"must be above zero, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class Dividend:
    """A discrete cash dividend per share: the ex-date instant (aware UTC) and the amount."""

    ex_ts: datetime
    amount: float

    def __post_init__(self) -> None:
        aware_utc("ex_ts", self.ex_ts)
        if _finite("amount", self.amount) <= 0:
            raise OptionsDataError("amount", f"must be above zero, got {self.amount!r}")


@dataclass(frozen=True, kw_only=True)
class AmericanInputs:
    """Everything the tree needs. Dividends outside (valuation, expiry) are ignored."""

    spot: float
    strike: float
    valuation_ts: datetime
    expiry_ts: datetime
    rate: float
    dividend_yield: float
    dividends: tuple[Dividend, ...]
    right: str

    def __post_init__(self) -> None:
        _finite("spot", self.spot, positive=True)
        _finite("strike", self.strike, positive=True)
        _finite("rate", self.rate)
        _finite("dividend_yield", self.dividend_yield)
        if self.right not in RIGHTS:
            raise OptionsDataError("right", f"must be one of {RIGHTS}, got {self.right!r}")
        aware_utc("valuation_ts", self.valuation_ts)
        if aware_utc("expiry_ts", self.expiry_ts) < self.valuation_ts:
            raise OptionsDataError("expiry_ts", "is before the valuation time")

    @property
    def years(self) -> float:
        return years_between(self.valuation_ts, self.expiry_ts)

    @property
    def sign(self) -> float:
        return 1.0 if self.right == "C" else -1.0

    def live_dividends(self) -> list[tuple[float, float]]:
        """(years from valuation, amount) for dividends strictly inside (valuation, expiry)."""
        return [
            (years_between(self.valuation_ts, d.ex_ts), d.amount)
            for d in self.dividends
            if self.valuation_ts < d.ex_ts < self.expiry_ts
        ]


@dataclass(frozen=True)
class TreeRefused:
    """A step size that breaks d < exp((r - q) dt) < u. There is no price."""

    steps: int
    up: float
    down: float
    growth: float

    @property
    def message(self) -> str:
        return (
            f"tree refused: step violates no-arbitrage (d={self.down!r}, "
            f"exp((r-q)dt)={self.growth!r}, u={self.up!r}) at {self.steps} steps"
        )


def min_tree_vol(inp: AmericanInputs, steps: int) -> float:
    """The volatility below which a `steps`-step tree breaks no-arbitrage: |r - q| sqrt(T/steps)."""
    return abs(inp.rate - inp.dividend_yield) * math.sqrt(inp.years / steps)


def _check_steps(steps: int) -> None:
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < MIN_STEPS:
        raise OptionsDataError(
            "steps", f"must be an integer of at least {MIN_STEPS}, got {steps!r}"
        )


def _remaining_pv(
    live: list[tuple[float, float]], carry: float, dt: float, steps: int
) -> np.ndarray:
    """Escrowed amount at each step time: sum D exp(-(r - q)(t_div - t)) over later ex-dates."""
    times = np.arange(steps + 1) * dt
    pv = np.zeros(steps + 1)
    for t_div, amount in live:
        mask = times < t_div
        pv[mask] += amount * np.exp(-carry * (t_div - times[mask]))
    return pv


Levels = list[tuple[np.ndarray, np.ndarray]]


def _induct(inp: AmericanInputs, vol: float, steps: int) -> Levels | TreeRefused:
    """Backward induction with O(steps) arrays. (values, stock prices) for levels 0, 1 and 2."""
    _check_steps(steps)
    _finite("vol", vol, positive=True)
    years = inp.years
    if years <= 0:
        raise OptionsDataError("years", "must be above zero to price an option")
    live = inp.live_dividends()
    carry = inp.rate - inp.dividend_yield
    pv_all = sum(a * math.exp(-carry * t) for t, a in live)
    if pv_all >= inp.spot:
        raise OptionsDataError("dividends", "present value of dividends must be below the spot")
    dt = years / steps
    sd = vol * math.sqrt(dt)
    up, down, growth = math.exp(sd), math.exp(-sd), math.exp(carry * dt)
    if not down < growth < up:
        return TreeRefused(steps, up, down, growth)
    prob = (growth - down) / (up - down)
    disc = math.exp(-inp.rate * dt)
    base = inp.spot - pv_all
    pv_left = _remaining_pv(live, carry, dt, steps)
    phi = inp.sign
    j = np.arange(steps + 1)
    node = base * np.exp((2 * j - steps) * sd)
    values = np.maximum(phi * (node - inp.strike), 0.0)
    levels: Levels = []
    for i in range(steps - 1, -1, -1):
        values = disc * (prob * values[1:] + (1.0 - prob) * values[:-1])
        stock = base * np.exp((2 * j[: i + 1] - i) * sd) + pv_left[i]
        values = np.maximum(values, phi * (stock - inp.strike))
        if i <= 2:
            levels.insert(0, (values, stock))
    return levels


def crr_tree_value(inp: AmericanInputs, vol: float, steps: int) -> float | TreeRefused:
    """One tree of exactly `steps` steps (no averaging)."""
    levels = _induct(inp, vol, steps)
    return levels if isinstance(levels, TreeRefused) else float(levels[0][0][0])


def tree_price_delta_gamma(
    inp: AmericanInputs, vol: float, steps: int
) -> tuple[float, float, float] | TreeRefused:
    """Price, delta and gamma from the first tree levels, averaged over the N and N + 1 trees.

    delta = (V_u - V_d) / (S_u - S_d) at step 1; gamma is the change of the step-2 slopes over half
    the step-2 spread (Hull, the binomial-tree greeks). They are taken one or two steps after the
    valuation instant, an error of order 1/steps like the price.
    """
    out: list[tuple[float, float, float]] = []
    for n in (steps, steps + 1):
        levels = _induct(inp, vol, n)
        if isinstance(levels, TreeRefused):
            return levels
        (v0, _), (v1, s1), (v2, s2) = levels
        slope_dn = (v2[1] - v2[0]) / (s2[1] - s2[0])
        slope_up = (v2[2] - v2[1]) / (s2[2] - s2[1])
        out.append((float(v0[0]), (v1[1] - v1[0]) / (s1[1] - s1[0]),
                    (slope_up - slope_dn) / (0.5 * (s2[2] - s2[0]))))  # fmt: skip
    (p0, d0, g0), (p1, d1, g1) = out
    return float(0.5 * (p0 + p1)), float(0.5 * (d0 + d1)), float(0.5 * (g0 + g1))


def american_price(
    inp: AmericanInputs, vol: float, steps: int = DEFAULT_STEPS
) -> float | TreeRefused:
    """Average of the N and N + 1 step trees; `TreeRefused` if either step breaks no-arbitrage."""
    first = crr_tree_value(inp, vol, steps)
    if isinstance(first, TreeRefused):
        return first
    second = crr_tree_value(inp, vol, steps + 1)
    if isinstance(second, TreeRefused):
        return second
    return 0.5 * (first + second)
