"""The picture behind `alpha chart overlays -p <pattern>`: price with the pattern drawn on it.

Two PNG files in the product's figure style (white, standard matplotlib): a plain one and an
annotated one with notes and a "How to read this chart" box. Event families draw what
`pattern_events` finds, each event placed by the bar it became known. Families that draw levels
at the last bar (`VISIBLE_ONLY`) draw the rows `chart_cmds.pattern_annotations` makes. Display
only; no authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alpha_core import Bar, DataError

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from alpha_patterns import OHLCV

DEFAULT_DAYS = 730
HELD_BACK_NOTE = (
    "This picture shows data from the held-back period. Looking at a chart is not a test; "
    "pattern tests in Setup Lab do not use this period."
)
NOTES = 3  # the most recent events that get a note in the annotated picture
GAP_DAYS = 15  # drawn lines and outlines are known at least this many days apart
MAX_DRAWN = 5  # lines and outlines: only the most recent are drawn, or the picture is a tangle
COLOURS = ("C1", "C2", "C3", "C4", "C5")
HIGH_WORDS = ("high", "top", "bear")  # series names that mark a high or a bearish shape
WHAT = {
    "swings": "Red triangles mark swing highs and green triangles swing lows: a bar higher, or "
    "lower, than the 5 bars on each side of it.",
    "dc_extremes": "Triangles mark turning points: a high or low is fixed once the price has "
    "reversed 2% from it.",
    "structure_levels": "Triangles mark the larger swing highs and lows, judged against the "
    "average daily range.",
    "trendlines": "Each coloured line joins two swing points and runs on to the day the close "
    "broke through it; the cross marks that day. A resistance line (joining highs) broken upward "
    "is a break up; a support line (joining lows) broken downward is a break down.",
    "flags": "Each coloured outline is a sharp move followed by a small drift against it; its "
    "last corner is the day the flag was confirmed.",
    "head_shoulders": "Each coloured line joins the left shoulder, the head and the right "
    "shoulder; the dashed line is the neckline. A top has three highs with the middle one "
    "highest; the inverse has three lows.",
    "wedges": "Each coloured outline joins the swing points of two lines that close in on each "
    "other.",
    "triple_taps": "Each coloured line joins three touches of nearly the same price level.",
    "harmonics": "Each coloured line joins the five points X, A, B, C and D whose distances "
    "match a harmonic shape; D is the last.",
    "pips": "The line joins the most important turning points of the window. They move as the "
    "window moves, so they cannot be tested.",
    "market_profile": "The lines are price levels where the most trading happened in the window.",
    "levels": "The lines are Fibonacci levels between the latest swing high and low.",
}


@dataclass(frozen=True)
class PatternPicture:
    plain: Path
    annotated: Path
    count: int
    window_start: date
    window_end: date
    summary: str


@dataclass(frozen=True)
class _Shape:
    label: str
    shape: str  # marker | line | outline
    points: tuple[tuple[datetime, float], ...]
    known: datetime
    series: str = ""


def _when(series: OHLCV, index: int) -> datetime:
    return datetime.fromtimestamp(float(series.ts[index]) / 1000.0, tz=UTC)


def _shapes(series: OHLCV, pattern: str) -> list[_Shape]:
    from alpha_cli.chart_cmds import parse_pattern, pattern_annotations
    from alpha_cli.pattern_events import FAMILIES, family_events

    if pattern in FAMILIES:
        return [
            _Shape(
                e.label,
                e.shape,
                tuple((_when(series, i), p) for i, p in e.anchors),
                _when(series, e.confirmed_index),
                e.series,
            )
            for e in family_events(series, pattern)
        ]
    known = _when(series, len(series) - 1)
    shapes = []
    for row in pattern_annotations(series, [parse_pattern(pattern)]):
        points = tuple(
            (datetime.fromtimestamp(a["ts"], tz=UTC), float(a["value"])) for a in row["anchors"]
        )
        shape = "marker" if row["kind"] == "marker" else "line"
        shapes.append(_Shape(row["label"], shape, points, known, pattern))
    return shapes


def _num(when: datetime) -> float:
    """The x value matplotlib reads as this day: days since 1970-01-01 UTC."""
    return when.timestamp() / 86400.0


def _clear(s: _Shape, other: _Shape) -> bool:
    """True when two shapes can share a picture: trend lines need only different break days;
    every other shape must also cover a different stretch of days."""
    if s.series.endswith("_line_break"):
        return abs((s.known - other.known).days) >= GAP_DAYS
    first = min(p[0] for p in s.points)
    first_other = min(p[0] for p in other.points)
    return s.known < first_other or other.known < first


def _spread(shapes: list[_Shape]) -> list[_Shape]:
    """The most recent shapes, newest picked first, that do not crowd each other."""
    chosen: list[_Shape] = []
    for s in sorted(shapes, key=lambda x: x.known, reverse=True):
        if all(_clear(s, c) for c in chosen):
            chosen.append(s)
        if len(chosen) == MAX_DRAWN:
            break
    return chosen


def _draw_shape(axes: Axes, s: _Shape, colour: str, number: int | None) -> None:
    xs = [_num(p[0]) for p in s.points]
    ys = [p[1] for p in s.points]
    if s.shape == "marker":
        high = any(w in s.series for w in HIGH_WORDS)
        axes.scatter(
            xs, ys, color="C3" if high else "C2", marker="v" if high else "^", s=34, zorder=4
        )
        return
    text = None if number is None else f"{number}  {s.label}, {s.known.date()}"
    if s.series.endswith("_line_break"):
        axes.plot(xs[:2], ys[:2], color=colour, lw=1.6, marker="o", ms=4, zorder=4, label=text)
        axes.plot(xs[1:], ys[1:], color=colour, lw=1.2, ls="--", zorder=4)
        axes.plot(xs[-1:], ys[-1:], color=colour, marker="x", ms=8, mew=2, zorder=5)
    else:
        if s.series.startswith("hs_"):
            axes.plot(xs[1:4:2], ys[1:4:2], color=colour, lw=1.0, ls="--", zorder=4)
        if s.shape == "outline":
            xs, ys = [*xs, xs[0]], [*ys, ys[0]]
            axes.fill(xs, ys, color=colour, alpha=0.12, zorder=3)
        axes.plot(xs, ys, color=colour, lw=1.6, marker="o", ms=4, zorder=4, label=text)
    if number is not None:
        axes.annotate(
            str(number),
            (xs[-1], ys[-1]),
            xytext=(4, 5),
            textcoords="offset points",
            fontsize=9,
            fontweight="bold",
            color=colour,
            zorder=6,
        )


def _summary(shapes: list[_Shape], pattern: str, start: date, end: date) -> tuple[str, int]:
    n = len(shapes)
    head = f"Found {n} {pattern} event{'s' if n != 1 else ''} from {start} to {end}."
    if not n:
        return f"{head}\nNo event in this window.", 0
    last = max(shapes, key=lambda s: s.known)
    return f"{head}\nMost recent: {last.label}, known on {last.known.date()}.", n


def reaches_held_back(end: date) -> bool:
    """True when the picture's last day is inside the held-back period."""
    from alpha_cli.spine.reserve import CUTOFF_DAY

    return end > CUTOFF_DAY


