"""Shared parts of the chart-pattern events: the event record and the replay on growing prefixes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from alpha_patterns import OHLCV

Shape = Literal["marker", "line", "outline"]
SWING_LOOKBACK = 5
REPLAY_WINDOW = 300  # head and shoulders and wedges: the longest span searched, in bars


@dataclass(frozen=True)
class PatternEvent:
    """One event: its series, the bar it became known, and the points to draw."""

    series: str
    confirmed_index: int
    anchors: tuple[tuple[int, float], ...]
    label: str
    shape: Shape


def ev(
    series: str, at: int, points: Sequence[tuple[int, float]], label: str, shape: Shape
) -> PatternEvent:
    return PatternEvent(series, int(at), tuple((int(i), float(p)) for i, p in points), label, shape)


def prefix(bars: OHLCV, n: int, start: int = 0) -> OHLCV:
    from alpha_patterns import OHLCV

    return OHLCV(
        ts=bars.ts[start:n],
        open=bars.open[start:n],
        high=bars.high[start:n],
        low=bars.low[start:n],
        close=bars.close[start:n],
        volume=bars.volume[start:n],
        symbol=bars.symbol,
    )


def replay(bars: OHLCV, build: Callable[[OHLCV], list[PatternEvent]]) -> list[PatternEvent]:
    """Run `build` on the bars up to each pivot-confirmation bar; keep each event's first sighting.

    Head and shoulders picks its best right shoulder, and a wedge may be judged, with bars after
    its own confirmation. A single run over all bars would let those later bars decide an earlier
    value. Here the event bar is the first bar on which a run over the bars up to that bar sees it.
    """
    from alpha_patterns import find_swings

    swings = find_swings(bars, lookback=SWING_LOOKBACK, kind="high")
    swings += find_swings(bars, lookback=SWING_LOOKBACK, kind="low")
    checkpoints = sorted({s.confirmed_index for s in swings})
    seen: dict[tuple[str, tuple[tuple[int, float], ...]], PatternEvent] = {}
    for at in checkpoints:
        if at < 1:
            continue
        start = max(0, at + 1 - REPLAY_WINDOW)
        for e in build(prefix(bars, at + 1, start)):
            anchors = tuple((i + start, p) for i, p in e.anchors)
            if (e.series, anchors) not in seen:
                seen[(e.series, anchors)] = PatternEvent(e.series, at, anchors, e.label, e.shape)
    return list(seen.values())
