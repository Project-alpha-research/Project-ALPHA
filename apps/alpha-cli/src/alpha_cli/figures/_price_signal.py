"""The price-with-signals figure: price cut to the run, annotations, fills and indicators."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal, cast

from alpha_cli import run_price_cmds
from alpha_cli.figures import _sources as src
from alpha_cli.figures._common import (
    _UNIT_LABELS,
    BuildContext,
    _indicator_unit,
    _truncation,
)
from alpha_cli.figures._held import held_zones, open_position_zone
from alpha_cli.run_projection import MAX_CHART_BARS
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
from alpha_research.figures.spec import Role, YUnit

_MAX_FILL_MARKERS = 60
_MAX_CANDLES = 400


def _run_span(ctx: BuildContext) -> tuple[float, float] | None:
    frame = src.frame(ctx.rdir, "equity_curve.parquet", "ts")
    if frame is None or frame.is_empty():
        return None
    ts = src.epochs(frame["ts"])
    # The equity recorder stamps a session a microsecond after its candle, so the candle
    # that opens the run sits just before ``ts[0]``. One second of slack keeps it.
    return ts[0] - 1.0, ts[-1] + 1.0


def _clip(frame: Any, column: str, span: tuple[float, float] | None) -> Any:
    """Rows whose timestamp lies inside the plotted window; every mark shares one window."""
    if span is None or frame is None or frame.is_empty():
        return frame
    seconds = frame[column].dt.epoch("us") / 1e6
    return frame.filter((seconds >= span[0]) & (seconds <= span[1]))


def _price_marks(rows: list[dict[str, float]]) -> list[Mark]:
    ts = tuple(row["t"] for row in rows)
    if len(rows) <= _MAX_CANDLES:
        return [
            CandleMark(
                x=ts,
                open=tuple(row["o"] for row in rows),
                high=tuple(row["h"] for row in rows),
                low=tuple(row["l"] for row in rows),
                close=tuple(row["c"] for row in rows),
                alpha=0.85,
            )
        ]
    closes = tuple(row["c"] for row in rows)
    return [LineMark(x=ts, y=closes, role="substrate", label="Close", width=1.0)]


def _annotation_marks(
    ctx: BuildContext, span: tuple[float, float] | None
) -> tuple[list[Mark], int, int]:
    """The strategy's own annotations: marks, how many were drawn, how many exist."""
    annotations = src.frame(ctx.rdir, "chart_annotations.parquet", "annotation_id", "anchor_index")
    if annotations is None or annotations.is_empty():
        return [], 0, 0
    marks: list[Mark] = []
    groups = annotations.partition_by("annotation_id", maintain_order=True)
    if span is not None:
        # Keep a whole annotation that touches the window: dropping its outside anchors
        # would leave a one-point line. The explicit x-limits crop what lies outside.
        # The cap comes after this, so the first 40 are the first 40 that can be seen.
        groups = [
            g
            for g in groups
            if max(src.epochs(g["ts"])) >= span[0] and min(src.epochs(g["ts"])) <= span[1]
        ]
    drawn = 0
    for group in groups[:40]:
        label = str(group["label"].to_list()[0])
        xs = src.epochs(group["ts"])
        ys = src.floats(group["value"], name="annotation value")
        first = label if drawn == 0 else None
        is_zone = str(group["kind"].to_list()[0]) == "zone"
        x0 = max(min(xs), span[0]) if span else min(xs)
        x1 = min(max(xs), span[1]) if span else max(xs)
        if is_zone and x1 <= x0:
            continue  # clipping left a single instant: nothing to shade
        if is_zone:
            marks.append(
                ZoneMark(
                    x0=x0,
                    x1=x1,
                    role="feature",
                    alpha=0.12,
                    label=first,
                    corner_label=ValueLabel(text=label),
                )
            )
        else:
            marks.append(
                LineMark(
                    x=xs,
                    y=ys,
                    role="feature",
                    label=first,
                    end_label=ValueLabel(text=f"{label} {ys[-1]:.2f}"),
                )
            )
        drawn += 1
    return marks, drawn, len(groups)


def _fill_marks(ctx: BuildContext, span: tuple[float, float] | None) -> tuple[list[Mark], str, int]:
    """Fill markers, or shaded held periods when there are too many fills to read."""
    trace = src.frame(ctx.rdir, "execution_trace.parquet", "sequence_id")
    if trace is None or trace.is_empty():
        return [], "", 0
    all_fills = trace.filter(trace["event_type"] == "fill")
    fills = _clip(all_fills, "ts", span)
    # Held periods are always shaded, as in the approved sample; markers too when few enough.
    zones = held_zones(ctx, span)
    open_zone = open_position_zone(all_fills, span)
    if open_zone is not None:
        zones.append(open_zone)
    if len(fills) > _MAX_FILL_MARKERS and zones:
        return zones, f"{len(fills):,} fills shown as shaded held periods", len(all_fills)
    size = 26.0 if len(fills) <= _MAX_FILL_MARKERS else 9.0
    marks: list[Mark] = list(zones)
    sides: tuple[tuple[str, Literal["^", "v"], Role, str], ...] = (
        ("BUY", "^", "up", "Buy fill"),
        ("SELL", "v", "down", "Sell fill"),
    )
    for side, marker, role, label in sides:
        subset = fills.filter(fills["side"] == side)
        if not subset.is_empty():
            marks.append(
                ScatterMark(
                    x=src.epochs(subset["ts"]),
                    y=src.floats(subset["price"], name="fill price"),
                    marker=marker,
                    role=role,
                    size=size,
                    label=label,
                )
            )
    return marks, "", len(all_fills)


