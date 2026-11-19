"""Greek conventions, the stored model tag, zero bids and the edge limits of the option models.

The reference values here are derived by hand from the formulas, not taken from the solver.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from alpha_data.options import ChainRow, ContractId, OptionsDataError, Quote
from alpha_data.options.implied import IvSolved, IvUnsolved, model_tag, solve_implied_vol, solve_row
from alpha_data.options.pricing import Conventions, OptionInputs, greeks, price

T0 = datetime(2023, 3, 1, 21, 0, tzinfo=UTC)


def spot(right: str = "C", q: float = 0.0, t: float = 0.5) -> OptionInputs:
    return OptionInputs(
        underlying=100.0, kind="spot", strike=100.0, years=t, rate=0.05, dividend_yield=q,
        right=right,
    )  # fmt: skip


def fwd(right: str = "C") -> OptionInputs:
    return OptionInputs(
        underlying=100.0, kind="forward", strike=100.0, years=0.5, rate=0.05,
        dividend_yield=None, right=right,
    )  # fmt: skip


def test_every_result_carries_its_conventions() -> None:
    g = greeks(spot(), 0.2)
    assert g.conventions == Conventions(delta_gamma_wrt="spot")
    assert (g.conventions.vega, g.conventions.theta, g.conventions.rho) == (
        "per_1.00_vol", "per_calendar_day", "per_1.00_rate",
    )  # fmt: skip
    assert g.conventions.day_count == "act365f"
    assert greeks(fwd(), 0.2).conventions.delta_gamma_wrt == "forward"
    out = solve_implied_vol(spot(), price(spot(), 0.2), style="E")
    assert isinstance(out, IvSolved) and out.conventions == g.conventions


def test_theta_is_per_calendar_day_and_negative_for_a_long_at_the_money_call() -> None:
    """Hand formula, q = 0: theta_year = -S n(d1) vol / (2 sqrt T) - r K exp(-rT) N(d2)."""
    s, k, t, r, v = 100.0, 100.0, 0.5, 0.05, 0.2
    d1 = (math.log(s / k) + (r + v * v / 2) * t) / (v * math.sqrt(t))
    d2 = d1 - v * math.sqrt(t)
    n1 = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    big_n2 = 0.5 * math.erfc(-d2 / math.sqrt(2))
    theta_year = -s * n1 * v / (2 * math.sqrt(t)) - r * k * math.exp(-r * t) * big_n2
    g = greeks(spot(), v)
    assert g.theta < 0
    assert g.theta == pytest.approx(theta_year / 365.0, rel=1e-13)
    assert g.vega / 100 == pytest.approx(s * n1 * math.sqrt(t) / 100, rel=1e-13)  # one vol point


def test_black76_rho_and_theta_hold_the_forward_fixed() -> None:
    """Black-76: rho = -T V; theta_year = r V - D F n(d1) vol / (2 sqrt T)."""
    g = greeks(fwd(), 0.2)
    d1 = 0.5 * 0.2 * math.sqrt(0.5)
    n1 = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    d = math.exp(-0.05 * 0.5)
    assert g.rho == pytest.approx(-0.5 * g.price, rel=1e-14)
    theta_year = 0.05 * g.price - d * 100.0 * n1 * 0.2 / (2 * math.sqrt(0.5))
    assert g.theta == pytest.approx(theta_year / 365.0, rel=1e-13)


def test_a_volatility_that_underflows_is_a_named_error_not_a_division_by_zero() -> None:
    with pytest.raises(OptionsDataError) as info:
        price(spot(t=1e-300), 1e-300)
    assert info.value.field == "vol"
    tiny = 0.2 * math.sqrt(1e-12) * 100 / math.sqrt(2 * math.pi)  # ATM: S vol sqrt(T) n(0)
    assert price(spot(t=1e-12), 0.2) == pytest.approx(tiny, rel=1e-3)


def test_the_model_tag_is_parseable_and_round_trips_the_inputs() -> None:
    tag = model_tag(spot(q=0.015))
    head, *pairs = tag.split(";")
    fields = dict(p.split("=", 1) for p in pairs)
    assert head == "black-scholes-merton-v1"
    assert float(fields["r"]) == 0.05 and float(fields["q"]) == 0.015
    assert fields == {
        "r": "0.05", "q": "0.015", "day_count": "act365f", "theta": "per_calendar_day",
        "vega": "per_1.00_vol",
    }  # fmt: skip
    assert model_tag(fwd()).split(";")[2] == "q=forward"


def test_solve_row_never_averages_a_zero_bid() -> None:
    contract = ContractId(
        underlying_id="AAA", root="AAA", expiry=date(2023, 6, 16), strike=Decimal(150),
        right="C", style="E", multiplier=100, listed_on=date(2023, 1, 1), provider_symbol="X",
    )  # fmt: skip
    row = ChainRow(contract=contract, quote=Quote(bid=0.0, ask=0.05, quote_ts=T0))
    out = solve_row(
        row, snapshot_ts=T0, underlying_price=100.0, rate=0.03, dividend_yield=0.0,
        expiry_time_utc=time(21, 0),
    )  # fmt: skip
    assert isinstance(out.outcome, IvUnsolved) and out.outcome.reason == "no_mid"
    assert out.row.computed is None and replace(out.row) == row