def _figure(
    series: OHLCV, shapes: list[_Shape], pattern: str, window: tuple[date, date], annotated: bool
) -> Any:
    from alpha_cli.figures import plain_style as ps

    start, end = window
    drawn = [s for s in shapes if s.shape == "marker"]
    inside = [
        s for s in shapes if s.shape != "marker" and min(p[0] for p in s.points).date() >= start
    ]
    drawn += _spread(inside)
    drawn.sort(key=lambda x: x.known)
    sentences = [
        f"The blue line is the daily close of {series.symbol}; the grey band behind it is each "
        "day's low to high.",
        WHAT[pattern],
        "Markers sit on the bar's own high or low, but each pattern is known only on the later "
        "day in its note.",
        "A pattern is a reading about the past; it does not say what comes next.",
    ]
    if reaches_held_back(end):
        sentences.insert(-1, HELD_BACK_NOTE)
    if len(shapes) > len(drawn):
        sentences.insert(
            -1,
            f"Of {len(shapes)} found, {len(drawn)} recent ones that do not crowd are drawn.",
        )
    box = ps.box_height(sentences) if annotated else 0.0
    height = 6.0 + box
    figure = ps.new_figure(height)
    axes = figure.add_subplot(1, 1, 1)
    figure.subplots_adjust(top=0.84, bottom=(box + 0.9) / height, left=0.07, right=0.98)
    days = [_when(series, i) for i in range(len(series))]
    keep = [i for i, d in enumerate(days) if start <= d.date() <= end]
    x = [_num(days[i]) for i in keep]
    low = [float(series.low[i]) for i in keep]
    high = [float(series.high[i]) for i in keep]
    axes.fill_between(x, low, high, color="0.85", lw=0, label="Daily low to high", zorder=1)
    axes.plot(
        x, [float(series.close[i]) for i in keep], color="C0", lw=1.0, label="Close", zorder=2
    )
    lines = [s for s in drawn if s.shape != "marker"]
    for s in drawn:
        number = lines.index(s) + 1 if s in lines else None
        _draw_shape(axes, s, COLOURS[((number or 1) - 1) % len(COLOURS)], number)
    span = max(high) - min(low)
    axes.set_ylim(min(low) - 0.04 * span, max(high) + 0.04 * span + 0.05 * span * len(lines))
    axes.set_xlim(
        _num(datetime.combine(start, datetime.min.time(), UTC)),
        _num(datetime.combine(end, datetime.min.time(), UTC)) + 1.0,
    )
    axes.xaxis_date()
    axes.set_ylabel("Price (native quote)")
    axes.set_xlabel("Date (UTC)")
    axes.grid(True, color="0.88", lw=0.6)
    axes.legend(loc="upper left", fontsize=8.5)
    ps.title_block(
        axes, f"Price with {pattern} drawn", f"{series.symbol}  ·  {pattern}  ·  {start} to {end}"
    )
    if annotated:
        used: list[Any] = []
        noted = [s for s in drawn if s.shape == "marker"][-NOTES:] or drawn[-1:]
        for s in noted:
            px, py = s.points[-1]
            ps.callout(axes, f"{s.label}, known {s.known.date()}", (_num(px), py), used)
        ps.how_to_read(figure, sentences, 0.15)
    return figure


