"""Rule-test figures from the same dated samples as each row of headline facts."""

from __future__ import annotations

from dataclasses import replace
from itertools import accumulate
from typing import Any

from alpha_cli.figures import _sources as src
from alpha_cli.figures._common import BuildContext, mult, pct
from alpha_core import DataError
from alpha_research.figures import (
    FigureDefinition,
    FigureSpec,
    LineMark,
    Mark,
    Panel,
    RuleMark,
    ValueLabel,
)
from alpha_research.figures import figure_definition as base_definition
from alpha_research.figures.spec import Role

CHARTS = ("equity_underwater", "equity_vs_passive")
TRADABLE = tuple("tradable_" + name for name in CHARTS)
TRADABLE_FILE = "tradable_comparison.parquet"
# Plain names for the subtitle; the stored period ids stay machine-readable.
PERIOD_WORDS = {
    "full_history": "full history",
    "tradable": "could trade",
    "scored": "scored test periods only",
}


def definition(figure_id: str) -> FigureDefinition:
    if figure_id not in TRADABLE:
        return base_definition(figure_id)
    return replace(
        base_definition(figure_id.removeprefix("tradable_")),
        figure_id=figure_id,
        required_artifacts=(TRADABLE_FILE,),
        run_commands=("validate",),
    )


def _passive(frame: Any) -> tuple[float, ...]:
    if "available" in frame.columns and not all(frame["available"].to_list()):
        reasons = frame["unavailable_reason"].to_list() if "unavailable_reason" in frame else []
        reason = next((r for r in reasons if r), "benchmark_unavailable")
        raise DataError(f"no passive benchmark for this run ({reason})")
    raw = src.optional_floats(frame["benchmark_equity"])
    if any(value is None for value in raw):
        raise DataError("passive benchmark has gaps; refusing to interpolate a comparison")
    passive = src.rebase(tuple(float(value) for value in raw if value is not None))
    if min(passive) <= 0:
        raise DataError("passive benchmark falls at or below zero; the growth ratio is undefined")
    return passive


def _legacy_basis(frame: Any) -> str:
    """Runs without period records state only what their stored buy-and-hold kind says."""
    kinds = set(frame["benchmark_kind"].to_list()) if "benchmark_kind" in frame.columns else set()
    return "with dividends" if kinds == {"passive_open_to_open_with_dividends"} else "price only"


def _padded_limits(values: tuple[float, ...]) -> tuple[float, float]:
    """Room above and below the line so its end label never sits on the frame."""
    low, high = min(0.0, *values), max(0.0, *values)
    pad = 0.14 * ((high - low) or 0.01)
    return low - pad, high + pad


def _plotted_subtitle(ctx: BuildContext, frame: Any) -> str:
    """Name the dates actually drawn; a run's stored window can be wider than its curve."""
    first, last = frame["ts"][0].date().isoformat(), frame["ts"][-1].date().isoformat()
    parts = [ctx.symbol, ctx.strategy, f"plotted {first} to {last}"]
    start, end = ctx.field("start", "first_ts"), ctx.field("end", "last_ts")
    if isinstance(start, str) and isinstance(end, str) and (start[:10], end[:10]) != (first, last):
        parts.append(
            f"run data {start[:10]} to {end[:10]}; the plotted curve covers part of that window"
        )
    return "  ·  ".join(parts)


