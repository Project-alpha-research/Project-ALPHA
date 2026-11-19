"""American-style implied volatility, solve_row wiring and the American fixture mode."""

from __future__ import annotations

import time as clock
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest

from alpha_data.options import (
    ChainRow,
    ChainSnapshot,
    OptionsDataError,
    SyntheticAdapter,
    VolSurface,
)
from alpha_data.options.fixture import PricedModel
from alpha_data.options.implied import IvSolved, IvUnsolved, RowSolve, solve_row
from alpha_data.options.implied_american import solve_american_implied_vol
from alpha_data.options.tree import (
    DEFAULT_STEPS,
    AmericanInputs,
    Dividend,
    TreeRefused,
    american_price,
    min_tree_vol,
)

T0 = datetime(2023, 3, 1, 21, 0, tzinfo=UTC)
CLOSE = time(21, 0)


def am(right: str, *, k: float = 100.0, years: float = 0.5, r: float = 0.04, q: float = 0.01,
       dividends: tuple[Dividend, ...] = ()) -> AmericanInputs:  # fmt: skip
    return AmericanInputs(
        spot=100.0, strike=k, valuation_ts=T0,
        expiry_ts=T0 + timedelta(seconds=round(years * 365 * 86400)),
        rate=r, dividend_yield=q, dividends=dividends, right=right,
    )  # fmt: skip


def tree(inp: AmericanInputs, vol: float, steps: int = DEFAULT_STEPS) -> float:
    out = american_price(inp, vol, steps)
    assert not isinstance(out, TreeRefused)
    return out


def test_round_trip_at_the_same_step_count_is_exact_to_1e_6() -> None:
    """Price from the tree, solve on the same tree: only the root finder tolerance remains.

    The finder stops at 1e-9 in volatility; 1e-6 leaves room for the flat part of a tree price.
    """
    for right, k in (("C", 100.0), ("P", 100.0), ("P", 115.0), ("C", 90.0)):
        inp = am(right, k=k, dividends=(Dividend(T0 + timedelta(days=60), 0.8),))
        for vol in (0.12, 0.3, 0.6):
            out = solve_american_implied_vol(inp, tree(inp, vol, 200), steps=200)
            assert isinstance(out, IvSolved) and out.confidence == "normal", (right, k, vol)
            assert out.iv == pytest.approx(vol, abs=1e-6)
            assert out.method == "crr_tree" and out.steps == 200


def test_round_trip_from_a_finer_tree_is_within_the_tree_error() -> None:
    """Price at 2000 steps, solve at 200: the volatility error is price error over vega.

    Measured volatility error at 200 steps: 1.6e-4 (vega 38.7); at 100 steps 3.3e-4. Tolerance
    1e-3 (a tenth of a vol point) is about six times the 200-step error.
    """
    inp = am("P", k=105.0)
    out = solve_american_implied_vol(inp, tree(inp, 0.3, 2000), steps=200)
    assert isinstance(out, IvSolved)
    assert out.iv == pytest.approx(0.3, abs=1e-3)


def test_price_is_strictly_increasing_in_volatility_and_so_is_the_solved_vol_in_price() -> None:
    inp = am("P", k=105.0, dividends=(Dividend(T0 + timedelta(days=90), 1.0),))
    vols = [0.08 + 0.02 * i for i in range(30)]
    prices = [tree(inp, v, 150) for v in vols]
    assert all(b > a for a, b in zip(prices, prices[1:], strict=False))
    solved = []
    for p in (prices[3], prices[10], prices[20]):
        out = solve_american_implied_vol(inp, p, steps=150)
        assert isinstance(out, IvSolved)
        solved.append(out.iv)
    assert solved == sorted(solved)


def test_a_price_at_or_below_exercise_value_or_above_the_cap_is_outside_bounds() -> None:
    put, call = am("P", k=120.0), am("C", k=80.0)
    for inp, exercise, cap in ((put, 20.0, 120.0), (call, 20.0, 100.0)):
        for bad in (exercise, exercise - 1.0, cap, cap + 1.0):
            out = solve_american_implied_vol(inp, bad, steps=100)
            assert isinstance(out, IvUnsolved)
            assert out.reason == "price_outside_no_arbitrage_bounds"
            assert out.message == "no implied volatility: price outside no-arbitrage bounds"


def test_a_price_below_what_the_smallest_valid_vol_gives_is_typed_not_clamped() -> None:
    """With q well above r the put's tiny-volatility limit (about 11.6) is above exercise value (5).

    A price of 6 is inside the bounds but no volatility the tree can represent produces it.
    """
    inp = am("P", k=105.0, years=1.0, r=0.01, q=0.08)
    out = solve_american_implied_vol(inp, 6.0, steps=100)
    assert isinstance(out, IvUnsolved)
    assert out.reason == "implied_vol_outside_search_interval"
    assert min_tree_vol(inp, 100) == pytest.approx(0.07 * 0.1, rel=1e-6)


