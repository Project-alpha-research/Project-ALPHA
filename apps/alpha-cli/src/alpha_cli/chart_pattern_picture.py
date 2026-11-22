"""The picture behind `alpha chart overlays -p <pattern>`: price with the pattern drawn on it.

Two PNG files in the product's figure style (white, standard matplotlib): a plain one and an
annotated one with notes and a "How to read this chart" box. Event families draw what
`pattern_events` finds, each event placed by the bar it became known. Families that draw levels
at the last bar (`VISIBLE_ONLY`) draw the rows `chart_cmds.pattern_annotations` makes. Display
only; no authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alpha_core import Bar, DataError

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from alpha_patterns import OHLCV

DEFAULT_DAYS = 730
NOTES = 3  # the most recent events that get a note in the annotated picture


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
        shapes.append(_Shape(row["label"], shape, points, known))
    return shapes


def _draw_shape(axes: Axes, s: _Shape, tag: dict[str, str]) -> None:
    xs = [p[0] for p in s.points]
    ys = [p[1] for p in s.points]
    if s.shape == "marker":
        axes.scatter(xs, ys, color="C1", s=22, zorder=4, **tag)
        return
    if s.shape == "outline":
        xs, ys = [*xs, xs[0]], [*ys, ys[0]]
    axes.plot(xs, ys, color="C1", lw=1.4, marker="o", ms=3, zorder=4, **tag)


def _summary(shapes: list[_Shape], pattern: str, start: date, end: date) -> tuple[str, int]:
    n = len(shapes)
    head = f"Found {n} {pattern} event{'s' if n != 1 else ''} from {start} to {end}."
    if not n:
        return f"{head}\nNo event in this window.", 0
    last = max(shapes, key=lambda s: s.known)
    return f"{head}\nMost recent: {last.label}, known on {last.known.date()}.", n


def _figure(
    series: OHLCV, shapes: list[_Shape], pattern: str, window: tuple[date, date], annotated: bool
) -> Any:
    import matplotlib.dates as mdates

    from alpha_cli.figures import plain_style as ps

    start, end = window
    sentences = [
        f"The line is the daily close of {series.symbol}.",
        "Orange marks and lines are the pattern, drawn on the bar where it could first be known.",
        "A pattern is a reading about the past; it does not say what comes next.",
    ]
    box = ps.box_height(sentences) if annotated else 0.0
    height = 6.0 + box
    figure = ps.new_figure(height)
    axes = figure.add_subplot(1, 1, 1)
    figure.subplots_adjust(top=0.84, bottom=(box + 0.9) / height, left=0.07, right=0.98)
    days = [_when(series, i) for i in range(len(series))]
    keep = [i for i, d in enumerate(days) if start <= d.date() <= end]
    axes.plot(
        [days[i] for i in keep],
        [float(series.close[i]) for i in keep],
        color="C0",
        lw=1.0,
        label="Close",
    )
    for n, s in enumerate(shapes):
        _draw_shape(axes, s, {"label": pattern} if n == 0 else {})
    axes.set_xlim(
        datetime.combine(start, datetime.min.time(), UTC),
        datetime.combine(end, datetime.min.time(), UTC) + timedelta(days=1),
    )
    axes.set_ylabel("Price (native quote)")
    axes.set_xlabel("Date (UTC)")
    axes.grid(True, color="0.88", lw=0.6)
    axes.legend(loc="upper left")
    ps.title_block(
        axes, f"Price with {pattern} drawn", f"{series.symbol}  ·  {pattern}  ·  {start} to {end}"
    )
    if annotated:
        used: list[Any] = []
        for s in sorted(shapes, key=lambda x: x.known)[-NOTES:]:
            x, y = s.points[-1]
            ps.callout(axes, f"{s.label}, known {s.known.date()}", (mdates.date2num(x), y), used)
        ps.how_to_read(figure, sentences, 0.15)
    return figure


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
        publish_artifact(path, lambda p, d=data: p.write_bytes(d))
        files[kind] = path
    summary += f"\nPictures: {files['plain']} and {files['annotated']}"
    return PatternPicture(files["plain"], files["annotated"], count, start, end, summary)
