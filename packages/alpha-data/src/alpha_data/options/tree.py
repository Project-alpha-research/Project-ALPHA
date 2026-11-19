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
  treatment in Hull, "Options, Futures, and Other Derivatives" (the binomial-tree and
  known-dividend sections). Haug, Haug and Lewis (2003), "Back to basics: a new approach to the
  discrete dividend problem", Wilmott Magazine, discuss its limits.

Assumptions, in plain words (all must hold for the number to mean something)
- One constant volatility, constant rate and constant continuous yield to expiry. Trading is
  continuous and there are no transaction costs.
- The volatility is the volatility of S*, the stock less the present value of its dividends. It is
  not the volatility of the quoted stock price. This escrowed treatment is an APPROXIMATION: the
  stock jumps down by the dividend on the ex-date in reality, but here the dividends are folded
  into the starting price. For a large dividend relative to spot, or a long expiry, the value is
  biased against the jump treatments; do not read it as exact.
- The yield q is applied to the S* process; the cash dividends are discounted at the rate r.
- A dividend counts only when valuation < ex-date < expiry. One at or before the valuation
  instant, or at or after expiry, is ignored. A node at time t sees a dividend as unpaid while its
  ex-date is later than t, so exercise "just before the ex-date" is the node before it.
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
    live: list[tuple[float, float]], rate: float, dt: float, steps: int
) -> np.ndarray:
    """Present value at each step time of the dividends whose ex-date is still later."""
    times = np.arange(steps + 1) * dt
    pv = np.zeros(steps + 1)
    for t_div, amount in live:
        mask = times < t_div
        pv[mask] += amount * np.exp(-rate * (t_div - times[mask]))
    return pv


def crr_tree_value(inp: AmericanInputs, vol: float, steps: int) -> float | TreeRefused:
    """One tree of exactly `steps` steps (no averaging)."""
    _check_steps(steps)
    _finite("vol", vol, positive=True)
    years = inp.years
    if years <= 0:
        raise OptionsDataError("years", "must be above zero to price an option")
    live = inp.live_dividends()
    pv_all = sum(a * math.exp(-inp.rate * t) for t, a in live)
    if pv_all >= inp.spot:
        raise OptionsDataError("dividends", "present value of dividends must be below the spot")
    dt = years / steps
    sd = vol * math.sqrt(dt)
    up, down, growth = math.exp(sd), math.exp(-sd), math.exp((inp.rate - inp.dividend_yield) * dt)
    if not down < growth < up:
        return TreeRefused(steps, up, down, growth)
    prob = (growth - down) / (up - down)
    disc = math.exp(-inp.rate * dt)
    base = inp.spot - pv_all
    pv_left = _remaining_pv(live, inp.rate, dt, steps)
    phi = inp.sign
    j = np.arange(steps + 1)
    node = base * np.exp((2 * j - steps) * sd)
    values = np.maximum(phi * (node - inp.strike), 0.0)
    for i in range(steps - 1, -1, -1):
        values = disc * (prob * values[1:] + (1.0 - prob) * values[:-1])
        node = base * np.exp((2 * j[: i + 1] - i) * sd)
        values = np.maximum(values, phi * (node + pv_left[i] - inp.strike))
    return float(values[0])


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