def _indicator_marks(indicators: Any, names: tuple[str, ...], role: Role) -> tuple[Mark, ...]:
    out: list[Mark] = []
    for index, name in enumerate(names):
        subset = indicators.filter(indicators["name"] == name)
        values = src.floats(subset["value"], name=name)
        # One series wears the role's own colour; several sharing a panel must be told apart.
        many = len(names) > 1
        out.append(
            LineMark(
                x=src.epochs(subset["ts"]),
                y=values,
                role="categorical" if many else role,
                palette_index=index if many else None,
                label=name,
                width=1.2,
                end_label=ValueLabel(text=f"{values[-1]:,.2f}"),
            )
        )
    return tuple(out)


def _indicator_panels(
    ctx: BuildContext, span: tuple[float, float] | None
) -> tuple[list[Mark], list[Panel]]:
    """Price-unit indicators ride on the price; each other unit gets one panel."""
    indicators = _clip(src.frame(ctx.rdir, "indicator_series.parquet", "name", "ts"), "ts", span)
    by_unit: dict[str, list[str]] = {}
    if indicators is not None and not indicators.is_empty():
        for name in sorted({str(value) for value in indicators["name"].to_list()}):
            subset = indicators.filter(indicators["name"] == name)
            unit = _indicator_unit(str(subset["unit"].to_list()[0]))
            if unit == "price" and name == "close":  # restates the price line already drawn
                continue
            by_unit.setdefault(unit, []).append(name)
    overlays: list[Mark] = []
    price_names = tuple(by_unit.pop("price", [])[:3])
    if price_names:
        overlays.extend(_indicator_marks(indicators, price_names, "feature"))
    panels: list[Panel] = []
    for index, (unit, names) in enumerate(sorted(by_unit.items())):
        capped = tuple(names[:3])
        panels.append(
            Panel(
                panel_id=f"indicator_{index}",
                y_label=_UNIT_LABELS.get(unit, unit.replace("_", " ").capitalize()),
                y_unit=cast(YUnit, unit),
                marks=_indicator_marks(indicators, capped, "subject"),
                note=(
                    None
                    if len(capped) == len(names)
                    else f"showing {len(capped)} of {len(names)} {unit} series"
                ),
            )
        )
    return overlays, panels


_NOT_DRAWN = {
    run_price_cmds.BARS_CHANGED: "the stored price bars no longer match the bars this run used "
    "(the fingerprint check failed). Run the test again to chart the bars stored now.",
    run_price_cmds.NOT_SAVED: "this run did not record enough to find and check its bars.",
}


def _stored_rows(ctx: BuildContext) -> list[dict[str, float]]:
    """A rule test's bars from the store, cut at the held-back date, only when they hash to the
    run's recorded source fingerprint."""
    status, rows = run_price_cmds.verified_bars(ctx.manifest, data_dir=ctx.data_dir)
    if status != run_price_cmds.AVAILABLE or not rows:
        reason = _NOT_DRAWN.get(status, "the stored price bars of this run could not be read.")
        raise DataError(f"The price chart is not drawn: {reason}")
    return [rows[index] for index in src.sample(len(rows), MAX_CHART_BARS)]


def price_signal(ctx: BuildContext) -> FigureSpec:
    keys = ("symbol", "snapshot_id", "start", "end", "timeframe", "source_timeframe", "session")
    if not ctx.field("snapshot_id") and isinstance(ctx.manifest.get("spine"), dict):
        rows = _stored_rows(ctx)
    else:
        rows, reason = src.bars({key: ctx.field(key) for key in keys}, data_dir=ctx.data_dir)
        if reason is not None or not rows:
            raise DataError(f"price bars unavailable for this run ({reason or 'no bars'})")
    span = _run_span(ctx)
    if span is not None:
        # The store can hold years of bars past the run's last session; the figure is about
        # what the strategy saw and did, so it stops where the run stops.
        rows = [row for row in rows if span[0] <= row["t"] <= span[1]]
        if not rows:
            raise DataError("no price bars fall inside this run's dated span")
    marks = _price_marks(rows)
    annotation_marks, drawn, total = _annotation_marks(ctx, span)
    marks.extend(annotation_marks)
    fill_marks, held_note, fills_count = _fill_marks(ctx, span)
    marks.extend(fill_marks)
    overlays, indicator_panels = _indicator_panels(ctx, span)
    marks.extend(overlays)
    price = Panel(
        panel_id="price",
        y_label="Price (native quote)",
        y_unit="price",
        height_ratio=3.0,
        marks=tuple(marks),
    )
    spec = ctx.spec(
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
        panels=(price, *indicator_panels),
    )
    if span is not None:
        spec = replace(spec, x_limits=span)
    # A note inside the axes covers data, so what it says goes in the caption instead.
    notes = [held_note] if held_note else []
    if not drawn:
        notes.append("the strategy emitted no chart annotations")
    return replace(spec, caption=f"{spec.caption} · {' · '.join(notes)}") if notes else spec
