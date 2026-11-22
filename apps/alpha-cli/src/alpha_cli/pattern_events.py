"""Chart-pattern events for Setup Lab and the chart picture: one value per bar, known on time.

Each series is `1.0` on the bar where a pattern event was first knowable and `0.0` on every other
bar. The first `WARMUP` bars are missing (never zero). The event bar is the confirmation bar of the
pattern, never the bar where its pivot sits, so a condition on bar t reads only bars up to t.
Detectors run once over the bars the caller may read. `tests/unit/test_pattern_events.py` proves
per family that bars after t never change the values at or before t. Pure; no authority.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import numpy as np

from alpha_cli.pattern_event_base import SWING_LOOKBACK, PatternEvent, ev, replay
from alpha_core import DataError

if TYPE_CHECKING:
    from alpha_patterns import OHLCV, TrendlineBreak

DC_SIGMA = 0.02
STRUCTURE_ATR = 14
WARMUP = 60
RECIPE = "chart-patterns-v1"

FAMILIES: dict[str, tuple[str, ...]] = {
    "swings": ("swing_high", "swing_low"),
    "dc_extremes": ("dc_high", "dc_low"),
    "structure_levels": ("structure_high", "structure_low"),
    "trendlines": ("falling_line_break", "rising_line_break"),
    "flags": ("bull_flag", "bear_flag", "bull_pennant", "bear_pennant"),
    "head_shoulders": ("hs_top", "hs_bottom"),
    "wedges": ("wedge_falling", "wedge_rising", "wedge_symmetrical"),
    "triple_taps": ("triple_tap",),
    "harmonics": ("harmonic_bull", "harmonic_bear"),
}
# Families drawn on the chart that are not events with a confirmation bar.
VISIBLE_ONLY: dict[str, str] = {
    "pips": "the points move as the window moves, so there is no event with a time",
    "market_profile": "it draws price levels at the last bar, not an event on a bar",
    "levels": "it draws a Fibonacci grid at the last bar, not an event on a bar",
}


def series_family(name: str) -> str:
    for family, names in FAMILIES.items():
        if name in names:
            return family
    known = [n for names in FAMILIES.values() for n in names]
    raise DataError(f"unknown pattern series {name!r}; choose from {known}")


def _swings(bars: OHLCV) -> list[PatternEvent]:
    from alpha_patterns import find_swings

    out = []
    for kind in ("high", "low"):
        for s in find_swings(bars, lookback=SWING_LOOKBACK, kind=kind):
            out.append(
                ev(
                    f"swing_{kind}",
                    s.confirmed_index,
                    [(s.index, s.price)],
                    f"Swing {kind}",
                    "marker",
                )
            )
    return out


def _dc(bars: OHLCV) -> list[PatternEvent]:
    from alpha_patterns import directional_change

    return [
        ev(f"dc_{e.kind}", e.confirmed_index, [(e.index, e.price)], f"DC {e.kind}", "marker")
        for e in directional_change(bars, sigma=DC_SIGMA)
    ]


def _structure(bars: OHLCV) -> list[PatternEvent]:
    from alpha_patterns import hierarchical_extremes

    tier = hierarchical_extremes(bars, levels=1, atr_lookback=STRUCTURE_ATR)[0]
    return [
        ev(
            f"structure_{x.kind}",
            x.confirmed_index,
            [(x.index, x.price)],
            f"Structure {x.kind}",
            "marker",
        )
        for x in tier
    ]


def _mirror(bars: OHLCV) -> OHLCV:
    """Prices as 1/p: a rising support line becomes a falling resistance line."""
    from alpha_patterns import OHLCV

    return OHLCV(
        ts=bars.ts,
        open=1.0 / bars.open,
        high=1.0 / bars.low,
        low=1.0 / bars.high,
        close=1.0 / bars.close,
        volume=bars.volume,
        symbol=bars.symbol,
    )


def _line_breaks(bars: OHLCV, name: str, flip: bool) -> list[PatternEvent]:
    from alpha_patterns import TrendlineConfig, build_trendlines, find_breaks

    cfg = TrendlineConfig(lookback=SWING_LOOKBACK)
    lines = build_trendlines(bars, cfg)
    first: dict[int, TrendlineBreak] = {}
    for brk in find_breaks(bars, lines, cfg=cfg):
        key = id(brk.line)
        if key not in first or brk.break_index < first[key].break_index:
            first[key] = brk
    out = []
    for brk in first.values():
        line = brk.line
        i1, i2 = line.anchor_indices
        p1, p2 = line.anchor_prices
        at = brk.break_index
        pts = [(i1, p1), (i2, p2), (at, brk.line_price)]
        if flip:
            pts = [(i, 1.0 / p) for i, p in pts]
        word = "Rising line broke down" if flip else "Falling line broke up"
        out.append(ev(name, at, pts, f"{word} ({line.touches} touches)", "line"))
    return out


def _trendlines(bars: OHLCV) -> list[PatternEvent]:
    return _line_breaks(bars, "falling_line_break", False) + _line_breaks(
        _mirror(bars), "rising_line_break", True
    )


def _flags(bars: OHLCV) -> list[PatternEvent]:
    from alpha_patterns import detect_flags_pips

    out = []
    for f in detect_flags_pips(np.log(bars.close), order=SWING_LOOKBACK):
        word = "pennant" if f.pennant else "flag"
        side = "bull" if f.bullish else "bear"
        pts = [(f.base_index, math.exp(f.base_price)), (f.tip_index, math.exp(f.tip_price))]
        pts.append((f.confirmed_index, math.exp(f.confirmed_price)))
        out.append(
            ev(f"{side}_{word}", f.confirmed_index, pts, f"{side.title()} {word}", "outline")
        )
    return out


def _head_shoulders(bars: OHLCV) -> list[PatternEvent]:
    return replay(bars, _hs_events)


def _hs_events(bars: OHLCV) -> list[PatternEvent]:
    from alpha_patterns import HSConfig, detect_head_shoulders

    out = []
    tops = detect_head_shoulders(bars, HSConfig(direction="bearish"))
    bottoms = detect_head_shoulders(bars, HSConfig(direction="bullish"))
    for name, word, found in (
        ("hs_top", "Head and shoulders top", tops),
        ("hs_bottom", "Inverse head and shoulders", bottoms),
    ):
        for h in found:
            pts = [(h.ls_index, h.ls_price), (h.head_index, h.head_price), (h.rs_index, h.rs_price)]
            out.append(ev(name, h.confirmed_index, pts, word, "outline"))
    return out


def _wedge_events(bars: OHLCV) -> list[PatternEvent]:
    from alpha_patterns import detect_wedges

    out = []
    for w in detect_wedges(bars):
        u = list(zip(w.upper_indices, w.upper_prices, strict=True))
        low = list(zip(w.lower_indices, w.lower_prices, strict=True))
        out.append(
            ev(
                f"wedge_{w.kind}",
                w.confirmed_index,
                [*u, *reversed(low)],
                f"{w.kind.title()} wedge",
                "outline",
            )
        )
    return out


def _wedges(bars: OHLCV) -> list[PatternEvent]:
    return replay(bars, _wedge_events)


def _triple_taps(bars: OHLCV) -> list[PatternEvent]:
    from alpha_patterns import detect_triple_taps

    return [
        ev(
            "triple_tap",
            t.confirmed_index,
            list(zip(t.tap_indices, t.tap_prices, strict=True)),
            "Triple tap",
            "line",
        )
        for t in detect_triple_taps(bars)
    ]


def _harmonics(bars: OHLCV) -> list[PatternEvent]:
    from alpha_patterns import detect_harmonics, directional_change

    scan = detect_harmonics(bars, directional_change(bars, sigma=DC_SIGMA))
    out = []
    for h in scan.patterns:
        side = "bull" if h.bullish else "bear"
        pts = [(i, float(bars.close[i])) for i in (h.x, h.a, h.b, h.c, h.d)]
        out.append(ev(f"harmonic_{side}", h.confirmed_index, pts, f"{h.name} ({side}ish)", "line"))
    return out


_BUILDERS: dict[str, Callable[[OHLCV], list[PatternEvent]]] = {
    "swings": _swings,
    "dc_extremes": _dc,
    "structure_levels": _structure,
    "trendlines": _trendlines,
    "flags": _flags,
    "head_shoulders": _head_shoulders,
    "wedges": _wedges,
    "triple_taps": _triple_taps,
    "harmonics": _harmonics,
}


def family_events(bars: OHLCV, family: str) -> list[PatternEvent]:
    """Every event of one family on the bars, in order of the bar it became known."""
    if family not in _BUILDERS:
        raise DataError(f"unknown pattern family {family!r}; choose from {sorted(_BUILDERS)}")
    events = _BUILDERS[family](bars)
    last = len(bars) - 1
    if any(e.confirmed_index > last or e.confirmed_index < 0 for e in events):
        raise DataError(f"{family} reported an event outside the bars")
    return sorted(events, key=lambda e: (e.confirmed_index, e.series))


def event_series(bars: OHLCV, names: Sequence[str]) -> dict[str, list[float | None]]:
    """`1.0` on the bar an event became known, else `0.0`; the first `WARMUP` bars are None."""
    n = len(bars)
    out: dict[str, list[float | None]] = {}
    for family in dict.fromkeys(series_family(name) for name in names):
        events = family_events(bars, family)
        for name in FAMILIES[family]:
            if name not in names:
                continue
            values: list[float | None] = [None] * min(WARMUP, n) + [0.0] * max(0, n - WARMUP)
            for e in events:
                if e.series == name and e.confirmed_index >= WARMUP:
                    values[e.confirmed_index] = 1.0
            out[name] = values
    return out
