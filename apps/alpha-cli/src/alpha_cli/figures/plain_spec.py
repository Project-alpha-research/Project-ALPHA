"""Lay a ``FigureSpec`` out as a notebook figure, plain or annotated.

Both variants draw the same marks on the same axes. The annotated variant adds callouts,
labelled bands and a "How to read this chart" box from ``spec_facts``; it never changes a
plotted value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.figures import plain_marks as pm
from alpha_cli.figures import plain_style as ps
from alpha_cli.figures.spec_facts import (
    Call,
    Plan,
    figure_bands,
    held_back_span,
    panel_plan,
    time_extent,
)
from alpha_research.figures.spec import (
    BandMark,
    BarMark,
    CandleMark,
    ErrorBarMark,
    FigureSpec,
    HeatmapMark,
    HistogramMark,
    LineMark,
    Mark,
    Panel,
    RuleMark,
    ScatterMark,
    TableMark,
    ZoneMark,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

_SOLO = (LineMark, BandMark, ScatterMark, RuleMark, ZoneMark, CandleMark, BarMark, HistogramMark)


def _draw_mark(
    axes: Axes, figure: Figure, spec: FigureSpec, panel: Panel, mark: Mark, index: int
) -> None:
    kind = spec.x_kind
    if isinstance(mark, LineMark):
        pm.draw_line(axes, mark, kind, index)
    elif isinstance(mark, BandMark):
        pm.draw_band(axes, mark, kind, index)
    elif isinstance(mark, CandleMark):
        pm.draw_candle(axes, mark, kind)
    elif isinstance(mark, ScatterMark):
        pm.draw_scatter(axes, mark, kind, index)
    elif isinstance(mark, BarMark):
        pm.draw_bar(axes, mark, kind, index)
    elif isinstance(mark, HistogramMark):
        # Parts of one set of bars (same edges, one colour family) stack instead of overlapping.
        below = [
            m
            for m in panel.marks[:index]
            if isinstance(m, HistogramMark)
            and m.edges == mark.edges
            and mark.role == m.role == "categorical"
            and m.palette_index == mark.palette_index
        ]
        bottom = [sum(values) for values in zip(*(m.counts for m in below), strict=True)]
        pm.draw_histogram(axes, mark, index, bottom if below else 0.0)
    elif isinstance(mark, HeatmapMark):
        pm.draw_heatmap(axes, figure, mark)
    elif isinstance(mark, ZoneMark):
        pm.draw_zone(axes, mark, kind, index)
    elif isinstance(mark, RuleMark):
        pm.draw_rule(axes, mark, kind)
    elif isinstance(mark, ErrorBarMark):
        pm.draw_errorbar(axes, mark)
    elif isinstance(mark, TableMark):
        pm.draw_table(axes, mark)


def _thin(axes: Axes, which: str, limit: int) -> None:
    ps.hide_alternate_ticks(axes, which, limit)


def _style_axes(axes: Axes, spec: FigureSpec, panel: Panel, last: bool, drawn: bool) -> None:
    from matplotlib.ticker import PercentFormatter

    heat = any(isinstance(m, HeatmapMark | TableMark) for m in panel.marks)
    if panel.y_scale != "linear":
        from matplotlib.ticker import FuncFormatter

        axes.set_yscale(panel.y_scale)
        plain = FuncFormatter(lambda value, _: f"{value:,.10g}")  # 400, not 4 x 10^2
        axes.yaxis.set_major_formatter(plain)
        axes.yaxis.set_minor_formatter(plain)
    if panel.y_limits is not None:
        axes.set_ylim(*panel.y_limits)
    else:
        stacks: dict[tuple[float, ...], list[float]] = {}
        for m in panel.marks:
            if isinstance(m, HistogramMark):
                base = stacks.setdefault(m.edges, [0.0] * len(m.counts))
                stacks[m.edges] = [a + b for a, b in zip(base, m.counts, strict=True)]
        counts = [c for column in stacks.values() for c in column]
        if counts and max(counts) > 0:
            # Head room over the tallest bar, as in the sample, so a note fits above it.
            log = panel.y_scale == "log"
            axes.set_ylim(0.5 if log else 0, max(counts) * (3.0 if log else 1.18))
    if panel.y_percent:
        # Enough decimals for every tick: a 2.5% tick never reads "2%".
        axes.yaxis.set_major_formatter(PercentFormatter(xmax=1.0))
    if panel.y_zero_rule:
        axes.axhline(0.0, color="black", linewidth=0.8)
    if not heat:
        axes.grid(True, alpha=0.3)
    table = any(isinstance(m, TableMark) for m in panel.marks)
    if not table and not any(isinstance(m, ErrorBarMark) for m in panel.marks):
        axes.set_ylabel(ps.wrap(panel.y_label, 26) if not heat else panel.y_label)
    if panel.note is not None:
        axes.text(
            0.01,
            0.03,
            ps.wrap(panel.note, 60),
            transform=axes.transAxes,
            fontsize=8,
            va="bottom",
            bbox={"fc": "white", "ec": "0.6"},
        )
    if panel.legend and panel.legend_entries and drawn:
        # Where the data leave the most room, as matplotlib's own "best" placement finds it.
        axes.legend(loc="best", fontsize=8, ncol=min(len(panel.legend_entries), 3))
    if last and not table:
        axes.set_xlabel(spec.x_label)


def plt_align(axes: Axes) -> None:
    for label in axes.get_xticklabels():
        label.set_horizontalalignment("right")


def _share_x(spec: FigureSpec) -> bool:
    """Time panels share one horizontal scale; heatmaps, tables and forests stay independent."""
    kinds = (HeatmapMark, TableMark, ErrorBarMark)
    solo = any(isinstance(m, kinds) for panel in spec.panels for m in panel.marks)
    return spec.x_kind == "time" and not solo and len(spec.panels) > 1


def _x_axis(axes_list: list[Axes], spec: FigureSpec) -> None:
    if spec.x_kind == "time":
        import matplotlib.dates as dates

        mdates: Any = dates

        for axes in axes_list:
            locator = mdates.AutoDateLocator(minticks=3, maxticks=8)
            if not axes.images and axes.get_xlim()[1] > 1000:
                axes.xaxis.set_major_locator(locator)
                axes.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    elif spec.x_kind == "category":
        for axes in axes_list:
            if axes.get_xlabel() or axes is axes_list[-1]:
                axes.set_xticks(range(len(spec.x_categories)), labels=list(spec.x_categories))
                if len(spec.x_categories) > 8 and not axes.images:
                    axes.tick_params(axis="x", labelrotation=45)
                    axes.tick_params(axis="x", labelrotation=45)
                    plt_align(axes)
                _thin(axes, "x", 16)
    for axes in axes_list:
        if axes.images:
            # Every heatmap row has its own height (``_heat_rows``), so each keeps its label.
            _thin(axes, "x", 16)


def _outline_cells(axes: Axes, plan: Plan, mark: HeatmapMark | None) -> None:
    """Heatmaps: outline the highest cell green and the lowest red; the notes sit to the right.

    A row that is a named crisis year gets a dashed outline, as in the approved sample.
    Extra calls (a count of zero cells) become notes without an outline.
    """
    from matplotlib.patches import Rectangle

    columns = len(mark.columns) if mark is not None else 1
    rows = list(mark.rows) if mark is not None else []
    # The row of the year a crisis is named after (the sample dashes 2000, 2008 and 2020).
    crises = [(rows.index(label[:4]), label) for _, _, label in ps.CRISES if label[:4] in rows]
    for k, _ in crises:
        axes.add_patch(
            Rectangle((-0.5, k - 0.5), columns, 1, fill=False, ec="0.2", lw=1.2, ls="--")
        )
    notes = [
        (call, colour)
        for call, colour in zip(plan.calls, ("darkgreen", "darkred", None), strict=False)
    ]
    if crises:
        named = "; ".join(f"{rows[k]} ({label})" for k, label in crises)
        notes.append((Call(ps.wrap(f"Dashed rows: {named}", 30), 0.0, 0.0), None))
    top = 0.985
    for call, colour in notes:
        if colour is not None:
            corner = (call.x - 0.5, call.y - 0.5)
            axes.add_patch(Rectangle(corner, 1, 1, fill=False, ec=colour, lw=2.5))
        note = axes.text(
            1.02, top, call.text, transform=axes.transAxes, fontsize=9, va="top", bbox=ps.BOX
        )
        top -= (note.get_window_extent().height + 14) / axes.bbox.height


def _annotate(figure: Figure, spec: FigureSpec, axes_list: list[Axes]) -> None:
    held = held_back_span(spec)
    extent = time_extent(spec)
    for number, (axes, panel) in enumerate(zip(axes_list, spec.panels, strict=True)):
        plan = panel_plan(spec, panel)
        used: list[ps.Rect] = []
        flat = axes.images or any(isinstance(m, TableMark) for m in panel.marks)
        if held is not None and not flat:
            left = float(pm.x_values((extent[0] if extent else 0.0,), "time")[0])
            lo, hi = (float(v) for v in pm.x_values(held, "time"))
            axes.set_xlim(left, hi)
            ps.held_back_band(axes, lo, hi)
            # No callout covers the held-back band.
            start = axes.transAxes.inverted().transform(axes.transData.transform((lo, 0.0)))[0]
            used.append((float(start), 0.0, 1.0, 1.0))
        if number == 0 and extent is not None:
            for a, b, label in figure_bands(spec):
                lo, hi = (float(v) for v in pm.x_values((a, b), "time"))
                used.append(ps.band(axes, lo, hi, label, y=0.93))
        for a, b, label in plan.bands:
            lo, hi = (float(v) for v in pm.x_values((a, b), spec.x_kind))
            used.append(ps.band(axes, lo, hi, label, y=0.86))
        axes.get_xlim()
        axes.get_ylim()
        if axes.images:
            heat = [m for m in panel.marks if isinstance(m, HeatmapMark)]
            _outline_cells(axes, plan, heat[0] if heat else None)
            continue
        tables = [m for m in panel.marks if isinstance(m, TableMark)]
        if tables:
            axes.annotate(
                f"stored evidence table: {len(tables[0].rows)} rows",
                xy=(0.99, 0.98),
                xycoords="axes fraction",
                ha="right",
                va="top",
                fontsize=8,
                color="0.25",
            )
            continue
        for call in plan.calls[:3]:
            xy = (float(pm.x_values((call.x,), spec.x_kind)[0]), call.y)
            ps.callout(axes, call.text, xy, used)


def _height_ratio(panel: Panel) -> float:
    """A table panel is as tall as its rows (0.26 inch each), never a block of white space."""
    rows = [len(m.rows) for m in panel.marks if isinstance(m, TableMark)]
    if not rows:
        return panel.height_ratio
    return min(panel.height_ratio, 0.26 * (max(rows) + 1.5) / 2.6)


def _heat_rows(spec: FigureSpec) -> int:
    return sum(
        len(mark.rows)
        for panel in spec.panels
        for mark in panel.marks
        if isinstance(mark, HeatmapMark)
    )


def draw_spec(spec: FigureSpec, variant: str, sentences: list[str]) -> Figure:
    """Draw one variant; ``sentences`` fill the annotated box and are ignored when plain."""
    annotated = variant == "annotated"
    ratios = [_height_ratio(panel) for panel in spec.panels]
    # A heatmap grows a row at a time, so every row keeps its label and its cell numbers.
    body = max(5.2, 2.6 * sum(ratios), 0.3 * _heat_rows(spec) + 1.6)
    # Under the plot: tick labels and the axis title (0.6 inch), then the reading box.
    foot = 0.45 + (ps.box_height(sentences) + 0.1 if annotated else 0.0)
    top = 0.95
    shared = _share_x(spec)
    figure = ps.new_figure(top + body + foot + 0.6)
    total = figure.get_figheight()
    grid = figure.add_gridspec(
        len(spec.panels),
        1,
        height_ratios=ratios,
        # Panels that share the date axis sit close; independent panels keep their own labels.
        hspace=0.12 if shared else 0.3,
        left=0.11,
        # An annotated heatmap keeps its notes in a column to the right of the cells.
        right=0.78 if annotated and _heat_rows(spec) else 0.96,
        top=1 - top / total,
        bottom=(foot + 0.6) / total,
    )
    axes_list: list[Axes] = []
    for number, panel in enumerate(spec.panels):
        axes = figure.add_subplot(
            grid[number], sharex=axes_list[0] if shared and axes_list else None
        )
        drawn = False
        for index, mark in enumerate(panel.marks):
            _draw_mark(axes, figure, spec, panel, mark, index)
            drawn = drawn or mark.label is not None
        _style_axes(axes, spec, panel, number == len(spec.panels) - 1, drawn)
        axes_list.append(axes)
    if shared:
        for axes in axes_list[:-1]:
            axes.tick_params(labelbottom=False)
    _x_axis(axes_list, spec)
    if spec.x_limits is not None and spec.x_kind != "category":
        low, high = (float(v) for v in pm.x_values(spec.x_limits, spec.x_kind))
        for axes in axes_list:
            axes.set_xlim(low, high)
    ps.title_block(axes_list[0], spec.title, spec.subtitle)
    note = f" · {spec.truncation_note}" if spec.truncation_note else ""
    figure.text(0.01, 0.12 / total, ps.wrap(spec.caption + note, 170), fontsize=7, color="0.4")
    if annotated:
        _annotate(figure, spec, axes_list)
        ps.how_to_read(figure, sentences, 0.45)
    return figure
