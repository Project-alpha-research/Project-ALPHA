"""American tree accuracy: error scale, the dividend convention, ex-date timing, tree greeks.

Every tolerance has one line saying why. Reference values come from the closed form, from a finer
tree, or from a recorded outside library value (QuantLib 1.44, stated where used).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest

from alpha_data.options import OptionsDataError
from alpha_data.options.implied import solve_row
from alpha_data.options.pricing import OptionInputs, greeks
from alpha_data.options.schema import ChainRow, ContractId, Quote
from alpha_data.options.tree import AmericanInputs, Dividend, TreeRefused, american_price
from alpha_data.options.tree_greeks import american_greeks

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def am(
    right: str,
    *,
    s: float = 100.0,
    k: float = 100.0,
    days: float = 365.0,
    r: float = 0.05,
    q: float = 0.0,
    dividends: tuple[tuple[float, float], ...] = (),
) -> AmericanInputs:
    return AmericanInputs(
        spot=s, strike=k, valuation_ts=T0, expiry_ts=T0 + timedelta(days=days), rate=r,
        dividend_yield=q,
        dividends=tuple(Dividend(T0 + timedelta(days=d), a) for d, a in dividends),
        right=right,
    )  # fmt: skip


def value(inp: AmericanInputs, vol: float, steps: int) -> float:
    out = american_price(inp, vol, steps)
    assert not isinstance(out, TreeRefused), out
    return out


def closed(inp: AmericanInputs, vol: float) -> tuple[float, float, float]:
    g = greeks(
        OptionInputs(
            underlying=inp.spot, kind="spot", strike=inp.strike, years=inp.years, rate=inp.rate,
            dividend_yield=inp.dividend_yield, right=inp.right,
        ),
        vol,
    )  # fmt: skip
    return g.price, g.delta, g.gamma


@pytest.mark.parametrize(
    ("k", "days", "vol"),
    [(80.0, 365.0, 0.2), (100.0, 365.0, 0.2), (120.0, 365.0, 0.2), (103.0, 730.0, 0.6),
     (103.0, 36.5, 0.8), (103.0, 18.25, 0.1)],
)  # fmt: skip
def test_tree_error_scales_with_spot_vol_and_root_time_over_steps(
    k: float, days: float, vol: float
) -> None:
    """|tree - closed form| <= 0.1 S vol sqrt(T) / steps for a no-dividend call (never exercised).

    A flat 0.3 / steps fits only S = 100, vol 0.2, one year: at vol 0.6 over two years error * steps
    is about 3. Scaled by S vol sqrt(T) the measured constant is at most 0.046 over this grid at
    100, 500 and 2000 steps, so 0.1 leaves about a factor of two.
    """
    inp = am("C", k=k, days=days)
    exact = closed(inp, vol)[0]
    scale = inp.spot * vol * math.sqrt(inp.years)
    for steps in (100, 500):
        assert abs(value(inp, vol, steps) - exact) <= 0.1 * scale / steps, steps


@pytest.mark.parametrize(
    ("inp", "quantlib"),
    [
        (am("C", k=80.0, days=500.0, r=0.02, q=0.01, dividends=((250.0, 4.0),)), 21.21485),
        (am("C", days=365.0, r=0.05, q=0.03, dividends=((180.0, 3.0),)), 9.15995),
    ],
)
def test_cash_dividends_with_a_yield_are_discounted_at_rate_less_yield(
    inp: AmericanInputs, quantlib: float
) -> None:
    """With a yield q and cash dividends, the escrowed amount is sum D exp(-(r - q) t).

    That gives the usual equity forward S exp((r - q) T) - sum D exp((r - q)(T - t)). Reference:
    QuantLib 1.44 FdBlackScholesVanillaEngine, Escrowed cash-dividend model, 2000 x 2000 grid
    (vol 0.2 and 0.25). Discounting at r alone was 0.024 off in both cases. Tolerance 1e-3: the
    2000-step tree and the finite-difference grid each carry a few 1e-4.
    """
    vol = 0.2 if inp.strike == 80.0 else 0.25
    assert value(inp, vol, 2000) == pytest.approx(quantlib, abs=1e-3)


def test_ex_date_timing_error_is_within_the_stated_bound_and_falls_with_steps() -> None:
    """The ex-date sits between nodes: the last exercise before it is up to one step early.

    Worst case found: a call with a large dividend 11 days before expiry, where exercise just before
    the ex-date matters most. Against an 8000-step tree the 500-step error is 7.4e-3 and the
    100-step error is larger; the stated bound is 0.02 at 500 steps for this case (docs).
    """
    inp = am("C", s=100.0, k=100.0, days=365.0, r=0.05, dividends=((354.05, 2.0),))
    fine = value(inp, 0.25, 8000)
    err_500 = abs(value(inp, 0.25, 500) - fine)
    err_100 = abs(value(inp, 0.25, 100) - fine)
    assert err_500 < 0.02
    assert err_100 > err_500


@pytest.mark.parametrize(
    ("k", "days", "vol"), [(100.0, 365.0, 0.2), (100.0, 18.25, 0.2), (105.0, 36.5, 0.3)]
)
def test_tree_delta_and_gamma_match_the_closed_form_for_a_call_without_dividends(
    k: float, days: float, vol: float
) -> None:
    """Delta and gamma read from the tree's first levels: errors measured under 1e-4 at 500 steps.

    A 3% spot bump had gamma errors up to 3.1e-3 on the 18-day case (gamma 0.089). Tolerance
    5e-4 for both: about five times the measured tree-level error.
    """
    inp = am("C", k=k, days=days)
    g = american_greeks(inp, vol, 500)
    assert not isinstance(g, TreeRefused)
    _, delta, gamma = closed(inp, vol)
    assert g.delta == pytest.approx(delta, abs=5e-4)
    assert g.gamma == pytest.approx(gamma, abs=5e-4)


def test_put_gamma_near_the_exercise_boundary_agrees_with_a_finer_tree() -> None:
    """Deep in-the-money put near the boundary (S 82, K 100): 500 steps against 5000 steps.

    The 3% bump was 5.2e-3 off here (gamma 0.037), because the bump crosses the boundary. Tree-level
    gamma measured 4.5e-5 off a 20000-step tree. Tolerance 5e-4.
    """
    inp = am("P", s=82.0)
    coarse, fine = american_greeks(inp, 0.2, 500), american_greeks(inp, 0.2, 5000)
    assert not isinstance(coarse, TreeRefused) and not isinstance(fine, TreeRefused)
    assert coarse.gamma == pytest.approx(fine.gamma, abs=5e-4)
    assert coarse.delta == pytest.approx(fine.delta, abs=5e-4)


def _row(right: str, mid: float) -> ChainRow:
    contract = ContractId(
        underlying_id="AAA", root="AAA", expiry=(T0 + timedelta(days=365)).date(),
        strike=Decimal("100"), right=right, style="A", multiplier=100, listed_on=None,
        provider_symbol="AAA-TEST",
    )  # fmt: skip
    return ChainRow(contract=contract, quote=Quote(bid=mid - 0.01, ask=mid + 0.01, quote_ts=T0))


def test_a_refused_greek_tree_keeps_the_iv_and_labels_the_row() -> None:
    """r = 0.1 on a 4-step tree: vol 0.0515 is valid (floor 0.0505), but the +50bp rate bump
    (floor 0.0525) breaks the tree.

    The solve stands (it is not "did not converge"); the computed block holds the IV only and the
    row says "greeks_not_available" instead of silently dropping the block.
    """
    inp = am("C", r=0.10)
    inp = AmericanInputs(
        spot=inp.spot, strike=inp.strike, valuation_ts=T0,
        expiry_ts=datetime.combine((T0 + timedelta(days=365)).date(), time(0), UTC),
        rate=0.10, dividend_yield=0.0, dividends=(), right="C",
    )  # fmt: skip
    assert isinstance(american_greeks(inp, 0.0515, 4), TreeRefused)
    mid = value(inp, 0.0515, 4)
    out = solve_row(
        _row("C", mid), snapshot_ts=T0, underlying_price=100.0, rate=0.10, dividend_yield=0.0,
        expiry_time_utc=time(0), dividends=(), steps=4,
    )  # fmt: skip
    assert out.labels == ("greeks_not_available",)
    assert out.row.computed is not None
    assert out.row.computed.iv == pytest.approx(0.0515, abs=1e-6)
    assert out.row.computed.delta is None and out.row.computed.gamma is None


def test_missing_dividends_on_an_american_row_say_what_to_pass() -> None:
    with pytest.raises(OptionsDataError, match=r"dividends=\(\)"):
        solve_row(
            _row("P", 7.0), snapshot_ts=T0, underlying_price=100.0, rate=0.05,
            dividend_yield=0.0, expiry_time_utc=time(0), dividends=None,
        )  # fmt: skip
