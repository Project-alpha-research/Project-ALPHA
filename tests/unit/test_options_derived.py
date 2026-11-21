"""Derived options series: known answers on a chain priced from a KNOWN volatility surface.

Every chain here is built by pricing Black-Scholes-Merton at chosen vols, so the expected number
is computed by hand in the test from the surface, with its own formulas (not the module's).
Solver outputs are checked to 1e-6 absolute: the root finder stops at 1e-14 in vol and the mid
carries float rounding, so 1e-6 is a wide, honest bound. Exact arithmetic is checked at 1e-9.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from alpha_core.reserve import RESERVED_DAY
from alpha_data.options import (
    ChainRow,
    ChainSnapshot,
    ContractId,
    OptionInputs,
    OptionsStore,
    PricedModel,
    Quote,
    SnapshotsRead,
    SyntheticAdapter,
    VolSurface,
    price,
)
from alpha_data.options.derived import (
    RealizedPoint,
    derive,
    interpolate_total_variance,
    rank_and_percentile,
)
from alpha_data.options.derived_params import SERIES, SurfaceConfig

D0 = date(2023, 3, 1)
RATE, DIV = 0.03, 0.01
CFG = SurfaceConfig(rate=RATE, dividend_yield=DIV)
exact_approx = partial(pytest.approx, rel=1e-9, abs=1e-12)
solved_approx = partial(pytest.approx, abs=1e-6)
STRIKES = tuple(Decimal(str(80 + 2.5 * i)) for i in range(17))
Surface = Callable[[float, float, float], float]


def surface(base: float = 0.20, skew: float = -0.10, term: float = 0.02) -> Surface:
    return lambda k, s, t: base + skew * (k / s - 1.0) + term * t


def ts_of(day: date) -> datetime:
    return datetime.combine(day, time(21, 0), UTC)


def make_chain(
    day: date,
    *,
    spot: float = 100.0,
    vol: Surface | None = None,
    expiry_days: tuple[int, ...] = (21, 49, 84, 112),
    strikes: tuple[Decimal, ...] = STRIKES,
    rights: str = "CP",
    style: str = "E",
    delay: timedelta = timedelta(0),
    edit: Callable[[ChainRow], ChainRow] | None = None,
) -> ChainSnapshot:
    vol = vol or surface()
    ts = ts_of(day)
    rows: list[ChainRow] = []
    for n in expiry_days:
        expiry, years = day + timedelta(days=n), n / 365.0
        for strike in strikes:
            for right in rights:
                inp = OptionInputs(
                    underlying=spot, kind="spot", strike=float(strike), years=years,
                    rate=RATE, dividend_yield=DIV, right=right,
                )  # fmt: skip
                mid = price(inp, vol(float(strike), spot, years))
                contract = ContractId(
                    underlying_id="AAA",
                    root="AAA",
                    expiry=expiry,
                    strike=strike,
                    right=right,
                    style=style,
                    multiplier=100,
                    listed_on=None,
                    provider_symbol=f"s{n}{right}{strike}",
                )
                quote = Quote(bid=mid * 0.995, ask=mid * 1.005, quote_ts=ts)
                row = ChainRow(contract=contract, quote=quote)
                rows.append(edit(row) if edit else row)
    return ChainSnapshot(
        provider="test", underlying_id="AAA", snapshot_ts=ts, known_at=ts + delay,
        underlying_price=spot, rows=tuple(rows),
    )  # fmt: skip


def read_of(*snaps: ChainSnapshot, held_back: int = 0) -> SnapshotsRead:
    return SnapshotsRead(tuple(snaps), held_back)


def one(snap: ChainSnapshot, name: str) -> tuple[float | None, str | None]:
    out = derive(read_of(snap), CFG, series=(name,))
    point = out.series[name][-1]
    return point.value, point.reason


# ---- hand-computed expectations, independent of the module -----------------------------------


def forward(spot: float, years: float) -> float:
    return spot * math.exp((RATE - DIV) * years)


def atm_vol(vol: Surface, spot: float, days: int) -> float:
    """The surface at the forward strike: linear in strike, so strike interpolation is exact."""
    years = days / 365.0
    return vol(forward(spot, years), spot, years)


def cm_vol(vol: Surface, spot: float, lo: int, hi: int, target: int) -> float:
    """Total variance linear in time between two expiries, hand-written."""
    w1 = atm_vol(vol, spot, lo) ** 2 * lo / 365.0
    w2 = atm_vol(vol, spot, hi) ** 2 * hi / 365.0
    w = w1 + (w2 - w1) * (target - lo) / (hi - lo)
    return math.sqrt(w / (target / 365.0))


def cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fwd_delta(spot: float, strike: float, vol: float, days: int, right: str) -> float:
    years = days / 365.0
    d1 = (math.log(forward(spot, years) / strike) + 0.5 * vol * vol * years) / (
        vol * math.sqrt(years)
    )
    return cdf(d1) if right == "C" else cdf(d1) - 1.0


def wing_25(vol: Surface, spot: float, days: int, right: str) -> float:
    """Linear interpolation of IV in |delta| between the two OTM strikes around 0.25."""
    years, f = days / 365.0, forward(spot, days / 365.0)
    pts = []
    for s in STRIKES:
        k = float(s)
        if (right == "P" and k <= f) or (right == "C" and k >= f):
            v = vol(k, spot, years)
            pts.append((abs(fwd_delta(spot, k, v, days, right)), v))
    pts.sort()
    for (d1, v1), (d2, v2) in zip(pts, pts[1:], strict=False):
        if d1 <= 0.25 <= d2:
            return v1 + (v2 - v1) * (0.25 - d1) / (d2 - d1)
    raise AssertionError("test chain does not bracket 25 delta")


def skew_cm(vol: Surface, spot: float, lo: int, hi: int, target: int) -> float:
    def at(right: str) -> float:
        w1 = wing_25(vol, spot, lo, right) ** 2 * lo / 365.0
        w2 = wing_25(vol, spot, hi, right) ** 2 * hi / 365.0
        return math.sqrt((w1 + (w2 - w1) * (target - lo) / (hi - lo)) / (target / 365.0))

    return at("P") - at("C")


# ---- iv30, term slope, skew ------------------------------------------------------------------


def test_iv30_recovers_the_variance_interpolated_known_vol() -> None:
    value, reason = one(make_chain(D0), "iv30")
    assert reason is None
    assert value == solved_approx(cm_vol(surface(), 100.0, 21, 49, 30))


def test_iv30_is_not_the_vol_linear_or_strike_linear_answer() -> None:
    """The rule is variance-linear: the vol-linear answer differs in the 7th decimal or more."""
    s = surface(term=0.40)
    value, _ = one(make_chain(D0, vol=s), "iv30")
    v1, v2 = atm_vol(s, 100.0, 21), atm_vol(s, 100.0, 49)
    vol_linear = v1 + (v2 - v1) * (30 - 21) / (49 - 21)
    assert value == solved_approx(cm_vol(s, 100.0, 21, 49, 30))
    assert abs(value - vol_linear) > 1e-7 if value is not None else False


def test_an_expiry_exactly_at_30_days_is_used_alone() -> None:
    value, _ = one(make_chain(D0, expiry_days=(30, 60, 90, 120)), "iv30")
    assert value == solved_approx(atm_vol(surface(), 100.0, 30))


def test_flat_surface_gives_zero_skew_zero_term_and_the_base_iv30() -> None:
    flat = surface(base=0.25, skew=0.0, term=0.0)
    snap = make_chain(D0, vol=flat, expiry_days=(21, 49, 84, 98))
    iv30, _ = one(snap, "iv30")
    skew, skew_reason = one(snap, "skew_25d")
    term, term_reason = one(snap, "term_slope")
    assert (skew_reason, term_reason) == (None, None)
    assert iv30 == solved_approx(0.25)
    assert skew == solved_approx(0.0)
    assert term == solved_approx(0.0)


def test_term_slope_is_iv_at_90_days_minus_iv30() -> None:
    snap = make_chain(D0, expiry_days=(21, 49, 84, 98))
    term, reason = one(snap, "term_slope")
    assert reason is None
    expected = cm_vol(surface(), 100.0, 84, 98, 90) - cm_vol(surface(), 100.0, 21, 49, 30)
    assert term == solved_approx(expected)


def test_skew_25d_is_put_iv_minus_call_iv_in_delta_space() -> None:
    snap = make_chain(D0)
    skew, reason = one(snap, "skew_25d")
    assert reason is None
    expected = skew_cm(surface(), 100.0, 21, 49, 30)
    assert skew == solved_approx(expected)
    assert skew is not None and skew > 0.0  # the surface has a downward skew: puts richer


# ---- null cases: never extrapolate -----------------------------------------------------------


def test_no_expiry_below_30_days_means_null_with_a_reason() -> None:
    value, reason = one(make_chain(D0, expiry_days=(35, 63, 91)), "iv30")
    assert value is None and reason == "no_expiry_at_or_below_30d"


def test_no_expiry_above_30_days_means_null_with_a_reason() -> None:
    value, reason = one(make_chain(D0, expiry_days=(9, 16, 23)), "iv30")
    assert value is None and reason == "no_expiry_at_or_above_30d"


def test_term_slope_is_null_when_90_days_is_not_bracketed() -> None:
    snap = make_chain(D0, expiry_days=(21, 49, 77))
    assert one(snap, "term_slope") == (None, "no_expiry_at_or_above_90d")
    assert one(snap, "iv30")[1] is None


def test_an_expiry_inside_the_minimum_days_is_not_used() -> None:
    snap = make_chain(D0, expiry_days=(3, 49, 84))
    assert one(snap, "iv30") == (None, "no_expiry_at_or_below_30d")


def test_wings_missing_gives_null_skew_with_a_reason() -> None:
    narrow = tuple(Decimal(str(97.5 + 2.5 * i)) for i in range(3))
    value, reason = one(make_chain(D0, strikes=narrow), "skew_25d")
    assert value is None and reason in {"put_wing_not_bracketed", "call_wing_not_bracketed"}


def test_too_few_quoted_strikes_make_an_expiry_unusable() -> None:
    thin = (Decimal(95), Decimal(100))
    value, reason = one(make_chain(D0, strikes=thin), "iv30")
    assert value is None and reason == "no_expiry_at_or_below_30d"


# ---- filters: crossed, zero-width, zero bid --------------------------------------------------


def poison_atm(row: ChainRow) -> ChainRow:
    """Break every quote at 100 and 102.5 on the 21-day expiry in a different bad way."""
    c = row.contract
    if c.expiry != D0 + timedelta(days=21) or c.strike not in (Decimal(100), Decimal("102.5")):
        return row
    assert row.quote is not None
    mid = (row.quote.bid + row.quote.ask) / 2
    bad = {
        ("C", Decimal(100)): Quote(bid=mid * 3, ask=mid, quote_ts=row.quote.quote_ts),
        ("P", Decimal(100)): Quote(bid=mid, ask=mid, quote_ts=row.quote.quote_ts),
        ("C", Decimal("102.5")): Quote(bid=0.0, ask=mid * 9, quote_ts=row.quote.quote_ts),
        ("P", Decimal("102.5")): Quote(bid=mid * 8, ask=mid * 7, quote_ts=row.quote.quote_ts),
    }[(c.right, c.strike)]
    return replace(row, quote=bad)


def test_crossed_zero_width_and_zero_bid_quotes_are_dropped_not_averaged() -> None:
    """Dropped rows leave the neighbours; the answer stays on the surface (strikes 97.5, 105)."""
    clean = one(make_chain(D0), "iv30")[0]
    dirty = one(make_chain(D0, edit=poison_atm), "iv30")[0]
    assert dirty is not None and clean is not None
    assert dirty == solved_approx(clean)


def test_a_stale_quote_is_dropped_not_used() -> None:
    """A quote older than MAX_QUOTE_AGE before the snapshot is stale: dropped like a crossed one."""
    from alpha_data.options.derived_params import MAX_QUOTE_AGE

    def aged(age: timedelta, scale: float) -> Callable[[ChainRow], ChainRow]:
        def edit(row: ChainRow) -> ChainRow:
            if poison_atm(row) is row or row.quote is None:
                return row
            q = row.quote
            return replace(
                row, quote=Quote(bid=q.bid * scale, ask=q.ask * scale, quote_ts=q.quote_ts - age)
            )

        return edit

    clean = one(make_chain(D0, edit=poison_atm), "iv30")[0]
    dirty = one(make_chain(D0, edit=aged(MAX_QUOTE_AGE + timedelta(seconds=1), 5.0)), "iv30")[0]
    assert dirty is not None and clean is not None
    assert dirty == solved_approx(clean)
    at_limit = one(make_chain(D0, edit=aged(MAX_QUOTE_AGE, 1.0)), "iv30")[0]
    assert at_limit == solved_approx(one(make_chain(D0), "iv30")[0])  # exactly the limit is used


def test_a_quote_that_is_only_bad_on_one_side_still_uses_the_good_side() -> None:
    def kill_puts(row: ChainRow) -> ChainRow:
        if row.contract.right == "P" and row.quote is not None:
            return replace(
                row, quote=Quote(bid=0.0, ask=row.quote.ask, quote_ts=row.quote.quote_ts)
            )
        return row

    value, reason = one(make_chain(D0, edit=kill_puts), "iv30")
    assert reason is None  # calls remain, so the nearest-strike rule gives a reading
    calls_only, _ = one(make_chain(D0, rights="C"), "iv30")
    assert value == solved_approx(calls_only)


def test_calls_only_falls_back_to_the_nearest_strike_to_spot_with_a_label() -> None:
    snap = make_chain(D0, rights="C")
    out = derive(read_of(snap), CFG, series=("iv30",))
    point = out.series["iv30"][-1]
    assert point.label == "nearest_strike_to_spot"
    # Strike 100 is nearest spot; the surface there (not at the forward) is the answer, with the
    # variance rule across expiries applied to those two vols.
    w1 = surface()(100.0, 100.0, 21 / 365.0) ** 2 * 21 / 365.0
    w2 = surface()(100.0, 100.0, 49 / 365.0) ** 2 * 49 / 365.0
    expected = math.sqrt((w1 + (w2 - w1) * 9 / 28) / (30 / 365.0))
    assert point.value == solved_approx(expected)


def test_parity_forward_is_labelled() -> None:
    out = derive(read_of(make_chain(D0)), CFG, series=("iv30",))
    assert out.series["iv30"][-1].label == "parity_forward"


# ---- american contracts use the tree ---------------------------------------------------------


def test_american_style_contracts_use_the_tree_and_the_nearest_strike() -> None:
    steps = 40
    model = PricedModel(rate=RATE, dividend_yield=DIV, american_steps=steps)
    surf = VolSurface(base=0.2, skew=-0.1, term=0.02)
    chain = SyntheticAdapter(seed=3, surface=surf, priced=model).chain("AAA", D0)
    assert {r.contract.style for r in chain.rows} == {"A"}
    cfg = replace(CFG, american_steps=steps)
    out = derive(read_of(chain), cfg, series=("iv30",))
    point = out.series["iv30"][-1]
    assert point.reason is None and point.label == "nearest_strike_to_spot"
    lows = sorted({r.contract.expiry for r in chain.rows})
    days = [(e - D0).days for e in lows]
    lo = max(d for d in days if d <= 30)
    hi = min(d for d in days if d >= 30)
    spot = chain.underlying_price
    k = min(
        (float(s) for s in {r.contract.strike for r in chain.rows}), key=lambda x: abs(x - spot)
    )
    w = [surf.iv(k, spot, d / 365.0) ** 2 * d / 365.0 for d in (lo, hi)]
    frac = 0.0 if hi == lo else (30 - lo) / (hi - lo)
    expected = math.sqrt((w[0] + (w[1] - w[0]) * frac) / (30 / 365.0))
    assert point.value == pytest.approx(expected, abs=1e-5)


# ---- rank and percentile ---------------------------------------------------------------------


def test_rank_and_percentile_known_answers_over_252_values() -> None:
    values: list[float | None] = [0.10 + 0.0005 * i for i in range(252)]
    values[100], values[251] = 0.30, 0.20  # a high past value, and today in the middle
    out = rank_and_percentile(values, 252)
    rank, pct, reason = out[251]
    assert reason is None
    lo, hi = min(v for v in values if v is not None), 0.30
    assert rank == exact_approx((0.20 - lo) / (hi - lo))
    below = sum(1 for v in values if v is not None and v < 0.20)
    assert pct == exact_approx(below / 252)


def test_rank_is_null_until_252_sessions_exist() -> None:
    out = rank_and_percentile([0.2 + 0.001 * i for i in range(251)], 252)
    assert all(r == (None, None, "warm_up_252") for r in out)


def test_flat_window_gives_null_rank() -> None:
    out = rank_and_percentile([0.2] * 252, 252)
    assert out[-1] == (None, None, "flat_window")


def test_today_missing_or_a_gap_in_the_window_gives_null_with_a_reason() -> None:
    values: list[float | None] = [0.2 + 0.001 * (i % 7) for i in range(260)]
    values[259] = None
    assert rank_and_percentile(values, 252)[259][2] == "iv30_missing"
    values[259], values[200] = 0.25, None
    assert rank_and_percentile(values, 252)[259][2] == "gap_in_window"
    assert rank_and_percentile(values, 252)[251][2] == "gap_in_window"


def test_rank_window_includes_today_and_rolls() -> None:
    values: list[float | None] = [float(i) for i in range(300)]
    rank, pct, _ = rank_and_percentile(values, 252)[299]
    assert rank == exact_approx(1.0)  # today is the window max
    assert pct == exact_approx(251 / 252)  # 251 of 252 values are below it
    assert rank_and_percentile(values, 252)[251][0] == exact_approx(1.0)


def test_end_to_end_rank_over_a_real_chain_series() -> None:
    days = [D0 + timedelta(days=i) for i in range(8)]
    bases = [0.20, 0.25, 0.15, 0.30, 0.22, 0.18, 0.28, 0.24]
    snaps = [make_chain(d, vol=surface(b, 0.0, 0.0)) for d, b in zip(days, bases, strict=True)]
    out = derive(read_of(*snaps), CFG, series=("iv30", "iv_rank_252"), rank_window=5)
    ranks = [p.value for p in out.series["iv_rank_252"]]
    assert ranks[:4] == [None] * 4
    window = bases[3:8]
    assert ranks[7] == solved_approx((0.24 - min(window)) / (max(window) - min(window)))


# ---- known_from ------------------------------------------------------------------------------


def test_known_from_is_the_snapshots_own_known_at_never_earlier() -> None:
    delay = timedelta(hours=5)
    snaps = [make_chain(D0 + timedelta(days=i), delay=delay) for i in range(3)]
    out = derive(read_of(*snaps), CFG, series=("iv30", "skew_25d", "term_slope"))
    for name in ("iv30", "skew_25d", "term_slope"):
        for point, snap in zip(out.series[name], snaps, strict=True):
            assert point.known_from == snap.known_at == snap.snapshot_ts + delay
            assert point.known_from >= snap.snapshot_ts


def test_a_null_value_still_carries_its_known_from() -> None:
    snap = make_chain(D0, expiry_days=(35, 63), delay=timedelta(hours=2))
    point = derive(read_of(snap), CFG, series=("iv30",)).series["iv30"][0]
    assert point.value is None and point.known_from == snap.known_at


def test_rank_known_from_is_the_latest_input_in_its_window() -> None:
    snaps = [
        make_chain(D0 + timedelta(days=i), vol=surface(0.2 + 0.01 * i, 0, 0),
                   delay=timedelta(hours=1 if i != 2 else 30))
        for i in range(6)
    ]  # fmt: skip
    out = derive(read_of(*snaps), CFG, series=("iv_rank_252",), rank_window=4)
    points = out.series["iv_rank_252"]
    assert points[3].known_from == snaps[2].known_at  # window 0..3 contains the late snapshot
    assert points[5].known_from == snaps[5].known_at  # window 2..5: the late one is still inside
    assert points[5].known_from >= snaps[2].known_at


def test_iv_minus_rv_uses_the_realized_vol_and_its_own_known_from() -> None:
    snap = make_chain(D0, delay=timedelta(hours=1))
    rv_known = snap.known_at + timedelta(hours=4)
    realized = {D0: RealizedPoint(0.12, rv_known)}
    out = derive(read_of(snap), CFG, series=("iv30", "iv_minus_rv"), realized=realized)
    iv30 = out.series["iv30"][0].value
    point = out.series["iv_minus_rv"][0]
    assert iv30 is not None and point.value == exact_approx(iv30 - 0.12)
    assert point.known_from == rv_known
    missing = derive(read_of(snap), CFG, series=("iv_minus_rv",), realized={})
    assert missing.series["iv_minus_rv"][0].reason == "no_realized_vol"


# ---- point in time ---------------------------------------------------------------------------


def absurd(row: ChainRow) -> ChainRow:
    assert row.quote is not None
    return replace(row, quote=Quote(bid=1.0, ask=1.01, quote_ts=row.quote.quote_ts))


def run_series(snaps: list[ChainSnapshot]) -> dict[str, list[float | None]]:
    out = derive(read_of(*snaps), CFG, series=SERIES, rank_window=4, realized=realized_for(snaps))
    return {k: [p.value for p in v] for k, v in out.series.items()}


def realized_for(snaps: list[ChainSnapshot]) -> dict[date, RealizedPoint]:
    return {s.snapshot_ts.date(): RealizedPoint(0.10, s.known_at) for s in snaps}


def test_future_poison_changes_nothing_at_or_before_bar_k() -> None:
    days = [D0 + timedelta(days=i) for i in range(9)]
    rng = random.Random(7)
    bases = [0.15 + 0.2 * rng.random() for _ in days]
    clean = [make_chain(d, vol=surface(b, -0.1, 0.02)) for d, b in zip(days, bases, strict=True)]
    k = 5
    poisoned = clean[: k + 1] + [make_chain(d, edit=absurd) for d in days[k + 1 :]]
    base, dirty = run_series(clean), run_series(poisoned)
    for name in SERIES:
        assert dirty[name][: k + 1] == base[name][: k + 1]
    assert dirty["iv30"][k + 1 :] != base["iv30"][k + 1 :]  # the poison is real


def test_a_deliberately_leaky_rank_does_change_so_the_poison_test_has_teeth() -> None:
    values = [0.2, 0.25, 0.15, 0.3, 0.22, 0.18]
    k = 3

    def leaky_rank(series: list[float]) -> float:  # full-sample min and max: sees the future
        return (series[k] - min(series)) / (max(series) - min(series))

    poisoned = [*values[: k + 1], 9.0, 9.0]
    assert leaky_rank(values) != leaky_rank(poisoned)
    honest = rank_and_percentile([*values], 4)
    honest_poisoned = rank_and_percentile([*poisoned], 4)
    assert honest[: k + 1] == honest_poisoned[: k + 1]


def test_rows_on_or_after_the_reserved_day_never_appear(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    adapter = SyntheticAdapter(seed=4, surface=VolSurface(), priced=PricedModel(RATE, DIV))
    days = [RESERVED_DAY + timedelta(days=d) for d in (-3, -2, -1, 0, 3)]
    for d in days:
        store.write(
            adapter.chain("AAA", d),
            fetched_at=datetime(2030, 1, 1, tzinfo=UTC),
            adapter_version="t",
        )
    far = datetime(2031, 1, 1, tzinfo=UTC)
    read = store.snapshots_as_of("fixture", "AAA", far)
    out = derive(read, CFG, series=("iv30", "skew_25d"))
    shown = [p.day for p in out.series["iv30"]]
    assert shown == days[:3]
    assert all(p.day < RESERVED_DAY for s in out.series.values() for p in s)
    assert all(
        p.known_from < datetime.combine(RESERVED_DAY, time.min, UTC) for p in out.series["iv30"]
    )
    assert out.held_back == 2 and out.sessions == 3


def test_one_session_per_day_keeps_the_latest_snapshot() -> None:
    early = make_chain(D0, vol=surface(0.20, 0, 0))
    late = replace(make_chain(D0, vol=surface(0.30, 0, 0)), known_at=ts_of(D0) + timedelta(hours=1))
    out = derive(read_of(early, late), CFG, series=("iv30",))
    assert len(out.series["iv30"]) == 1
    assert out.series["iv30"][0].value == solved_approx(0.30)


# ---- properties ------------------------------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(
    base=st.floats(0.15, 0.60),
    skew=st.floats(-0.2, 0.1),
    term=st.floats(-0.05, 0.15),
    lo=st.integers(14, 29),
    hi=st.integers(31, 60),
    target=st.sampled_from((30,)),
)
def test_iv30_lies_between_the_two_bracketing_atm_vols(
    base: float, skew: float, term: float, lo: int, hi: int, target: int
) -> None:
    surf = surface(base, skew, term)
    snap = make_chain(D0, vol=surf, expiry_days=(lo, hi, 91))
    value, reason = one(snap, "iv30")
    assert reason is None and value is not None
    v1, v2 = atm_vol(surf, 100.0, lo), atm_vol(surf, 100.0, hi)
    assert min(v1, v2) - 1e-6 <= value <= max(v1, v2) + 1e-6
    assert value == pytest.approx(cm_vol(surf, 100.0, lo, hi, target), abs=1e-5)


@given(
    t1=st.floats(0.02, 0.2),
    t2=st.floats(0.21, 0.5),
    v1=st.floats(0.05, 1.0),
    v2=st.floats(0.05, 1.0),
)
def test_total_variance_interpolation_is_linear_in_variance_and_bounded(
    t1: float, t2: float, v1: float, v2: float
) -> None:
    target = (t1 + t2) / 2
    got = interpolate_total_variance(t1, v1, t2, v2, target)
    assert got * got * target == pytest.approx((v1 * v1 * t1 + v2 * v2 * t2) / 2, rel=1e-9)
    assert min(v1, v2) - 1e-12 <= got <= max(v1, v2) + 1e-12 or t1 != t2


def test_the_default_series_list_is_complete() -> None:
    assert SERIES == (
        "iv30", "iv_rank_252", "iv_percentile_252", "skew_25d", "term_slope", "iv_minus_rv",
    )  # fmt: skip