def test_low_vega_rule_is_reused() -> None:
    inp = am("C", k=160.0, years=7 / 365, r=0.04, q=0.01)
    out = solve_american_implied_vol(inp, 0.01, steps=100, price_resolution=0.005)
    assert isinstance(out, IvSolved) and out.confidence == "low_vega"
    assert out.iv_uncertainty == pytest.approx(0.005 / out.vega, rel=1e-12)


def test_zero_time_and_bad_numbers_follow_the_european_rules() -> None:
    zero = replace(am("C"), expiry_ts=T0)
    out = solve_american_implied_vol(zero, 1.0, steps=100)
    assert isinstance(out, IvUnsolved) and out.reason == "zero_time_to_expiry"
    with pytest.raises(OptionsDataError) as info:
        solve_american_implied_vol(am("C"), float("nan"), steps=100)
    assert info.value.field == "price"


def test_solve_time_per_contract_and_per_chain_is_recorded_and_bounded() -> None:
    """Measured on this machine (see the invariants page); the bound is deliberately generous."""
    inp = am("P", k=105.0)
    target = tree(inp, 0.3)
    start = clock.perf_counter()
    out = solve_american_implied_vol(inp, target)
    elapsed = clock.perf_counter() - start
    assert isinstance(out, IvSolved) and out.steps == 500
    assert elapsed < 5.0, elapsed


def solved_row(
    steps: int | None = None, dividends: tuple[Dividend, ...] | None = ()
) -> tuple[ChainSnapshot, ChainRow, RowSolve]:
    chain = SyntheticAdapter(
        seed=3,
        surface=VolSurface(),
        priced=PricedModel(rate=0.03, dividend_yield=0.01, american_steps=80),
    ).chain("AAA", date(2023, 3, 1))
    row = next(
        r for r in chain.rows if r.contract.right == "P" and float(r.contract.strike) == 100.0
    )
    kwargs = {} if steps is None else {"steps": steps}
    return chain, row, solve_row(
        row, snapshot_ts=chain.snapshot_ts, underlying_price=chain.underlying_price, rate=0.03,
        dividend_yield=0.01, expiry_time_utc=CLOSE, dividends=dividends, **kwargs,
    )  # fmt: skip


def test_the_american_fixture_is_american_style_and_the_solver_recovers_its_surface() -> None:
    chain = SyntheticAdapter(
        seed=3,
        surface=VolSurface(),
        priced=PricedModel(rate=0.03, dividend_yield=0.01, american_steps=80),
    ).chain("AAA", date(2023, 3, 1))
    assert {r.contract.style for r in chain.rows} == {"A"}
    stored = 0
    for r in chain.rows[:12]:
        out = solve_row(
            r, snapshot_ts=chain.snapshot_ts, underlying_price=chain.underlying_price, rate=0.03,
            dividend_yield=0.01, expiry_time_utc=CLOSE, dividends=(), steps=80,
        )  # fmt: skip
        assert r.provided is not None and r.provided.iv is not None
        if isinstance(out.outcome, IvSolved) and out.outcome.confidence == "normal":
            stored += 1
            assert out.outcome.iv == pytest.approx(r.provided.iv, abs=1e-6)
    assert stored >= 5


def test_solve_row_fills_only_computed_with_the_crr_tag_and_keeps_provided() -> None:
    chain, row, out = solved_row(steps=80)
    assert isinstance(out.outcome, IvSolved)
    assert out.row.provided == row.provided
    block = out.row.computed
    assert block is not None and block.source == "computed"
    parts = block.model.split(";")
    assert "model=crr_tree" in parts and "steps=80" in parts and "r=0.03" in parts
    assert "q=0.01" in parts and "divs=none" in parts
    assert parts[-2:] == ["theta=per_calendar_day", "vega=per_1.00_vol"]
    assert block.iv == pytest.approx(out.outcome.iv, abs=0) and chain.snapshot_ts == T0


def test_an_american_row_needs_dividends_stated_and_a_european_row_does_not() -> None:
    with pytest.raises(OptionsDataError) as info:
        solved_row(steps=80, dividends=None)
    assert info.value.field == "dividends"


def test_european_fixture_rows_still_use_the_closed_form_tag() -> None:
    chain = SyntheticAdapter(
        seed=3, surface=VolSurface(), priced=PricedModel(rate=0.03, dividend_yield=0.01)
    ).chain("AAA", date(2023, 3, 1))
    r = next(x for x in chain.rows if float(x.contract.strike) == 100.0 and x.contract.right == "C")
    out = solve_row(
        r, snapshot_ts=chain.snapshot_ts, underlying_price=chain.underlying_price, rate=0.03,
        dividend_yield=0.01, expiry_time_utc=CLOSE,
    )  # fmt: skip
    assert out.row.computed is not None
    assert out.row.computed.model.startswith("black-scholes-merton-v1;")