def build(ctx: BuildContext, figure_id: str, row: dict[str, Any] | None) -> FigureSpec:
    """Both charts for one dated row; ``row`` is None for runs that predate period records.

    Every label is computed on the full series; only the plotted points are sampled.
    """
    name = figure_id.removeprefix("tradable_")
    comparison = name == "equity_vs_passive"
    filename = definition(figure_id).required_artifacts[0]
    frame = src.require(ctx.rdir, filename, "ts")
    column = "equity" if filename == "equity_curve.parquet" else "strategy_equity"
    strategy = src.rebase(src.floats(frame[column], name=column))
    points = src.sample(len(strategy))
    basis = row["price_basis"] if row else None
    subject_label = f"Strategy ({basis})" if basis else "Strategy"
    if comparison:
        passive = _passive(frame)
        basis = basis or _legacy_basis(frame)
        lower = tuple(s / b - 1 for s, b in zip(strategy, passive, strict=True))
        reference, reference_label = passive, f"Buy and hold ({basis})"
        # One short line: a two-line label is wider than the left margin and is clipped.
        axis = "Ahead (%)"
        lead = lower[-1]
        relation = "ahead of" if lead >= 0 else "behind"
        answer = (
            f"Strategy finished at {mult(strategy[-1])}. "
            f"Buy and hold finished at {mult(passive[-1])}. "
            f"The strategy finished {pct(abs(lead))} {relation} buy and hold."
            if lead
            else f"Strategy and buy and hold both finished at {mult(strategy[-1])}, level at 0.0%."
        )
        same = (
            f"Both lines use the same opening prices and dividend rule ({basis}). Rule tests "
            "add dividends when the store holds them. "
            if row
            else f"Buy and hold is the stored {basis} line. Backtest and validate runs use the "
            "engine's built-in buy-and-hold, which never adds dividends, so the same asset can "
            "read price only here and with dividends in a rule test. "
        )
        caveat = (
            same + "The strategy pays recorded fees and slippage; buy and hold pays none. "
            "The lower panel (Ahead) divides strategy growth by buy-and-hold growth and "
            "subtracts one: above zero is ahead, below zero is behind."
        )
    else:
        reference = tuple(accumulate(strategy, max))
        lower = src.drawdown(strategy)
        # Preserve the actual peak and trough when the display sample is bounded.
        trough = lower.index(min(lower))
        peak = strategy.index(reference[trough])
        points = sorted({*points, trough, peak})
        reference_label = "Running peak"
        axis = "Drawdown (%)"
        answer = (
            f"Capital ended at {mult(strategy[-1])} of its start. The worst drawdown was "
            f"{pct(lower[trough])} on {frame['ts'][trough].date().isoformat()}."
        )
        caveat = "The strategy includes recorded fees and slippage."
    ts = src.epochs(frame[points]["ts"])
    series: tuple[tuple[tuple[float, ...], str, Role], ...] = (
        (reference, reference_label, "substrate"),
        (strategy, subject_label, "subject"),
    )
    marks = []
    for values, label, role in series:
        marks.append(
            LineMark(
                x=ts,
                y=tuple(values[i] for i in points),
                role=role,
                label=label,
                # Only the strategy is labelled: two close end values would overprint.
                end_label=ValueLabel(text=mult(values[-1])) if role == "subject" else None,
            )
        )
    lower_marks: list[Mark] = [
        LineMark(
            x=ts,
            y=tuple(lower[i] for i in points),
            role="feature" if lower[-1] > 0 else "down",
            fill_to=0,
            end_label=ValueLabel(text=pct(lower[-1])) if comparison else None,
        )
    ]
    if not comparison:
        worst = min(lower)
        lower_marks.append(
            RuleMark(
                orientation="horizontal",
                position=worst,
                role="feature",
                annotate=ValueLabel(text=f"worst {pct(worst)}", ha="right", dx_pt=-6),
            )
        )
    spec = ctx.spec(
        name,
        x_label="Date (UTC)",
        artifacts=(filename,),
        answer=answer,
        truncation=f"Showing {len(points):,} of {len(strategy):,} sessions"
        if len(points) < len(strategy)
        else None,
        panels=(
            Panel(
                panel_id="growth" if comparison else "equity",
                y_label="Growth of 1 (x initial)",
                y_unit="multiple",
                marks=tuple(marks),
                height_ratio=2.2 if comparison else 2.6,
            ),
            Panel(
                panel_id="excess" if comparison else "underwater",
                y_label=axis,
                y_unit="percent",
                y_percent=True,
                y_zero_rule=True,
                y_limits=_padded_limits(lower),
                legend=False,
                marks=tuple(lower_marks),
            ),
        ),
    )
    if row is None:
        return replace(spec, caveat=caveat, subtitle=_plotted_subtitle(ctx, frame))
    period = PERIOD_WORDS.get(row["period"], row["period"])
    dates = f"{row['first_ts'][:10]} to {row['last_ts'][:10]}"
    return replace(
        spec,
        figure_id=figure_id,
        caveat=caveat,
        subtitle="  ·  ".join((ctx.symbol, ctx.strategy, period, dates)),
    )
