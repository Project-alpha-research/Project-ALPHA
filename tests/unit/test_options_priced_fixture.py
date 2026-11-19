"""Model-priced fixture: the solver recovers the known surface and stores a computed block."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest

from alpha_data.options import ChainRow, OptionsStore, SyntheticAdapter, VolSurface
from alpha_data.options.fixture import PricedModel
from alpha_data.options.implied import IvUnsolved, mid_price, solve_row, years_between
from alpha_data.options.pricing import OptionInputs, price

DAY = date(2023, 3, 1)
MODEL = PricedModel(rate=0.03, dividend_yield=0.015)
SURFACE = VolSurface(base=0.2, skew=-0.1, term=0.02)
CLOSE = time(21, 0)
FETCHED = datetime(2023, 3, 10, tzinfo=UTC)


def priced() -> SyntheticAdapter:
    return SyntheticAdapter(seed=5, surface=SURFACE, priced=MODEL)


def test_placeholder_mode_is_unchanged_american_and_not_model_priced() -> None:
    plain = SyntheticAdapter(seed=5, surface=SURFACE).chain("AAA", DAY)
    assert {r.contract.style for r in plain.rows} == {"A"}
    assert plain == SyntheticAdapter(seed=5, surface=SURFACE, priced=None).chain("AAA", DAY)


def test_priced_chain_is_european_deterministic_and_the_mid_is_the_model_price() -> None:
    chain = priced().chain("AAA", DAY)
    assert chain == priced().chain("AAA", DAY)
    assert {r.contract.style for r in chain.rows} == {"E"}
    for r in chain.rows:
        assert r.quote is not None and 0 <= r.quote.bid < r.quote.ask
        assert r.provided is not None and r.provided.iv is not None
        t = years_between(chain.snapshot_ts, datetime.combine(r.contract.expiry, CLOSE, UTC))
        inp = OptionInputs(
            underlying=chain.underlying_price, kind="spot", strike=float(r.contract.strike),
            years=t, rate=MODEL.rate, dividend_yield=MODEL.dividend_yield, right=r.contract.right,
        )  # fmt: skip
        mid = mid_price(r.quote).value
        assert mid == pytest.approx(price(inp, r.provided.iv), rel=1e-12, abs=1e-15)


def solved(row: ChainRow, chain_price: float, snap: datetime) -> ChainRow:
    out = solve_row(
        row, snapshot_ts=snap, underlying_price=chain_price, rate=MODEL.rate,
        dividend_yield=MODEL.dividend_yield, expiry_time_utc=CLOSE,
    )  # fmt: skip
    return out.row


def test_the_solver_recovers_the_surface_from_fixture_mids_and_fills_only_the_computed_slot() -> (
    None
):
    """Tolerance 1e-7 in volatility for every normal-confidence row; at least 90% of rows."""
    chain = priced().chain("AAA", DAY)
    normal = 0
    for r in chain.rows:
        out = solve_row(
            r, snapshot_ts=chain.snapshot_ts, underlying_price=chain.underlying_price,
            rate=MODEL.rate, dividend_yield=MODEL.dividend_yield, expiry_time_utc=CLOSE,
        )  # fmt: skip
        assert out.row.provided == r.provided  # provider values are never touched
        if out.row.computed is None:
            assert isinstance(out.outcome, IvUnsolved) or out.outcome.confidence == "low_vega"
            continue
        normal += 1
        c = out.row.computed
        assert c.source == "computed" and c.model.startswith("black-scholes-merton-v1")
        assert "r=0.03" in c.model and "q=0.015" in c.model and "act365f" in c.model
        assert r.provided is not None and r.provided.iv is not None
        assert c.iv == pytest.approx(r.provided.iv, abs=1e-7)
        assert c.vega is not None and c.vega > 0 and c.gamma is not None and c.gamma > 0
        assert c.delta is not None and math.isfinite(c.theta or 0.0)
    assert normal / len(chain.rows) >= 0.75


def test_solved_rows_survive_the_store_and_a_research_read(tmp_path: Path) -> None:
    adapter = priced()
    chain = adapter.chain("AAA", DAY)
    rows = tuple(solved(r, chain.underlying_price, chain.snapshot_ts) for r in chain.rows)
    want = next(r for r in rows if r.computed is not None)
    store = OptionsStore(tmp_path)
    store.write(replace(chain, rows=rows), fetched_at=FETCHED, adapter_version="fixture-priced-1")
    got = store.chain_as_of("fixture", "AAA", datetime(2023, 3, 2, tzinfo=UTC)).chain
    assert got is not None
    first = next(r for r in got.rows if r.contract.key == want.contract.key)
    assert first.computed is not None and first.computed.source == "computed"
    assert first.provided is not None and first.provided.source == "provided"
    assert first.computed == want.computed