def _writer(data: bytes) -> Callable[[Path], object]:
    def write(path: Path) -> object:
        return path.write_bytes(data)

    return write


def draw_pattern_pictures(
    bars: list[Bar], pattern: str, *, since: date | None, out_dir: Path
) -> PatternPicture:
    """Write the plain and annotated pictures of `pattern` on `bars`; return where and what."""
    from alpha_cli._artifacts import publish_artifact
    from alpha_cli.chart_cmds import to_ohlcv
    from alpha_cli.figures.plain_style import to_bytes

    series = to_ohlcv(bars)
    end = _when(series, len(series) - 1).date()
    start = since or end - timedelta(days=DEFAULT_DAYS)
    if start > end:
        raise DataError(f"--since {start} is after the last bar {end}")
    shapes = [s for s in _shapes(series, pattern) if start <= s.known.date() <= end]
    summary, count = _summary(shapes, pattern, start, end)
    files = {}
    for kind, annotated in (("plain", False), ("annotated", True)):
        data = to_bytes(_figure(series, shapes, pattern, (start, end), annotated), "png")
        tag = hashlib.sha256(data).hexdigest()[:8]
        path = out_dir / f"{series.symbol}-{pattern}-{start}-{end}-{kind}-{tag}.png"
        publish_artifact(path, _writer(data))
        files[kind] = path
    if reaches_held_back(end):
        summary += f"\n{HELD_BACK_NOTE}"
    summary += f"\nPictures: {files['plain']} and {files['annotated']}"
    return PatternPicture(files["plain"], files["annotated"], count, start, end, summary)
