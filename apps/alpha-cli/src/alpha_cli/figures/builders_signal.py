"""Figure builders: signal."""

from __future__ import annotations

from alpha_cli.figures import _sources as src
from alpha_cli.figures._common import BuildContext, _truncation
from alpha_core import DataError
from alpha_research.figures import (
    CandleMark,
    FigureSpec,
    LineMark,
    Mark,
    Panel,
    ScatterMark,
    ValueLabel,
    ZoneMark,
)


# --------------------------------------------------------------------------- signals
def price_signal(ctx: BuildContext) -> FigureSpec:
    keys = ("symbol", "snapshot_id", "start", "end", "timeframe", "source_timeframe", "session")
    rows, reason = src.bars({key: ctx.field(key) for key in keys}, data_dir=ctx.data_dir)
    if reason is not None or not rows:
        raise DataError(f"price bars unavailable for this run ({reason or 'no bars'})")
    ts = tuple(row["t"] for row in rows)
    marks: list[Mark] = [
        CandleMark(
            x=ts,
            open=tuple(row["o"] for row in rows),
            high=tuple(row["h"] for row in rows),
            low=tuple(row["l"] for row in rows),
            close=tuple(row["c"] for row in rows),
            alpha=0.85,
        )
        if len(rows) <= 400
        else LineMark(
            x=ts, y=tuple(row["c"] for row in rows), role="substrate", label="Close", width=1.0
        )
    ]

    annotations = src.frame(ctx.rdir, "chart_annotations.parquet", "annotation_id", "anchor_index")
    drawn, total = 0, 0
    if annotations is not None and not annotations.is_empty():
        groups = annotations.partition_by("annotation_id", maintain_order=True)
        total = len(groups)
        for group in groups[:40]:
            label = str(group["label"].to_list()[0])
            kind = str(group["kind"].to_list()[0])
            unit = str(group["unit"].to_list()[0])
            xs = src.epochs(group["ts"])
            ys = src.floats(group["value"], name="annotation value")
            if kind == "zone":
                marks.append(
                    ZoneMark(
                        x0=min(xs),
                        x1=max(xs),
                        role="feature",
                        alpha=0.12,
                        label=label if drawn == 0 else None,
                        corner_label=ValueLabel(text=label),
                    )
                )
            else:
                marks.append(
                    LineMark(
                        x=xs,
                        y=ys,
                        role="feature",
                        label=label if drawn == 0 else None,
                        end_label=ValueLabel(text=f"{label} {ys[-1]:.2f}{'' if unit else ''}"),
                    )
                )
            drawn += 1

    trace = src.frame(ctx.rdir, "execution_trace.parquet", "sequence_id")
    if trace is not None and not trace.is_empty():
        fills = trace.filter(trace["event_type"] == "fill")
        if not fills.is_empty():
            buys = fills.filter(fills["side"] == "BUY")
            sells = fills.filter(fills["side"] == "SELL")
            for subset, marker, role, label in (
                (buys, "^", "up", "Buy fill"),
                (sells, "v", "down", "Sell fill"),
            ):
                if subset.is_empty():
                    continue
                marks.append(
                    ScatterMark(
                        x=src.epochs(subset["ts"]),
                        y=src.floats(subset["price"], name="fill price"),
                        marker=marker,  # type: ignore[arg-type]
                        role=role,  # type: ignore[arg-type]
                        size=26.0,
                        label=label,
                    )
                )

    # Indicators are grouped by unit, not one panel each. A strategy that publishes three
    # price-unit series (two moving averages and the close it already draws) used to get
    # three near-identical panels whose rotated labels ran into each other, and the one
    # series that was NOT a price fell off the end of an alphabetical cap. Anything
    # measured in price belongs over the price -- which is exactly how a moving average is
    # read -- and each remaining unit gets one panel with the series named in its legend.
    indicators = src.frame(ctx.rdir, "indicator_series.parquet", "name", "ts")
    by_unit: dict[str, list[str]] = {}
    if indicators is not None and not indicators.is_empty():
        for name in sorted({str(value) for value in indicators["name"].to_list()}):
            subset = indicators.filter(indicators["name"] == name)
            unit = _indicator_unit(str(subset["unit"].to_list()[0]))
            # `close` restates the price line this figure already draws.
            if unit == "price" and name == "close":
                continue
            by_unit.setdefault(unit, []).append(name)

    def _indicator_marks(unit: str, names: tuple[str, ...], role: str) -> tuple[Mark, ...]:
        assert indicators is not None
        drawn_marks: list[Mark] = []
        for index, name in enumerate(names):
            subset = indicators.filter(indicators["name"] == name)
            values = src.floats(subset["value"], name=name)
            # One series wears the role's own colour. Several sharing a panel must be told
            # apart, and two gold lines over the same price are two lines you cannot read.
            categorical = len(names) > 1
            drawn_marks.append(
                LineMark(
                    x=src.epochs(subset["ts"]),
                    y=values,
                    role="categorical" if categorical else role,  # type: ignore[arg-type]
                    palette_index=index if categorical else None,
                    label=name,
                    width=1.2,
                    end_label=ValueLabel(text=f"{values[-1]:,.2f}"),
                )
            )
        return tuple(drawn_marks)

    price_overlays = tuple(by_unit.pop("price", [])[:3])
    if price_overlays:
        marks.extend(_indicator_marks("price", price_overlays, "feature"))

    panels: list[Panel] = [
        Panel(
            panel_id="price",
            y_label="Price (native quote)",
            y_unit="price",
            height_ratio=3.0,
            marks=tuple(marks),
            note=None if drawn else "the strategy emitted no chart annotations",
        )
    ]

    for index, (unit, names) in enumerate(sorted(by_unit.items())):
        capped = tuple(names[:3])
        panels.append(
            Panel(
                panel_id=f"indicator_{index}",
                y_label=_UNIT_LABELS.get(unit, unit.replace("_", " ").capitalize()),
                y_unit=unit,  # type: ignore[arg-type]
                marks=_indicator_marks(unit, capped, "subject"),
                note=(
                    None
                    if len(capped) == len(names)
                    else f"showing {len(capped)} of {len(names)} {unit} series"
                ),
            )
        )

    fills_count = 0 if trace is None else int((trace["event_type"] == "fill").sum())
    return ctx.spec(
        "price_signal",
        x_label="Date (UTC)",
        artifacts=(
            "execution_trace.parquet",
            "chart_annotations.parquet",
            "indicator_series.parquet",
        ),
        truncation=_truncation(total, drawn, "annotations") if total else None,
        answer=(
            f"{fills_count:,} fills over {len(rows):,} sessions, with {drawn} strategy-authored "
            f"annotation{'s' if drawn != 1 else ''} drawn on price."
        ),
        panels=tuple(panels),
    )


