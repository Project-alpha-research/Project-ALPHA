"""Implied volatility solver: round trip, typed outcomes, low-vega label, mid price, day count."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import product

import pytest

from alpha_data.options import OptionsDataError, Quote
from alpha_data.options.implied import (
    IV_HIGH,
    IV_LOW,
    IvSolved,
    IvUnsolved,
    mid_price,
    solve_implied_vol,
    years_between,
)
from alpha_data.options.pricing import OptionInputs, price, price_bounds

T0 = datetime(2023, 3, 1, 21, 0, tzinfo=UTC)


def inputs(m: float, t: float, right: str, kind: str = "spot", s: float = 100.0) -> OptionInputs:
    return OptionInputs(
        underlying=s,
        kind=kind,
        strike=s * m,
        years=t,
        rate=0.03,
        dividend_yield=0.015 if kind == "spot" else None,
        right=right,
    )


def test_round_trip_recovers_the_volatility_to_1e_8_across_the_grid() -> None:
    """Exact model prices in, vol out. Tolerance 1e-8 whenever confidence is normal.

    Every case is either recovered to 1e-8, labelled low_vega, or typed unsolved (the price rounds
    onto a bound). Silent wrong answers are the failure. The grid includes deep corners (60% and
    160% moneyness at one week), so only 65% must be normal; measured: 600 of 840, worst error
    1.6e-14.
    """
    normal = total = 0
    for m, t, v, right, kind in product(
        (0.6, 0.8, 0.95, 1.0, 1.05, 1.25, 1.6),
        (7 / 365, 0.1, 0.5, 1.0, 3.0),
        (0.05, 0.1, 0.2, 0.5, 1.0, 2.0),
        ("C", "P"),
        ("spot", "forward"),
    ):
        inp = inputs(m, t, right, kind)
        out = solve_implied_vol(inp, price(inp, v), style="E")
        total += 1
        if isinstance(out, IvSolved) and out.confidence == "normal":
            normal += 1
            assert out.iv == pytest.approx(v, abs=1e-8), (m, t, v, right, kind)
        elif isinstance(out, IvSolved):
            assert out.confidence == "low_vega" and out.iv_uncertainty > 0
        else:
            assert out.reason in {
                "price_outside_no_arbitrage_bounds",
                "implied_vol_outside_search_interval",
            }
    assert normal / total >= 0.65


def test_the_result_records_the_inputs_model_and_vega() -> None:
    inp = inputs(1.0, 0.5, "C")
    out = solve_implied_vol(inp, price(inp, 0.3), style="E")
    assert isinstance(out, IvSolved)
    assert out.inputs == inp and out.model == "black-scholes-merton-v1"
    assert out.vega > 0 and out.iterations > 0
    assert out.price == price(inp, 0.3)


@pytest.mark.parametrize("right", ["C", "P"])
def test_price_below_intrinsic_or_above_the_upper_bound_is_typed_not_a_number(right: str) -> None:
    inp = inputs(0.8 if right == "C" else 1.2, 0.5, right)
    lower, upper = price_bounds(inp)
    for bad in (lower * 0.999 - 1e-6, lower, upper, upper * 1.01):
        out = solve_implied_vol(inp, bad, style="E")
        assert isinstance(out, IvUnsolved)
        assert out.reason == "price_outside_no_arbitrage_bounds"
        assert out.message == "no implied volatility: price outside no-arbitrage bounds"


def test_zero_time_to_expiry_is_typed() -> None:
    out = solve_implied_vol(inputs(1.0, 0.0, "C"), 1.0, style="E")
    assert isinstance(out, IvUnsolved) and out.reason == "zero_time_to_expiry"


def test_american_style_is_a_typed_not_supported_result() -> None:
    inp = inputs(1.0, 0.5, "P")
    out = solve_implied_vol(inp, price(inp, 0.3), style="A")
    assert isinstance(out, IvUnsolved)
    assert out.reason == "american_style_not_supported"
    assert out.message == "no implied volatility: American style is not supported yet"


def test_a_vol_outside_the_search_interval_is_typed() -> None:
    inp = inputs(1.0, 1.0, "C")
    lo = solve_implied_vol(inp, price(inp, IV_LOW / 10) + 1e-300, style="E")
    hi = solve_implied_vol(inp, price(inp, IV_HIGH * 3), style="E")
    for out in (lo, hi):
        assert isinstance(out, IvUnsolved)
        assert out.reason in {
            "implied_vol_outside_search_interval",
            "price_outside_no_arbitrage_bounds",
        }


def test_deep_out_of_the_money_with_a_coarse_price_is_labelled_low_confidence() -> None:
    """A price quantised to a cent on a worthless option cannot pin the volatility."""
    inp = inputs(1.6, 7 / 365, "C")
    out = solve_implied_vol(inp, 0.01, style="E", price_resolution=0.005)
    assert isinstance(out, IvSolved)
    assert out.confidence == "low_vega"
    assert out.iv_uncertainty == pytest.approx(0.005 / out.vega, rel=1e-12)
    assert out.iv_uncertainty > 0.005


def test_at_the_money_with_a_cent_price_is_normal_confidence() -> None:
    inp = inputs(1.0, 0.5, "C")
    out = solve_implied_vol(inp, round(price(inp, 0.25), 2), style="E", price_resolution=0.005)
    assert isinstance(out, IvSolved) and out.confidence == "normal"
    assert out.iv == pytest.approx(0.25, abs=2e-3)


@pytest.mark.parametrize("field", ["price", "price_resolution"])
def test_non_finite_numbers_name_the_field(field: str) -> None:
    inp = inputs(1.0, 0.5, "C")
    kwargs: dict[str, float] = {"price": 5.0, "price_resolution": 0.005}
    kwargs[field] = math.nan
    with pytest.raises(OptionsDataError) as info:
        solve_implied_vol(
            inp, kwargs["price"], style="E", price_resolution=kwargs["price_resolution"]
        )
    assert info.value.field == field


def test_style_must_be_known() -> None:
    with pytest.raises(OptionsDataError) as info:
        solve_implied_vol(inputs(1.0, 0.5, "C"), 5.0, style="Z")
    assert info.value.field == "style"


def test_years_use_actual_over_365_fixed_on_aware_utc_timestamps() -> None:
    assert years_between(T0, T0 + timedelta(days=365)) == 1.0
    assert years_between(T0, T0 + timedelta(hours=12)) == pytest.approx(0.5 / 365, rel=1e-15)
    assert years_between(T0, T0) == 0.0
    with pytest.raises(OptionsDataError) as early:
        years_between(T0, T0 - timedelta(seconds=1))
    assert early.value.field == "expiry_ts"
    with pytest.raises(OptionsDataError) as naive:
        years_between(T0.replace(tzinfo=None), T0)
    assert naive.value.field == "snapshot_ts"
    assert isinstance(time(21, 0), time) and isinstance(date(2023, 3, 1), date)


def test_mid_price_is_the_average_and_respects_the_labels() -> None:
    q = Quote(bid=1.0, ask=1.2, quote_ts=T0)
    assert mid_price(q).value == pytest.approx(1.1, abs=1e-15)
    assert mid_price(q).labels == ()
    crossed = mid_price(replace(q, bid=1.3))
    assert crossed.value is None and crossed.labels == ("crossed",)
    flat = mid_price(replace(q, bid=1.2))
    assert flat.value is None and flat.labels == ("zero_width",)
    zero_bid = mid_price(replace(q, bid=0.0))
    assert zero_bid.value == pytest.approx(0.6, abs=1e-15) and zero_bid.labels == ("zero_bid",)
