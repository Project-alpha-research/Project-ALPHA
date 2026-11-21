"""Render a FigureSpec in-process and measure matplotlib's own text artists."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from alpha_cli.figures.rdagent_journey_figures import figure_theme
from alpha_research.figures import FigureSpec, RenderOptions, default_size, render
from alpha_research.figures.render import render_figure


@dataclass
class Measured:
    """Text boxes in pixels, taken before the renderer clears the figure."""

    frame: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    texts: list[tuple[str, tuple[float, float, float, float]]] = field(default_factory=list)
    tick_runs: list[list[tuple[str, tuple[float, float, float, float]]]] = field(
        default_factory=list
    )
    ylabels: list[str] = field(default_factory=list)

    def outside(self) -> list[str]:
        x0, y0, x1, y1 = self.frame
        return [
            text
            for text, (a, b, c, d) in self.texts
            if a < x0 - 1 or b < y0 - 1 or c > x1 + 1 or d > y1 + 1
        ]

    def overlapping_ticks(self) -> list[str]:
        bad: list[str] = []
        for run in self.tick_runs:
            for (a, box_a), (b, box_b) in zip(run, run[1:], strict=False):
                if (
                    box_a[0] < box_b[2]
                    and box_b[0] < box_a[2]
                    and box_a[1] < box_b[3]
                    and box_b[1] < box_a[3]
                ):
                    bad.append(f"{a}|{b}")
        return bad


def _box(text: Any, renderer: Any) -> tuple[float, float, float, float]:
    extents = text.get_window_extent(renderer).extents
    return (float(extents[0]), float(extents[1]), float(extents[2]), float(extents[3]))


def measure(spec: FigureSpec, monkeypatch: pytest.MonkeyPatch, *, dark: bool = False) -> Measured:
    result = Measured()
    original = render._save

    def keep(figure: Any, options: Any, built: Any) -> bytes:
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        bounds = figure.bbox.bounds
        result.frame = (bounds[0], bounds[1], bounds[0] + bounds[2], bounds[1] + bounds[3])
        # Tick labels outside the view interval are never drawn; they are not text on the page.
        hidden: set[int] = set()
        for axes in figure.axes:
            if not axes.axison:  # a table panel switches its axis off: no labels are drawn
                hidden.update(id(a) for a in (axes.xaxis.label, axes.yaxis.label))
            for axis in (axes.xaxis, axes.yaxis):
                low, high = sorted(float(v) for v in axis.get_view_interval())
                for loc, label in zip(
                    axis.get_majorticklocs(), axis.get_majorticklabels(), strict=False
                ):
                    if not low - 1e-9 <= float(loc) <= high + 1e-9:
                        hidden.add(id(label))
        for text in figure.findobj(match=lambda a: hasattr(a, "get_text")):
            if id(text) in hidden:
                continue
            if text.get_visible() and text.get_text().strip():
                box = _box(text, renderer)
                if box[2] > box[0]:
                    result.texts.append((text.get_text()[:40], box))
        for axes in figure.axes:
            result.ylabels.append(axes.get_ylabel() if axes.axison else "")
            for axis in (axes.xaxis, axes.yaxis):
                run = [
                    (t.get_text(), _box(t, renderer))
                    for t in axis.get_ticklabels()
                    if t.get_visible() and t.get_text().strip()
                ]
                result.tick_runs.append(run)
        return original(figure, options, built)

    monkeypatch.setattr(render, "_save", keep)
    options = RenderOptions(
        theme=figure_theme(dark), size=default_size(spec.panel_count), fmt="png"
    )
    render_figure(spec, options)
    return result
