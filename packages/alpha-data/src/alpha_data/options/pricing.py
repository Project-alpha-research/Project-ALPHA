"""European option pricing and greeks: Black-Scholes-Merton (spot) and Black-76 (forward).

Pure math. No data, no network, no clock. Every input is explicit: the caller passes the rate and
the dividend yield (or the forward), and nothing here has a default for them.

Sources
- Black, F. and Scholes, M. (1973), "The Pricing of Options and Corporate Liabilities", Journal of
  Political Economy 81(3): the call formula (their eq. 13). The put follows by put-call parity.
- Merton, R. C. (1973), "Theory of Rational Option Pricing", Bell Journal of Economics and
  Management Science 4(1): the same formula with a continuous dividend yield.
- Black, F. (1976), "The pricing of commodity contracts", Journal of Financial Economics 3(1-2):
  options on a forward or futures price.
- Greeks: the partial derivatives of those formulas, as in Hull, "Options, Futures, and Other
  Derivatives" (the chapter on the Greek letters). Every greek is also checked against a central
  finite difference of the price in tests/unit/test_options_pricing.py.

Assumptions, in plain words (all must hold for the number to mean something)
- The exercise is European: only at expiry. American contracts are priced in
  `alpha_data.options.tree`.
- The underlying follows a geometric Brownian motion with one constant volatility to expiry.
- The risk-free rate and the dividend yield are constant and continuously compounded.
- No transaction costs, no borrow cost beyond the yield, and trading is continuous.
- Black-76: the underlying is the forward price for the option's own expiry. The rate only
  discounts.
- Time to expiry is in years (ACT/365 fixed, see `alpha_data.options.implied.years_between`).

Conventions (the stored computed block uses these; every result carries them in `conventions`)
- `vega` is the derivative with respect to volatility per 1.00 (100 vol points). Divide by 100 for
  one vol point.
- `theta` is the change in price per CALENDAR DAY (the derivative with respect to calendar time
  divided by 365). Multiply by 365 for per year. It is normally negative for a long option.
- `rho` is per 1.00 of the rate (BSM: spot and yield held fixed; Black-76: forward held fixed, so
  rho = -years * price).
- `delta` and `gamma` are with respect to the input `underlying` (the spot for BSM, the forward for
  Black-76).
- Converting a provider's numbers before any comparison: theta per trading day = ALPHA theta * 365
  / 252 (if the provider uses 252 trading days); theta per year = ALPHA theta * 365; vega per vol
  point = ALPHA vega / 100; rho per 1% of rate = ALPHA rho / 100.

Edges: the price needs years > 0 and vol > 0, and vol * sqrt(years) must not be zero in floating
point (a named error, never a division by zero). As vol or years falls to zero the price tends to
the discounted intrinsic on the FORWARD, max(phi D (F - K), 0), not on the spot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from alpha_data.options.schema import RIGHTS, OptionsDataError

BSM_MODEL = "black-scholes-merton-v1"
BLACK76_MODEL = "black-76-v1"
KINDS = ("spot", "forward")
DAY_COUNT = "act365f"
_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)


def _finite(
    field: str, value: object, *, positive: bool = False, minimum: float | None = None
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise OptionsDataError(field, f"must be a finite number, got {value!r}")
    if positive and value <= 0:
        raise OptionsDataError(field, f"must be above zero, got {value!r}")
    if minimum is not None and value < minimum:
        raise OptionsDataError(field, f"must not be below {minimum:g}, got {value!r}")
    return float(value)


@dataclass(frozen=True, kw_only=True)
class OptionInputs:
    """Everything the model needs. `underlying` is the spot (kind "spot") or the forward.

    `dividend_yield` is required for a spot and must be None for a forward (the forward already
    carries it). `years` may be zero here; pricing needs it above zero.
    """

    underlying: float
    kind: str
    strike: float
    years: float
    rate: float
    dividend_yield: float | None
    right: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise OptionsDataError("kind", f"must be one of {KINDS}, got {self.kind!r}")
        _finite("underlying", self.underlying, positive=True)
        _finite("strike", self.strike, positive=True)
        _finite("years", self.years, minimum=0.0)
        _finite("rate", self.rate)
        if self.kind == "spot":
            _finite("dividend_yield", self.dividend_yield)
        elif self.dividend_yield is not None:
            raise OptionsDataError(
                "dividend_yield", "must be None when the underlying is a forward"
            )
        if self.right not in RIGHTS:
            raise OptionsDataError("right", f"must be one of {RIGHTS}, got {self.right!r}")

    @property
    def model(self) -> str:
        return BSM_MODEL if self.kind == "spot" else BLACK76_MODEL

    @property
    def discount(self) -> float:
        return math.exp(-self.rate * self.years)

    @property
    def forward(self) -> float:
        if self.kind == "forward":
            return self.underlying
        assert self.dividend_yield is not None
        return self.underlying * math.exp((self.rate - self.dividend_yield) * self.years)

    @property
    def sign(self) -> float:
        return 1.0 if self.right == "C" else -1.0


@dataclass(frozen=True, kw_only=True)
class Conventions:
    """The units of every greek in a result, so a provider's units are never mixed in silently."""

    delta_gamma_wrt: str
    vega: str = "per_1.00_vol"
    theta: str = "per_calendar_day"
    rho: str = "per_1.00_rate"
    day_count: str = DAY_COUNT


