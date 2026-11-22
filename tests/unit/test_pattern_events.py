"""Pattern events as Setup Lab conditions: one value per bar, known at its confirmation bar.

Fixtures are synthetic. Every family gets a look-ahead test: bars after bar t must not change
the event values at or before t, and a pivot shows on its confirmation bar, never its own bar.
"""

from __future__ import annotations

import numpy as np
import pytest

from alpha_cli import pattern_events as pe
from alpha_cli.pattern_event_base import SWING_LOOKBACK
from alpha_core import DataError
from alpha_patterns import (
    OHLCV,
    geometric_brownian_series,
    inject_descending_trendline,
    inject_head_shoulders,
    inject_triple_tap,
    inject_wedge,
)

CUTS = (150, 233, 300, 377, 450)


def _poison(bars: OHLCV, cut: int) -> OHLCV:
    """Multiply every bar from ``cut`` on by 5: a violent change to the future."""
    cols = {k: getattr(bars, k).copy() for k in ("open", "high", "low", "close", "volume")}
    for key in ("open", "high", "low", "close", "volume"):
        cols[key][cut:] *= 5.0
    return OHLCV(ts=bars.ts, symbol=bars.symbol, **cols)


def _head(bars: OHLCV, n: int) -> OHLCV:
    return OHLCV(
        ts=bars.ts[:n],
        open=bars.open[:n],
        high=bars.high[:n],
        low=bars.low[:n],
        close=bars.close[:n],
        volume=bars.volume[:n],
        symbol=bars.symbol,
    )


def _fixtures() -> list[OHLCV]:
    out = [geometric_brownian_series(600, seed=s, vol_per_bar=0.02) for s in (1, 2, 3)]
    out.append(inject_head_shoulders(500, direction="bullish")[0])
    out.append(inject_head_shoulders(500, direction="bearish")[0])
    out.append(inject_triple_tap(500)[0])
    out.append(inject_wedge(500, kind="falling")[0])
    out.append(inject_wedge(500, kind="rising", break_direction=-1)[0])
    out.append(inject_descending_trendline(500)[0])
    return out


def _same(a: list[float | None], b: list[float | None]) -> bool:
    return a == b


def test_every_family_is_named_and_every_series_belongs_to_one() -> None:
    assert set(pe.FAMILIES) >= {
        "swings",
        "dc_extremes",
        "structure_levels",
        "trendlines",
        "flags",
        "head_shoulders",
        "wedges",
        "triple_taps",
        "harmonics",
    }
    flat = [name for names in pe.FAMILIES.values() for name in names]
    assert len(flat) == len(set(flat))
    assert set(pe.VISIBLE_ONLY) == {"pips", "market_profile", "levels"}
    assert not set(pe.VISIBLE_ONLY) & set(pe.FAMILIES)


@pytest.mark.parametrize("family", sorted(pe.FAMILIES))
def test_family_events_do_not_look_ahead(family: str) -> None:
    seen = 0
    for bars in _fixtures():
        full = pe.event_series(bars, pe.FAMILIES[family])
        for cut in CUTS:
            if cut >= len(bars):
                continue
            cut_series = pe.event_series(_head(bars, cut + 1), pe.FAMILIES[family])
            poisoned = pe.event_series(_poison(bars, cut + 1), pe.FAMILIES[family])
            for name in pe.FAMILIES[family]:
                assert _same(cut_series[name], full[name][: cut + 1]), (family, name, cut)
                assert _same(poisoned[name][: cut + 1], full[name][: cut + 1]), (family, name, cut)
        seen += sum(v == 1.0 for name in pe.FAMILIES[family] for v in full[name])
    assert seen > 0, f"{family} found no event on any fixture: the guard would be vacuous"


def test_a_swing_shows_on_its_confirmation_bar_not_its_own_bar() -> None:
    bars = geometric_brownian_series(300, seed=4, vol_per_bar=0.02)
    from alpha_patterns import find_swings

    swing = find_swings(bars, lookback=SWING_LOOKBACK, kind="high")[3]
    flags = pe.event_series(bars, ("swing_high",))["swing_high"]
    assert flags[swing.confirmed_index] == 1.0
    assert swing.confirmed_index == swing.index + SWING_LOOKBACK
    assert flags[swing.index] == 0.0


def test_warm_up_is_missing_with_a_reason_never_zero() -> None:
    bars = geometric_brownian_series(300, seed=4, vol_per_bar=0.02)
    values = pe.event_series(bars, ("swing_low",))["swing_low"]
    assert values[: pe.WARMUP] == [None] * pe.WARMUP
    assert all(v in (0.0, 1.0) for v in values[pe.WARMUP :])


def test_unknown_series_fails_loud_and_lists_the_names() -> None:
    with pytest.raises(DataError, match="swing_high"):
        pe.series_family("nope")


def test_events_carry_a_label_a_confirmation_bar_and_anchors() -> None:
    bars = inject_head_shoulders(500, direction="bearish")[0]
    events = pe.family_events(bars, "head_shoulders")
    assert events
    for event in events:
        assert event.confirmed_index < len(bars)
        assert event.anchors
        assert event.label
        assert max(i for i, _ in event.anchors) <= event.confirmed_index
        assert np.isfinite([p for _, p in event.anchors]).all()


def test_head_and_shoulders_is_one_event_per_head_with_its_neckline() -> None:
    for bars in (
        inject_head_shoulders(500, direction="bullish")[0],
        inject_head_shoulders(500, direction="bearish")[0],
    ):
        events = pe.family_events(bars, "head_shoulders")
        heads = [e.anchors[2][0] for e in events]
        assert events
        assert len(heads) == len(set(heads))
        for e in events:
            assert len(e.anchors) == 5  # left shoulder, neckline, head, neckline, right shoulder
