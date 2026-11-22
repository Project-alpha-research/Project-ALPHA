"""The one standard figure look, and the annotation primitives for the annotated variant.

A plain figure is what a quant draws in a research notebook: white face, matplotlib's own
default colour cycle, a light grid, a plain title, labelled axes and a legend. Nothing here
chooses a colour of its own except grey for reference marks. The annotated variant adds
callouts, labelled bands, a hatched held-back band and a "How to read this chart" box.

Display only: every number drawn here arrives from a stored run artefact.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING, Any, Final

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

FIGURE_WIDTH_IN: Final = 12.0
DPI: Final = 100
BOX: Final = {"boxstyle": "square", "fc": "white", "ec": "0.4", "lw": 0.8}
ARROW: Final = {"arrowstyle": "->", "color": "0.2", "lw": 1.0}
#: Named crisis windows drawn as labelled bands when they fall inside a time axis.
CRISES: Final = (
    ("2000-03-01", "2002-10-31", "2000-02 bust"),
    ("2007-10-01", "2009-03-31", "2008 crisis"),
    ("2020-02-01", "2020-04-30", "2020"),
)
#: Callout directions from the point, tried in this order: up-right, up-left, down-right, ...
DIRECTIONS: Final = ((1, 1), (-1, 1), (1, -1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1))
_OFFSET_PX: Final = 22.0  # how far a callout box sits from its point
_EDGE: Final = 0.01  # axes-fraction margin a box keeps from the frame
_WRAP: Final = 44
HOW_WIDTH: Final = 165


def pct(value: float, places: int = 1) -> str:
    return f"{value * 100:.{places}f}%"


def month(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m")


def new_figure(height_in: float) -> Figure:
    """A pyplot-free figure on matplotlib defaults: white face, default cycle and fonts."""
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(FIGURE_WIDTH_IN, height_in), dpi=DPI, facecolor="white")
    FigureCanvasAgg(figure)
    return figure


def to_bytes(figure: Figure, fmt: str) -> bytes:
    """Deterministic bytes: no date, no software stamp, a pinned SVG hash salt."""
    import matplotlib

    buffer = BytesIO()
    meta = {"Software": None} if fmt == "png" else {"Date": None}
    with matplotlib.rc_context({"svg.hashsalt": "alpha-figures", "svg.fonttype": "path"}):
        figure.savefig(buffer, format=fmt, dpi=DPI, metadata=meta, facecolor="white")
    figure.clear()
    return buffer.getvalue()


def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width))


def _coverage(axes: Axes, rect: tuple[float, float, float, float]) -> int:
    """How many plotted vertices fall inside a candidate box (axes-fraction coordinates)."""
    inverse = axes.transAxes.inverted()
    left, bottom, right, top = rect
    count = 0
    for line in axes.get_lines():
        data = np.asarray(line.get_xydata(), dtype=float)
        if len(data) == 0:
            continue
        points = inverse.transform(axes.transData.transform(data))
        inside = (
            (points[:, 0] >= left)
            & (points[:, 0] <= right)
            & (points[:, 1] >= bottom)
            & (points[:, 1] <= top)
        )
        count += int(inside.sum())
    for container in axes.containers:
        for patch in getattr(container, "patches", []):
            box = patch.get_window_extent()
            low = inverse.transform((box.x0, box.y0))
            high = inverse.transform((box.x1, box.y1))
            if low[0] < right and high[0] > left and low[1] < top and high[1] > bottom:
                count += 5
    return count


Rect = tuple[float, float, float, float]  # left, bottom, right, top in axes fractions


def _pad_px(fontsize: float) -> float:
    """Pixels the square box adds on each side of its text (0.3 of the font size, plus a line)."""
    return 0.3 * fontsize * DPI / 72 + 1


def _box_size(axes: Axes, body: str, fontsize: float) -> tuple[float, float]:
    """Width and height of a boxed note in axes fractions, measured with the real renderer."""
    probe = axes.text(0.0, 0.0, body, fontsize=fontsize, transform=axes.transAxes)
    extent = probe.get_window_extent()
    probe.remove()
    pad = 2 * _pad_px(fontsize)
    return (extent.width + pad) / axes.bbox.width, (extent.height + pad) / axes.bbox.height


def _overlap(a: Rect, b: Rect) -> float:
    across = min(a[2], b[2]) - max(a[0], b[0])
    up = min(a[3], b[3]) - max(a[1], b[1])
    return across * up if across > 0 and up > 0 else 0.0


def _crossings(point: tuple[float, float], rect: Rect, taken: list[Rect]) -> int:
    """How many sampled points of the arrow (point to box centre) fall inside a taken box."""
    centre = ((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)
    count = 0
    for step in range(1, 20):
        x = point[0] + (centre[0] - point[0]) * step / 20
        y = point[1] + (centre[1] - point[1]) * step / 20
        count += sum(o[0] <= x <= o[2] and o[1] <= y <= o[3] for o in taken)
    return count


def _legend_rect(axes: Axes) -> list[Rect]:
    legend = axes.get_legend()
    if legend is None:
        return []
    box = legend.get_window_extent()
    inverse = axes.transAxes.inverted()
    (left, bottom), (right, top) = inverse.transform([(box.x0, box.y0), (box.x1, box.y1)])
    return [(float(left), float(bottom), float(right), float(top))]


def _place(
    axes: Axes, point: tuple[float, float], size: tuple[float, float], taken: list[Rect]
) -> tuple[Rect, str, str]:
    """The box next to ``point`` (axes fractions) that stays inside, off other boxes and data."""
    width, height = size
    dx, dy = _OFFSET_PX / axes.bbox.width, _OFFSET_PX / axes.bbox.height
    options = []
    for order, (sx, sy) in enumerate(DIRECTIONS):
        x, y = point[0] + sx * dx, point[1] + sy * dy
        left = x if sx > 0 else x - width if sx < 0 else x - width / 2
        bottom = y if sy > 0 else y - height if sy < 0 else y - height / 2
        # Flip into the axes: a box that would leave the frame slides back inside.
        shift_x = max(_EDGE - left, 0.0) - max(left + width - (1 - _EDGE), 0.0)
        shift_y = max(_EDGE - bottom, 0.0) - max(bottom + height - (1 - _EDGE), 0.0)
        rect = (left + shift_x, bottom + shift_y, left + shift_x + width, bottom + shift_y + height)
        covers = point[0] >= rect[0] and point[0] <= rect[2] and point[1] >= rect[1]
        covers = covers and point[1] <= rect[3]
        clash = sum(_overlap(rect, other) for other in taken) + _crossings(point, rect, taken)
        cost = (covers, clash > 0, _coverage(axes, rect), abs(shift_x) + abs(shift_y), order)
        options.append((cost, rect))
    rect = min(options)[1]
    ha = "left" if rect[0] >= point[0] else "right" if rect[2] <= point[0] else "center"
    va = "bottom" if rect[1] >= point[1] else "top" if rect[3] <= point[1] else "center"
    return rect, ha, va


def callout(
    axes: Axes, text: str, xy: tuple[float, float], used: list[Rect], *, fontsize: float = 8.5
) -> None:
    """A boxed note a short way from ``xy`` (data coordinates), with a short arrow to it.

    The box stays inside the axes, off the legend, off the boxes in ``used`` and as far as it
    can off the plotted data; it never sits across the plot from its point.
    """
    body = wrap(text, _WRAP)
    point = axes.transAxes.inverted().transform(axes.transData.transform(xy))
    rect, ha, va = _place(
        axes,
        (float(point[0]), float(point[1])),
        _box_size(axes, body, fontsize),
        [*used, *_legend_rect(axes)],
    )
    used.append(rect)
    # The text is aligned inside the box edge, so the drawn box fills exactly ``rect``.
    pad_x, pad_y = _pad_px(fontsize) / axes.bbox.width, _pad_px(fontsize) / axes.bbox.height
    x = rect[0] + pad_x if ha == "left" else rect[2] - pad_x if ha == "right" else 0.0
    y = rect[1] + pad_y if va == "bottom" else rect[3] - pad_y if va == "top" else 0.0
    x = x if ha != "center" else (rect[0] + rect[2]) / 2
    y = y if va != "center" else (rect[1] + rect[3]) / 2
    axes.annotate(
        body,
        xy=xy,
        xycoords="data",
        xytext=(x, y),
        textcoords="axes fraction",
        fontsize=fontsize,
        ha=ha,
        va=va,
        bbox=BOX,
        arrowprops=ARROW,
        zorder=10,
        annotation_clip=False,
    )


def band(
    axes: Axes, x0: float, x1: float, label: str, *, alpha: float = 0.15, y: float = 0.985
) -> Rect:
    """A labelled shaded span over the full axes height (data x coordinates).

    Returns where the label sits (axes fractions), so a callout can keep off it.
    """
    axes.axvspan(
        x0,
        x1,
        facecolor="0.5",
        alpha=alpha,
        lw=0,
    )
    # A span that starts before the view is labelled at the view's left edge, never off it.
    text = axes.text(
        max(x0, min(axes.get_xlim())),
        y,
        " " + label,
        transform=axes.get_xaxis_transform(),
        ha="left",
        va="top",
        fontsize=8,
        color="0.25",
        clip_on=True,
        bbox={"fc": "white", "ec": "none", "alpha": 0.8, "pad": 1.0},
    )
    box = text.get_window_extent()
    (left, bottom), (right, top) = axes.transAxes.inverted().transform(
        [(box.x0, box.y0), (box.x1, box.y1)]
    )
    return (float(left), float(bottom), float(right), float(top))


def held_back_band(axes: Axes, start: float, end: float) -> None:
    """The hatched band for data the run never used: the reserved period."""
    axes.axvspan(start, end, facecolor="none", hatch="///", edgecolor="0.6", lw=0)
    label = axes.text(
        (start + end) / 2,
        0.5,
        "held back, not used",
        transform=axes.get_xaxis_transform(),
        rotation=90,
        ha="center",
        va="center",
        fontsize=9,
        color="0.25",
        bbox={"fc": "white", "ec": "none", "alpha": 0.85},
    )
    # A short panel cannot hold the words in one column: break them, then shrink them to fit.
    for text, size in (("held back,\nnot used", 9.0), ("held back,\nnot used", 7.0)):
        if label.get_window_extent().height <= 0.9 * axes.bbox.height:
            break
        label.set_text(text)
        label.set_fontsize(size)


def box_height(sentences: list[str], width_chars: int = HOW_WIDTH) -> float:
    """Inches the "How to read this chart" box needs for these sentences."""
    lines = wrap(" ".join(sentences), width_chars).count("\n") + 1
    return 0.6 + 0.19 * lines


def how_to_read(
    figure: Figure, sentences: list[str], bottom_in: float, width_chars: int = HOW_WIDTH
) -> None:
    """Draw the explanation box with its lower edge ``bottom_in`` above the figure foot."""
    body = wrap(" ".join(sentences), width_chars)
    total = figure.get_figheight()
    figure.text(
        0.01,
        bottom_in / total,
        "How to read this chart\n" + body,
        fontsize=9,
        ha="left",
        va="bottom",
        linespacing=1.35,
        bbox={"fc": "0.97", "ec": "0.6", "lw": 0.8, "boxstyle": "square,pad=0.5"},
    )


def title_block(axes: Axes, title: str, subtitle: str) -> None:
    """The sample's heading: "SPY idea-name: Chart title" large, the rest of the line in grey.

    A subtitle reads "symbol  ·  idea  ·  dates ..."; the symbol and idea move into the title.
    """
    parts = subtitle.split("  ·  ") if subtitle else []
    if len(parts) >= 2 and parts[0] != "-":
        title, parts = f"{parts[0]} {parts[1]}: {title}", parts[2:]
    rest = wrap("  ·  ".join(parts), 130)
    lines = rest.count("\n") + 1 if rest else 0
    axes.set_title(title, loc="left", fontsize=13, pad=8 + 15 * lines)
    if rest:
        axes.text(0, 1.012, rest, transform=axes.transAxes, fontsize=10, color="0.3", va="bottom")


def hide_alternate_ticks(axes: Axes, which: str = "x", limit: int = 14) -> None:
    """Thin crowded category labels so no two tick labels overlap."""
    labels: list[Any] = axes.get_xticklabels() if which == "x" else axes.get_yticklabels()
    step = max(1, -(-len(labels) // limit))
    for index, label in enumerate(labels):
        label.set_visible(index % step == 0)
