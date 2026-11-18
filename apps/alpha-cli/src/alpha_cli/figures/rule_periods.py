"""Rule-test figures from the same dated samples as each row of headline facts."""

from __future__ import annotations

from dataclasses import replace
from itertools import accumulate
from typing import Any

from alpha_cli.figures import _sources as src
from alpha_cli.figures._builders import BuildContext, mult, pct
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


def definition(figure_id: str) -> FigureDefinition:
    if figure_id not in TRADABLE:
        return base_definition(figure_id)
    return replace(
        base_definition(figure_id.removeprefix("tradable_")),
        figure_id=figure_id,
        required_artifacts=(TRADABLE_FILE,),
        run_commands=("validate",),
    )


def build(ctx: BuildContext, figure_id: str, row: dict[str, Any]) -> FigureSpec:
    name = figure_id.removeprefix("tradable_")
    comparison = name == "equity_vs_passive"
    filename = definition(figure_id).required_artifacts[0]
    frame = src.require(ctx.rdir, filename, "ts")
    column = "equity" if filename == "equity_curve.parquet" else "strategy_equity"
    strategy = src.rebase(src.floats(frame[column], name=column))
    points = src.sample(len(strategy))
    basis = row["price_basis"]
    if comparison:
        passive = src.rebase(src.floats(frame["benchmark_equity"], name="benchmark_equity"))
        if min(passive) <= 0:
            raise DataError("buy-and-hold growth must be positive")
        lower = tuple(s / b - 1 for s, b in zip(strategy, passive, strict=True))
        reference, reference_label = passive, f"Buy and hold ({basis})"
        axis = "Ahead of / behind buy and hold (%)"
        lead = lower[-1]
        relation = "ahead of" if lead >= 0 else "behind"
        answer = (
            f"Strategy finished at {mult(strategy[-1])}. "
            f"Buy and hold finished at {mult(passive[-1])}. "
            f"The strategy finished {pct(abs(lead))} {relation} buy and hold."
            if lead
            else f"Strategy and buy and hold both finished at {mult(strategy[-1])}, level at 0.0%."
        )
        caveat = (
            f"Both lines use the same opens ({basis}). The lower panel divides "
            "strategy growth by buy-and-hold growth and subtracts one."
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
        (strategy, f"Strategy ({basis})", "subject"),
    )
    marks = []
    for values, label, role in series:
        marks.append(
            LineMark(
                x=ts,
                y=tuple(values[i] for i in points),
                role=role,
                label=label,
                end_label=ValueLabel(text=mult(values[-1])),
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
                panel_id="growth",
                y_label="Growth of 1",
                y_unit="multiple",
                marks=tuple(marks),
                height_ratio=2.2,
            ),
            Panel(
                panel_id="excess" if comparison else "underwater",
                y_label=axis,
                y_unit="percent",
                y_percent=True,
                y_zero_rule=True,
                legend=False,
                marks=tuple(lower_marks),
            ),
        ),
    )
    dates = f"{row['first_ts'][:10]} to {row['last_ts'][:10]}"
    return replace(
        spec,
        figure_id=figure_id,
        caveat=caveat,
        subtitle=f"{ctx.symbol} · {ctx.strategy} · {row['period']} · {dates}",
    )