@dataclass(frozen=True)
class ModelGreeks:
    """Price and greeks at one volatility, with their units in `conventions`."""

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    conventions: Conventions


def _cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / _SQRT2)


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT2PI


def _check_vol(inp: OptionInputs, vol: float) -> None:
    _finite("vol", vol, positive=True)
    if inp.years <= 0:
        raise OptionsDataError("years", "must be above zero to price an option")
    if vol * math.sqrt(inp.years) == 0.0:
        raise OptionsDataError("vol", "vol * sqrt(years) is zero in floating point")


def _d1(inp: OptionInputs, vol: float) -> tuple[float, float]:
    sd = vol * math.sqrt(inp.years)
    d1 = (math.log(inp.forward / inp.strike) + 0.5 * sd * sd) / sd
    return d1, d1 - sd


def price(inp: OptionInputs, vol: float) -> float:
    """Model price per unit of underlying: D * (phi F N(phi d1) - phi K N(phi d2))."""
    _check_vol(inp, vol)
    d1, d2 = _d1(inp, vol)
    phi = inp.sign
    return inp.discount * phi * (inp.forward * _cdf(phi * d1) - inp.strike * _cdf(phi * d2))


def price_bounds(inp: OptionInputs) -> tuple[float, float]:
    """No-arbitrage bounds (lower, upper) for a European option, dividends and rate included.

    Call: max(D (F - K), 0) up to D F. Put: max(D (K - F), 0) up to D K. D is exp(-rate * years).
    """
    d, fwd = inp.discount, inp.forward
    lower = max(inp.sign * d * (fwd - inp.strike), 0.0)
    upper = d * fwd if inp.right == "C" else d * inp.strike
    return lower, upper


def greeks(inp: OptionInputs, vol: float) -> ModelGreeks:
    """Price, delta, gamma, vega, theta (per calendar day) and rho at one volatility."""
    _check_vol(inp, vol)
    d1, d2 = _d1(inp, vol)
    phi, d, fwd, t = inp.sign, inp.discount, inp.forward, inp.years
    sqrt_t = math.sqrt(t)
    value = d * phi * (fwd * _cdf(phi * d1) - inp.strike * _cdf(phi * d2))
    if inp.kind == "spot":
        assert inp.dividend_yield is not None
        scale = math.exp(-inp.dividend_yield * t)  # dF/dS discounted
        drift = inp.rate - inp.dividend_yield
        rho = phi * inp.strike * t * d * _cdf(phi * d2)
    else:
        scale, drift, rho = d, 0.0, -t * value
    density = _pdf(d1)
    theta_year = (
        inp.rate * value
        - d * fwd * density * vol / (2.0 * sqrt_t)
        - drift * d * fwd * phi * _cdf(phi * d1)
    )
    return ModelGreeks(
        price=value,
        delta=phi * scale * _cdf(phi * d1),
        gamma=scale * density / (inp.underlying * vol * sqrt_t),
        vega=d * fwd * density * sqrt_t,
        theta=theta_year / 365.0,
        rho=rho,
        conventions=Conventions(delta_gamma_wrt=inp.kind),
    )