_INDICATOR_UNITS = {
    "price",
    "ratio",
    "percent",
    "count",
    "days",
    "sharpe",
    "weight",
    "correlation",
    "probability",
    "z_score",
    "index",
    "seconds",
    "multiple",
    "account_currency",
}


#: An axis label must carry a unit a reader recognises, not the vocabulary token -- and it
#: must fit: these are budgeted for a short stacked panel, so every one stays under about
#: 22 characters rather than eliding into a shrug.
_UNIT_LABELS = {
    "account_currency": "Amount (account ccy)",
    "correlation": "Correlation (-1 to 1)",
    "count": "Count (n)",
    "days": "Duration (days)",
    "index": "Level (index points)",
    "multiple": "Multiple (x)",
    "percent": "Percent (%)",
    "price": "Price (native quote)",
    "probability": "Probability (0-1)",
    "ratio": "Ratio (unitless)",
    "seconds": "Duration (seconds)",
    "sharpe": "Sharpe (annualised)",
    "weight": "Weight (fraction)",
    "z_score": "Z-score (sigma)",
}


def _indicator_unit(raw: str) -> str:
    """Map a strategy-declared indicator unit onto the closed panel vocabulary.

    Strategies author their own unit strings; anything unrecognised is shown as a plain
    ratio rather than silently claiming to be a price.
    """
    return raw if raw in _INDICATOR_UNITS else "ratio"
