"""Pure deterministic drawing of already bounded setup panels."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from alpha_research.figures.theme import Theme


@dataclass(frozen=True)
class Panel:
    title: str
    mode: str
    candles: tuple[tuple[int, float, float, float, float], ...]
    event_x: int
    trigger_x: int | None
    entry_x: int | None
    entry_price: float | None
    references: tuple[tuple[str, float], ...]


def _draw(axes: Any, panel: Panel, theme: Theme) -> None:
    from matplotlib.patches import Rectangle

    for x, opened, high, low, close in panel.candles:
        colour = (
            theme.substrate
            if panel.mode == "rejected"
            else (theme.up if close >= opened else theme.down)
        )
        axes.vlines(x, low, high, color=colour, linewidth=0.8)
        axes.add_patch(
            Rectangle(
                (x - 0.3, min(opened, close)),
                0.6,
                abs(close - opened),
                facecolor=colour,
                edgecolor=colour,
                linewidth=0.8,
            )
        )
        if close == opened:
            axes.hlines(close, x - 0.3, x + 0.3, color=colour, linewidth=0.8)
    axes.axvline(panel.event_x, color=theme.muted, linestyle="--", linewidth=0.8)
    if panel.trigger_x is not None and panel.trigger_x != panel.event_x:
        axes.axvline(panel.trigger_x, color=theme.accent, linewidth=0.8)
    if panel.entry_price is not None:
        axes.scatter([panel.entry_x], [panel.entry_price], marker="^", color=theme.gold, s=32)
    # Levels of a double bottom sit close together: the lowest is labelled below its line and
    # the others above, at the left edge, so labels neither collide nor cover the event bars.
    ordered = sorted(panel.references, key=lambda item: (item[1], item[0]))
    for index, (name, value) in enumerate(ordered):
        axes.axhline(value, color=theme.ink_dim, linestyle="--", linewidth=0.7)
        axes.text(
            0.02,
            value,
            f"{name}={value:.2f}",
            transform=axes.get_yaxis_transform(),
            ha="left",
            va="top" if index == 0 and len(ordered) > 1 else "bottom",
            fontsize=7,
            color=theme.ink_dim,
            bbox={"facecolor": theme.panel, "edgecolor": "none", "alpha": 0.8, "pad": 1.0},
        )
    axes.set_title(panel.title, fontsize=8, color=theme.ink, loc="left")
    left = panel.candles[0][0]
    right = panel.entry_x if panel.entry_x is not None else panel.candles[-1][0]
    axes.set_xlim(left - 1, right + 1)
    axes.set_ymargin(0.12)  # room for a level label drawn below the lowest line
    # Ticks every ten days back from the event, plus the first bar unless it would crowd one.
    ticks = set(range(0, left - 1, -10))
    if all(abs(left - tick) > 3 for tick in ticks):
        ticks.add(left)
    axes.set_xticks(sorted(ticks))
    axes.grid(color=theme.grid, linewidth=0.4)
    axes.set_axisbelow(True)


def _key(panels: list[Panel]) -> str:
    if any(panel.mode == "accepted" for panel in panels):
        return (
            "x axis: trading days from the event (0, dashed line). Solid line: trigger day.\n"
            "Gold triangle: entry at the next day's open. Dashed levels: reference prices."
        )
    return (
        "Grey candles: rejected; the reason follows the date.\n"
        "Each panel ends where that decision was made. x axis: days from the event (0)."
    )


def draw_sheet(panels: list[Panel], *, title: str, footer: str, theme: Theme) -> bytes:
    """Render at most sixteen bounded panels, independent of live matplotlib settings."""
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import font_manager, rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    if len(panels) > 16:
        raise ValueError("a contact sheet holds at most 16 panels")
    font_manager.findfont("DejaVu Sans", fallback_to_default=False)
    style: dict[Any, Any] = {
        **dict(matplotlib.rcParamsDefault.items()),
        "font.family": "DejaVu Sans",
        "figure.facecolor": theme.bg,
        "axes.facecolor": theme.panel,
        "axes.edgecolor": theme.grid,
        "text.color": theme.ink,
        "xtick.color": theme.ink,
        "ytick.color": theme.ink,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
    }
    with rc_context(style):
        figure = Figure(figsize=(16, 12), dpi=100)
        FigureCanvasAgg(figure)
        for index, panel in enumerate(panels):
            _draw(figure.add_subplot(4, 4, index + 1), panel, theme)
        figure.subplots_adjust(
            left=0.05, right=0.98, top=0.93, bottom=0.07, wspace=0.30, hspace=0.40
        )
        figure.text(0.05, 0.97, title, fontsize=14, va="top")
        figure.text(0.98, 0.012, _key(panels), fontsize=9, va="bottom", ha="right")
        figure.text(0.05, 0.025, footer, fontsize=9)
        buffer = BytesIO()
        figure.savefig(buffer, format="png", dpi=100, metadata={"Software": None})
        figure.clear()
        return buffer.getvalue()
