"""Option pricing: published values, parity, finite-difference greeks, limits, monotonicity."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from itertools import product
from statistics import NormalDist
from typing import Any

import pytest

from alpha_data.options import OptionsDataError
from alpha_data.options.pricing import (
    BLACK76_MODEL,
    BSM_MODEL,
    OptionInputs,
    greeks,
    price,
    price_bounds,
)

NORM = NormalDist()


def spot_inputs(s: float, k: float, t: float, r: float, q: float, right: str = "C") -> OptionInputs:
    return OptionInputs(
        underlying=s, kind="spot", strike=k, years=t, rate=r, dividend_yield=q, right=right
    )


def fwd_inputs(f: float, k: float, t: float, r: float, right: str = "C") -> OptionInputs:
    return OptionInputs(
        underlying=f, kind="forward", strike=k, years=t, rate=r, dividend_yield=None, right=right
    )


def independent_bsm(
    s: float, k: float, t: float, r: float, q: float, v: float, right: str
) -> float:
    """Second implementation using statistics.NormalDist, not math.erfc."""
    d1 = (math.log(s / k) + (r - q + v * v / 2) * t) / (v * math.sqrt(t))
    d2 = d1 - v * math.sqrt(t)
    if right == "C":
        return s * math.exp(-q * t) * NORM.cdf(d1) - k * math.exp(-r * t) * NORM.cdf(d2)
    return k * math.exp(-r * t) * NORM.cdf(-d2) - s * math.exp(-q * t) * NORM.cdf(-d1)


def test_published_prices_hull_s42_k40() -> None:
    """Hull: S=42, K=40, r=10%, vol=20%, T=0.5, no dividend: call 4.76, put 0.81. Tolerance 5e-3."""
    assert price(spot_inputs(42, 40, 0.5, 0.10, 0.0, "C"), 0.20) == pytest.approx(4.76, abs=5e-3)
    assert price(spot_inputs(42, 40, 0.5, 0.10, 0.0, "P"), 0.20) == pytest.approx(0.81, abs=5e-3)


def test_published_greeks_hull_s49_k50() -> None:
    """Hull: S=49, K=50, r=5%, vol=20%, T=20/52, no dividend. Published to 3 significant digits.

    delta 0.522, gamma 0.066, vega 12.1 (per 1.00 vol), rho 8.91, theta -4.31 (per YEAR, so the
    per-calendar-day value times 365). Tolerances: 5e-4, 5e-4, 5e-2, 5e-3, 5e-3.
    """
    g = greeks(spot_inputs(49, 50, 20 / 52, 0.05, 0.0), 0.20)
    assert g.delta == pytest.approx(0.522, abs=5e-4)
    assert g.gamma == pytest.approx(0.066, abs=5e-4)
    assert g.vega == pytest.approx(12.1, abs=5e-2)
    assert g.rho == pytest.approx(8.91, abs=5e-3)
    assert g.theta * 365 == pytest.approx(-4.31, abs=5e-3)


def test_published_black76_haug_f19_k19() -> None:
    """Haug, Complete Guide to Option Pricing Formulas: F=19, K=19, r=10%, vol=28%, T=0.75: 1.7011.

    Tolerance 5e-5.
    """
    assert price(fwd_inputs(19, 19, 0.75, 0.10), 0.28) == pytest.approx(1.7011, abs=5e-5)


GRID = list(
    product(
        (0.7, 0.9, 1.0, 1.1, 1.4),  # strike / underlying
        (7 / 365, 0.1, 0.5, 2.0),  # years
        (0.05, 0.2, 0.6, 1.5),  # volatility
    )
)


def test_prices_match_an_independent_implementation() -> None:
    """Tolerance 1e-12 absolute plus 1e-12 relative on 120 cases per right."""
    for m, t, v in GRID:
        for right in ("C", "P"):
            got = price(spot_inputs(100, 100 * m, t, 0.03, 0.015, right), v)
            want = independent_bsm(100, 100 * m, t, 0.03, 0.015, v, right)
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


def test_put_call_parity_holds_to_1e_10() -> None:
    for m, t, v in GRID:
        c = price(spot_inputs(100, 100 * m, t, 0.03, 0.015, "C"), v)
        p = price(spot_inputs(100, 100 * m, t, 0.03, 0.015, "P"), v)
        assert c - p == pytest.approx(
            100 * math.exp(-0.015 * t) - 100 * m * math.exp(-0.03 * t), abs=1e-10
        )
        cf = price(fwd_inputs(100, 100 * m, t, 0.03, "C"), v)
        pf = price(fwd_inputs(100, 100 * m, t, 0.03, "P"), v)
        assert cf - pf == pytest.approx(math.exp(-0.03 * t) * (100 - 100 * m), abs=1e-10)


def test_black76_equals_bsm_when_the_forward_is_built_from_the_same_inputs() -> None:
    """F = S exp((r-q)T). Price and every greek agree where they mean the same thing.

    Tolerance 1e-10 relative. Vega, theta and rho differ in definition (what is held fixed) and are
    compared through the chain rule instead: vega is identical; delta_bsm = delta_76 * dF/dS.
    """
    s, r, q = 100.0, 0.03, 0.015
    for m, t, v in GRID:
        f = s * math.exp((r - q) * t)
        for right in ("C", "P"):
            a = greeks(spot_inputs(s, s * m, t, r, q, right), v)
            b = greeks(fwd_inputs(f, s * m, t, r, right), v)
            assert a.price == pytest.approx(b.price, rel=1e-10, abs=1e-12)
            assert a.vega == pytest.approx(b.vega, rel=1e-10, abs=1e-12)
            assert a.delta == pytest.approx(b.delta * f / s, rel=1e-10, abs=1e-12)
            assert a.gamma == pytest.approx(b.gamma * (f / s) ** 2, rel=1e-10, abs=1e-12)


def central(fn: Callable[[float], float], x: float, h: float) -> float:
    return (fn(x + h) - fn(x - h)) / (2 * h)


@pytest.mark.parametrize("right", ["C", "P"])
@pytest.mark.parametrize("m,t,v", [(1.0, 0.5, 0.2), (0.9, 0.25, 0.35), (1.2, 1.0, 0.15)])
def test_bsm_greeks_match_central_finite_differences(
    right: str, m: float, t: float, v: float
) -> None:
    """Relative tolerance 1e-6 (second differences 1e-5)."""
    s, k, r, q = 100.0, 100.0 * m, 0.03, 0.015
    g = greeks(spot_inputs(s, k, t, r, q, right), v)

    def px(x: float) -> float:
        return price(spot_inputs(x, k, t, r, q, right), v)

    delta = central(px, s, 1e-3)
    gamma = (px(s + 1e-2) - 2 * px(s) + px(s - 1e-2)) / 1e-4
    vega = central(lambda x: price(spot_inputs(s, k, t, r, q, right), x), v, 1e-6)
    theta = -central(lambda x: price(spot_inputs(s, k, x, r, q, right), v), t, 1e-6) / 365
    rho = central(lambda x: price(spot_inputs(s, k, t, x, q, right), v), r, 1e-6)
    assert g.delta == pytest.approx(delta, rel=1e-6)
    assert g.gamma == pytest.approx(gamma, rel=1e-5)
    assert g.vega == pytest.approx(vega, rel=1e-6)
    assert g.theta == pytest.approx(theta, rel=1e-6)
    assert g.rho == pytest.approx(rho, rel=1e-6)


@pytest.mark.parametrize("right", ["C", "P"])
@pytest.mark.parametrize("m,t,v", [(1.0, 0.5, 0.2), (0.9, 0.25, 0.35), (1.2, 1.0, 0.15)])
def test_black76_greeks_match_central_finite_differences(
    right: str, m: float, t: float, v: float
) -> None:
    """Forward held fixed for theta and rho. Same tolerances as the BSM test."""
    f, k, r = 100.0, 100.0 * m, 0.03
    g = greeks(fwd_inputs(f, k, t, r, right), v)

    def px(x: float) -> float:
        return price(fwd_inputs(x, k, t, r, right), v)

    assert g.delta == pytest.approx(central(px, f, 1e-3), rel=1e-6)
    assert g.gamma == pytest.approx((px(f + 1e-2) - 2 * px(f) + px(f - 1e-2)) / 1e-4, rel=1e-5)
    assert g.vega == pytest.approx(
        central(lambda x: price(fwd_inputs(f, k, t, r, right), x), v, 1e-6), rel=1e-6
    )
    assert g.theta == pytest.approx(
        -central(lambda x: price(fwd_inputs(f, k, x, r, right), v), t, 1e-6) / 365, rel=1e-6
    )
    assert g.rho == pytest.approx(
        central(lambda x: price(fwd_inputs(f, k, t, x, right), v), r, 1e-6), rel=1e-6
    )


def test_vanishing_volatility_gives_discounted_forward_intrinsic() -> None:
    """Tolerance 1e-9 absolute."""
    s, k, t, r, q = 100.0, 95.0, 0.5, 0.03, 0.01
    fwd = s * math.exp((r - q) * t)
    d = math.exp(-r * t)
    assert price(spot_inputs(s, k, t, r, q, "C"), 1e-8) == pytest.approx(d * (fwd - k), abs=1e-9)
    assert price(spot_inputs(s, k, t, r, q, "P"), 1e-8) == pytest.approx(0.0, abs=1e-9)
    assert price(spot_inputs(s, 110.0, t, r, q, "P"), 1e-8) == pytest.approx(
        d * (110.0 - fwd), abs=1e-9
    )


def test_very_large_volatility_approaches_the_upper_bound() -> None:
    """Call to S exp(-qT), put to K exp(-rT); relative tolerance 1e-9 at vol 100."""
    s, k, t, r, q = 100.0, 95.0, 0.5, 0.03, 0.01
    _, call_upper = price_bounds(spot_inputs(s, k, t, r, q, "C"))
    _, put_upper = price_bounds(spot_inputs(s, k, t, r, q, "P"))
    assert call_upper == pytest.approx(s * math.exp(-q * t), rel=1e-15)
    assert put_upper == pytest.approx(k * math.exp(-r * t), rel=1e-15)
    assert price(spot_inputs(s, k, t, r, q, "C"), 100.0) == pytest.approx(call_upper, rel=1e-9)
    assert price(spot_inputs(s, k, t, r, q, "P"), 100.0) == pytest.approx(put_upper, rel=1e-9)


def test_price_is_strictly_increasing_in_volatility_and_inside_the_bounds() -> None:
    for m, t, right in product((0.8, 1.0, 1.25), (0.05, 1.0), ("C", "P")):
        inp = spot_inputs(100, 100 * m, t, 0.03, 0.01, right)
        lower, upper = price_bounds(inp)
        vols = [0.05 * 1.3**i for i in range(14)]
        prices = [price(inp, v) for v in vols]
        assert all(b >= a for a, b in zip(prices, prices[1:], strict=False))
        assert all(lower - 1e-12 <= p <= upper + 1e-12 for p in prices)
    atm = spot_inputs(100, 100, 0.5, 0.03, 0.01, "C")
    atm_prices = [price(atm, 0.05 * 1.3**i) for i in range(14)]
    assert all(b > a for a, b in zip(atm_prices, atm_prices[1:], strict=False))


def test_models_are_named() -> None:
    assert spot_inputs(100, 100, 1, 0.01, 0.0).model == BSM_MODEL == "black-scholes-merton-v1"
    assert fwd_inputs(100, 100, 1, 0.01).model == BLACK76_MODEL == "black-76-v1"


@pytest.mark.parametrize(
    "field,kwargs",
    [
        ("underlying", {"underlying": math.nan}),
        ("underlying", {"underlying": 0.0}),
        ("strike", {"strike": -1.0}),
        ("years", {"years": math.inf}),
        ("years", {"years": -0.1}),
        ("rate", {"rate": math.nan}),
        ("dividend_yield", {"dividend_yield": math.inf}),
        ("dividend_yield", {"dividend_yield": None}),
        ("right", {"right": "X"}),
        ("kind", {"kind": "futures"}),
    ],
)
def test_bad_inputs_raise_an_error_naming_the_field(field: str, kwargs: dict[str, Any]) -> None:
    with pytest.raises(OptionsDataError) as info:
        replace(spot_inputs(100.0, 100.0, 1.0, 0.01, 0.0), **kwargs)
    assert info.value.field == field


def test_a_forward_must_not_carry_a_dividend_yield_and_price_needs_positive_inputs() -> None:
    with pytest.raises(OptionsDataError) as info:
        replace(fwd_inputs(100.0, 100.0, 1.0, 0.01), dividend_yield=0.02)
    assert info.value.field == "dividend_yield"
    with pytest.raises(OptionsDataError) as vol:
        price(spot_inputs(100, 100, 1.0, 0.01, 0.0), 0.0)
    assert vol.value.field == "vol"
    with pytest.raises(OptionsDataError) as years:
        price(spot_inputs(100, 100, 0.0, 0.01, 0.0), 0.2)
    assert years.value.field == "years"
