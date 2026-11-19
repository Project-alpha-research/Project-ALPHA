"""American-style tree pricing and greeks: known answers, convergence, early exercise, smoothness.

Every tolerance has one line saying why. The tree under test is `alpha_data.options.tree`; the
reference values come from the closed form (no early exercise) or from a separate fine tree written
inside this file, so no test rests on a remembered number alone.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from alpha_data.options import OptionsDataError
from alpha_data.options.pricing import OptionInputs, greeks, price
from alpha_data.options.tree import (
    DEFAULT_STEPS,
    AmericanInputs,
    Dividend,
    TreeRefused,
    american_price,
    crr_tree_value,
    min_tree_vol,
)
from alpha_data.options.tree_greeks import BUMPS, american_greeks

T0 = datetime(2023, 3, 1, 21, 0, tzinfo=UTC)


def am(
    right: str,
    *,
    s: float = 100.0,
    k: float = 100.0,
    years: float = 1.0,
    r: float = 0.05,
    q: float = 0.0,
    dividends: tuple[Dividend, ...] = (),
) -> AmericanInputs:
    expiry = T0 + timedelta(seconds=round(years * 365 * 86400))
    return AmericanInputs(
        spot=s, strike=k, valuation_ts=T0, expiry_ts=expiry, rate=r, dividend_yield=q,
        dividends=dividends, right=right,
    )  # fmt: skip


def european(inp: AmericanInputs, vol: float) -> float:
    return price(
        OptionInputs(
            underlying=inp.spot, kind="spot", strike=inp.strike, years=inp.years, rate=inp.rate,
            dividend_yield=inp.dividend_yield, right=inp.right,
        ),
        vol,
    )  # fmt: skip


def value(inp: AmericanInputs, vol: float, steps: int = DEFAULT_STEPS) -> float:
    out = american_price(inp, vol, steps)
    assert not isinstance(out, TreeRefused), out
    return out


def reference_put(s: float, k: float, years: float, r: float, vol: float, steps: int) -> float:
    """A separate, plain CRR American put (no yield, no dividends) used as an independent check."""
    dt = years / steps
    u = math.exp(vol * math.sqrt(dt))
    d = 1.0 / u
    p = (math.exp(r * dt) - d) / (u - d)
    disc = math.exp(-r * dt)
    j = np.arange(steps + 1)
    v = np.maximum(k - s * u ** (2 * j - steps), 0.0)
    for i in range(steps - 1, -1, -1):
        j = np.arange(i + 1)
        v = disc * (p * v[1:] + (1.0 - p) * v[:-1])
        v = np.maximum(v, k - s * u ** (2 * j - i))
    return float(v[0])


def test_no_dividend_call_matches_black_scholes_and_the_error_falls_with_steps() -> None:
    """q = 0, no dividends: early exercise is never optimal, so the tree is the European price.

    CRR error is order 1/steps (their paper proves convergence to Black-Scholes; the rate is
    first order). The N and N+1 average damps the odd-even swing. Bound: 0.3 / steps in price
    units for S = K = 100, vol 0.2, one year. Measured errors: 1.3e-3 (100 steps), 2.5e-4 (500),
    6.2e-5 (2000), each about 2.5 times inside the bound.
    """
    inp = am("C")
    exact = european(inp, 0.2)
    errors = []
    for steps in (100, 500, 2000):
        err = abs(value(inp, 0.2, steps) - exact)
        errors.append(err)
        assert err < 0.3 / steps, (steps, err)
    assert errors[0] > errors[1] > errors[2], errors


def test_american_put_is_at_least_european_and_the_premium_grows_with_the_rate() -> None:
    """The early-exercise premium is positive here and strictly increasing in the rate.

    The cases are in the money enough that the premium (0.2 to 2) is far above the tree error
    (about 0.0003), so a strict inequality is safe.
    """
    premiums = []
    for rate in (0.01, 0.03, 0.05, 0.08, 0.12):
        inp = am("P", k=110.0, r=rate)
        premiums.append(value(inp, 0.25) - european(inp, 0.25))
        assert value(inp, 0.25) >= max(inp.strike - inp.spot, 0.0)
    assert all(p > 0.02 for p in premiums), premiums
    assert premiums == sorted(premiums) and len(set(premiums)) == len(premiums), premiums


def test_a_nearly_worthless_put_has_a_premium_within_the_tree_error() -> None:
    """Deep out of the money: the true premium is tiny, so only the tree error bound applies."""
    inp = am("P", k=60.0)
    assert value(inp, 0.2) - european(inp, 0.2) > -1.0 / DEFAULT_STEPS


def test_hull_american_put_five_step_tree_and_an_independent_recompute() -> None:
    """S 50, K 50, r 10%, vol 40%, 5 months: Hull's five-step tree gives about 4.49.

    The target is also recomputed here by a separate five-step tree, so the test does not rest on
    the book. Five steps is a coarse tree: 4.49 is a rounded book figure (tolerance 0.006 covers
    the rounding); the separate recompute must match the module to 1e-9.
    """
    inp = am("P", s=50.0, k=50.0, years=5.0 / 12.0, r=0.10)
    ours = crr_tree_value(inp, 0.4, 5)
    assert not isinstance(ours, TreeRefused)
    assert ours == pytest.approx(reference_put(50.0, 50.0, inp.years, 0.10, 0.4, 5), abs=1e-9)
    assert ours == pytest.approx(4.49, abs=0.006)


@pytest.mark.slow_oracle
def test_hull_put_converges_to_a_20000_step_independent_value() -> None:
    """The same put at 500 steps against a 20,000-step separate tree.

    Tolerance 2e-3: the averaged 500-step tree error is order 1/steps times a small constant
    (measured well inside); the 20,000-step reference is about 1e-4 from the limit.
    """
    inp = am("P", s=50.0, k=50.0, years=5.0 / 12.0, r=0.10)
    fine = reference_put(50.0, 50.0, inp.years, 0.10, 0.4, 20_000)
    assert 4.2 < fine < 4.4
    assert value(inp, 0.4, 500) == pytest.approx(fine, abs=2e-3)


def test_a_dividend_makes_early_exercise_of_a_call_optimal_just_before_ex_date() -> None:
    """Deep in the money call, big cash dividend at half a year: exercise just before the ex-date.

    Hull's rule: exercise just before an ex-date is worth considering when the dividend exceeds
    K (1 - exp(-r tau)) (here about 1.97). A 5.0 dividend passes, a 0.5 one does not. The excess
    over the escrowed European price is above 1.0 in the first case (measured 2.11) and inside
    the tree error in the second (measured 2.5e-4; tolerance 0.5 / steps).
    """
    ex = T0 + timedelta(days=182)
    for amount in (5.0, 0.5):
        inp = am("C", s=100.0, k=80.0, dividends=(Dividend(ex, amount),))
        pv = amount * math.exp(-inp.rate * 182 / 365)
        euro = european(replace(inp, spot=inp.spot - pv, dividends=()), 0.2)
        excess = value(inp, 0.2) - euro
        if amount == 5.0:
            assert excess > 1.0, excess
            assert value(inp, 0.2) >= inp.spot - inp.strike
        else:
            assert abs(excess) < 0.5 / DEFAULT_STEPS, excess


def test_dividends_after_expiry_or_not_after_valuation_are_ignored() -> None:
    plain = am("P", k=105.0)
    noisy = am(
        "P", k=105.0,
        dividends=(
            Dividend(T0 - timedelta(days=3), 2.0),
            Dividend(T0, 2.0),
            Dividend(plain.expiry_ts, 2.0),
            Dividend(plain.expiry_ts + timedelta(days=9), 2.0),
        ),
    )  # fmt: skip
    assert value(noisy, 0.3) == value(plain, 0.3)


def test_a_dividend_present_value_above_spot_is_a_typed_error() -> None:
    inp = am("C", s=10.0, k=10.0, dividends=(Dividend(T0 + timedelta(days=30), 11.0),))
    with pytest.raises(OptionsDataError) as info:
        american_price(inp, 0.3, 50)
    assert info.value.field == "dividends"


def test_put_call_inequalities_for_american_options_hold() -> None:
    """S exp(-qT) - K <= C - P <= S - K exp(-rT), with no discrete dividend (Hull, American).

    Tolerance 2e-3: two tree errors (each under 1/steps) at 500 steps.
    """
    for k in (80.0, 95.0, 100.0, 110.0, 130.0):
        inp_c, inp_p = am("C", k=k, q=0.02), am("P", k=k, q=0.02)
        diff = value(inp_c, 0.3) - value(inp_p, 0.3)
        assert inp_c.spot * math.exp(-0.02 * inp_c.years) - k <= diff + 2e-3
        assert diff <= inp_c.spot - k * math.exp(-0.05 * inp_c.years) + 2e-3


def test_tiny_volatility_gives_the_larger_of_exercise_and_discounted_forward_intrinsic() -> None:
    """Vol just above the smallest step-valid value: price tends to the best discounted payoff.

    The limit is the maximum over exercise times of the discounted payoff along the forward path;
    it is recomputed here on a fine time grid. Tolerance 2e-3 for the step-grid of the tree.
    """
    for right, k in (("P", 110.0), ("P", 90.0), ("C", 90.0), ("C", 110.0)):
        inp = am(right, k=k, years=0.5, r=0.04, q=0.01)
        vol = 4.0 * min_tree_vol(inp, DEFAULT_STEPS)
        phi = 1.0 if right == "C" else -1.0
        grid = np.linspace(0.0, inp.years, 20001)
        payoff = phi * (
            inp.spot * np.exp(-inp.dividend_yield * grid) - k * np.exp(-inp.rate * grid)
        )
        limit = max(float(payoff.max()), 0.0)
        assert value(inp, vol) == pytest.approx(limit, abs=2e-3), (right, k)


def test_a_step_that_breaks_no_arbitrage_is_a_typed_outcome() -> None:
    """d < exp((r - q) dt) < u fails when vol < |r - q| sqrt(dt): typed, never a bad number."""
    inp = am("P", r=0.05)
    out = american_price(inp, 0.5 * min_tree_vol(inp, 100), 100)
    assert isinstance(out, TreeRefused)
    assert out.steps == 100 and not out.down < out.growth < out.up
    assert "no-arbitrage" in out.message
    assert not isinstance(american_price(inp, 1.5 * min_tree_vol(inp, 100), 100), TreeRefused)


def broken(field: str) -> AmericanInputs:
    base = am("C")
    if field == "spot":
        return replace(base, spot=math.nan)
    if field == "strike":
        return replace(base, strike=math.nan)
    if field == "rate":
        return replace(base, rate=math.nan)
    return replace(base, dividend_yield=math.nan)


@pytest.mark.parametrize("field", ["spot", "strike", "rate", "dividend_yield"])
def test_inputs_must_be_finite(field: str) -> None:
    with pytest.raises(OptionsDataError) as info:
        broken(field)
    assert info.value.field == field


def test_naive_instants_and_bad_steps_are_named_errors() -> None:
    with pytest.raises(OptionsDataError) as naive:
        replace(am("C"), valuation_ts=T0.replace(tzinfo=None))
    assert naive.value.field == "valuation_ts"
    with pytest.raises(OptionsDataError) as steps:
        american_price(am("C"), 0.2, 1)
    assert steps.value.field == "steps"


def test_greeks_match_black_scholes_where_early_exercise_never_happens() -> None:
    """American call, q = 0: every greek equals the closed form. FD bumps are in `BUMPS`.

    Tolerances at 500 steps are about 2.5 times the measured errors: price 1e-3 (measured 2.5e-4),
    delta 2e-3 (8e-4), gamma 1e-3 (3.5e-4, true 0.019), vega 0.02 (2e-3 of 37.5), theta 1e-5 per
    day (1e-6), rho 0.03 (0.011 of 53).
    """
    inp = am("C")
    ours = american_greeks(inp, 0.2, 500)
    assert not isinstance(ours, TreeRefused)
    euro = greeks(
        OptionInputs(
            underlying=100.0, kind="spot", strike=100.0, years=inp.years, rate=0.05,
            dividend_yield=0.0, right="C",
        ),
        0.2,
    )  # fmt: skip
    assert ours.method == "crr_tree" and ours.steps == 500
    assert ours.conventions == euro.conventions
    assert ours.conventions.vega == "per_1.00_vol" and ours.conventions.theta == "per_calendar_day"
    assert ours.price == pytest.approx(euro.price, abs=1e-3)
    assert ours.delta == pytest.approx(euro.delta, abs=2e-3)
    assert ours.gamma == pytest.approx(euro.gamma, abs=1e-3)
    assert ours.vega == pytest.approx(euro.vega, abs=0.02)
    assert ours.theta == pytest.approx(euro.theta, abs=1e-5)
    assert ours.rho == pytest.approx(euro.rho, abs=0.03)
    assert set(BUMPS) >= {"spot_relative", "vol", "rate", "time_days"}


def test_delta_and_gamma_are_smooth_across_a_spot_grid_with_no_sign_flips() -> None:
    """An American put across S = 96 to 104: delta rises steadily, gamma stays positive.

    The N / N+1 average removes the tree parity wobble. Measured: smallest delta step +0.008,
    gamma between 0.021 and 0.026. So the test demands strictly rising delta and positive gamma.
    """
    deltas, gammas = [], []
    for k in range(21):
        inp = am("P", s=96.0 + 0.4 * k, k=100.0, years=0.5, r=0.04)
        g = american_greeks(inp, 0.25, DEFAULT_STEPS)
        assert not isinstance(g, TreeRefused)
        deltas.append(g.delta)
        gammas.append(g.gamma)
    assert all(-1.0 <= d <= 0.0 for d in deltas)
    assert all(b - a > 0.0 for a, b in zip(deltas, deltas[1:], strict=False)), deltas
    assert all(x > 0.0 for x in gammas), gammas
    assert max(gammas) - min(gammas) < 0.01
