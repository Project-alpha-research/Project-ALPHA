"""`alpha context show-derived`: a derived context series as the research join sees it on bars."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import polars as pl
import typer

from alpha_cli._cli_json import emit
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_data.context import derived, finra_short
from alpha_data.context.attach import Binding, attach_context
from alpha_data.store import ParquetStore
from alpha_data.timeframe import DAILY, store_dir

derived_app = typer.Typer()
READING = "A reading of stored data, not a verdict; a null is a gap, never zero."


def _bars_and_calendar(asset: str) -> tuple[pl.DataFrame, str | None]:
    from alpha_cli._runner import _calendar_for

    store = ParquetStore(store_dir(AlphaSettings().data_dir, DAILY))
    return store.read_bars(asset), _calendar_for(asset, store.read_provenance(asset))


def _cell(value: float | None, reason: str | None) -> str:
    if value is not None:
        return f"{value:.6g}"
    return f"null ({reason})" if reason else "null"


def _stamp(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else "-"


def _coverage(frame: pl.DataFrame, cutoff: datetime) -> str:
    total = frame.height
    got = frame.filter(pl.col("ctx_v").is_not_null())
    reasons = frame.filter(pl.col("ctx_v").is_null())["ctx_v_reason"].fill_null(
        "warm-up or undefined"
    )
    counts = ", ".join(f"{k}: {n}" for k, n in sorted(reasons.value_counts().iter_rows()))
    stamps: list[datetime] = got["ts"].to_list()
    span = f"{stamps[0]:%Y-%m-%d} to {stamps[-1]:%Y-%m-%d}" if stamps else "none"
    return (
        f"Coverage: {got.height} of {total} bars have a value ({span}); nulls by cause: "
        f"{counts or 'none'}. Data cut at {cutoff:%Y-%m-%d}; bars on or after the reserved day "
        "are held back."
    )


@derived_app.command("show-derived")
def show_derived(
    series: str = typer.Option(
        ..., help=f"One of {', '.join([*derived.COT_SERIES, *derived.FINRA_SERIES])}."
    ),
    key: str = typer.Option(..., help="COT market code, FINRA symbol, or ALL for breadth."),
    asset: str = typer.Option(..., help="Stored daily symbol whose bars the series is placed on."),
    rows: int = typer.Option(20, "--rows", help="Newest bars to show; 0 shows all."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show a derived COT or FINRA series on an asset's daily bars (value, known_from, age)."""
    from alpha_cli.spine.reserve import CUTOFF

    try:
        bars, calendar = _bars_and_calendar(asset)
        result = attach_context(
            bars,
            timeframe=DAILY,
            calendar=calendar,
            bindings={"v": Binding(series, key)},
            data_dir=AlphaSettings().data_dir,
            cutoff=CUTOFF,
            symbol=asset,
        )
    except (DataError, OSError) as exc:
        raise typer.BadParameter(
            f"{exc}. Next: check --series, --key and --asset; `alpha context list` lists data."
        ) from None
    frame = result.frame
    shown = frame.tail(rows) if rows > 0 else frame
    table: list[dict[str, Any]] = [
        dict(
            bar_date=ts.strftime("%Y-%m-%d"),
            value=v,
            known_from=known.isoformat() if known else None,
            age_days=age,
            stale=stale,
            reason=reason,
        )
        for ts, v, known, age, stale, reason in shown.select(
            "ts", "ctx_v", "ctx_v_known_from", "ctx_v_age_days", "ctx_v_stale", "ctx_v_reason"
        ).iter_rows()
    ]
    note = result.notes["v"]
    coverage = _coverage(frame, CUTOFF)
    caveat = finra_short.CAVEAT if derived.series_source(series) == "finra" else ""
    payload = dict(
        series=series,
        key=key,
        asset=asset,
        recipe=result.recipe,
        used_rows_sha256=result.used_rows_sha256["v"],
        source_table_sha256=result.source_table_sha256,
        note=note,
        coverage=coverage,
        caveat=caveat,
        reading=READING,
        rows=table,
    )
    lines = [f"{'bar_date':<11}{'value':<24}{'known_from':<18}{'age_days':<10}stale"]
    for r in table:
        known = datetime.fromisoformat(r["known_from"]) if r["known_from"] else None
        age = "-" if r["age_days"] is None else str(r["age_days"])
        cells = (r["bar_date"], _cell(r["value"], r["reason"]), _stamp(known), age)
        lines.append(
            f"{cells[0]:<11}{cells[1]:<24}{cells[2]:<18}{cells[3]:<10}{str(r['stale']).lower()}"
        )
    lines.append(coverage)
    if note:
        lines.append(note)
    if caveat:
        lines.append(caveat)
    lines.append(f"Recipe {result.recipe}. {READING}")
    emit(payload, json_out=json_out, fallback="\n".join(lines))
