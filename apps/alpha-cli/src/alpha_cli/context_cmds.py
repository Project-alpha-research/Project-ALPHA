"""Read and acquire point-in-time macro reference data."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

import polars as pl
import typer

from alpha_cli import context_sources_cmds as sources
from alpha_cli._cli_json import emit
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_data.context.fred import (
    DEFAULT_SERIES,
    as_known,
    first_release,
    latest,
    load_series,
    pull_series,
)
from alpha_data.context.views import read_provenance

context_app = typer.Typer(help="Point-in-time macro, SEC filings and Binance derivatives context.")


def _emit(payload: dict[str, Any], json_out: bool) -> None:
    emit(payload, json_out=json_out, fallback=json.dumps(payload, indent=2, allow_nan=False))


def _date(raw: str | None, default: date | None = None) -> date | None:
    if raw is None:
        return default
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        raise typer.BadParameter("dates must be YYYY-MM-DD") from None
    if parsed.isoformat() != raw:
        raise typer.BadParameter("dates must be YYYY-MM-DD")
    return parsed


def _bounds(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise typer.BadParameter("--end precedes --start")


def _stored(data_dir: Path) -> list[str]:
    return sorted(path.stem for path in (data_dir / "context/fred").glob("*.parquet"))


@context_app.command()
def pull(
    series: Annotated[
        list[str] | None, typer.Option("--series", help="Series ID; repeat for several.")
    ] = None,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Pull FRED vintages using FRED_API_KEY; default to the macro starter set."""
    data_dir = AlphaSettings().data_dir
    results, errors = [], []
    for series_id in dict.fromkeys(series or DEFAULT_SERIES):
        try:
            result = pull_series(series_id, data_dir=data_dir, fetched_at=datetime.now(UTC))
            results.append(
                {
                    "series_id": series_id,
                    **{
                        name: result[name] for name in ("rows", "first_obs", "last_obs", "vintages")
                    },
                }
            )
        except (DataError, OSError, pl.exceptions.PolarsError) as exc:
            errors.append({"series_id": series_id, "error": str(exc)})
    _emit({"series": results, "errors": errors}, json_out)
    if not results:
        raise typer.Exit(1)


@context_app.command("list")
def list_series(json_out: bool = typer.Option(False, "--json")) -> None:
    """List locally stored series and their provenance (no network)."""
    data_dir = AlphaSettings().data_dir
    rows = []
    try:
        for series_id in _stored(data_dir):
            meta = read_provenance(series_id, data_dir=data_dir)
            rows.append(
                {
                    "series_id": series_id,
                    "label": DEFAULT_SERIES.get(series_id, meta["title"]),
                    **{k: meta[k] for k in ("title", "frequency", "last_obs", "fetched_at")},
                }
            )
    except (DataError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from None
    _emit({"series": rows}, json_out)


@context_app.command()
def show(
    series_id: str,
    as_of: str | None = typer.Option(None, help="Knowledge cutoff YYYY-MM-DD; default today UTC."),
    start: str | None = typer.Option(None, help="First observation date, inclusive."),
    end: str | None = typer.Option(None, help="Last observation date, inclusive."),
    view: str = typer.Option("known", help="known, first or latest; non-known views are explicit."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show stored observations with the selected vintage view named in the output."""
    cutoff = _date(as_of, datetime.now(UTC).date())
    lower, upper = _date(start), _date(end)
    _bounds(lower, upper)
    if view not in {"known", "first", "latest"}:
        raise typer.BadParameter("--view must be known, first or latest")
    assert cutoff is not None
    try:
        df = load_series(series_id, data_dir=AlphaSettings().data_dir)
        df = (
            as_known(df, as_of=cutoff)
            if view == "known"
            else first_release(df)
            if view == "first"
            else latest(df)
        )
    except (DataError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from None
    if lower is not None:
        df = df.filter(pl.col("obs_date") >= lower)
    if upper is not None:
        df = df.filter(pl.col("obs_date") <= upper)
    rows = [
        {"obs_date": str(r["obs_date"]), "value": r["value"], "known_from": str(r["known_from"])}
        for r in df.iter_rows(named=True)
    ]
    _emit(
        {
            "series_id": series_id,
            "view": {"known": "as_known", "first": "first_release", "latest": "latest"}[view],
            "as_of": str(cutoff) if view == "known" else None,
            "rows": rows,
        },
        json_out,
    )


def _endpoint(df: pl.DataFrame, when: date, cutoff: date) -> float | None:
    available = as_known(df, as_of=min(when, cutoff)).filter(pl.col("obs_date") <= when)
    return (
        float(available["value"][-1])
        if available.height and available["value"][-1] is not None
        else None
    )


@context_app.command()
def window(
    start: str = typer.Option(..., help="Window start YYYY-MM-DD, inclusive."),
    end: str = typer.Option(..., help="Window end YYYY-MM-DD, inclusive."),
    series: Annotated[
        list[str] | None, typer.Option("--series", help="Series ID; default all stored.")
    ] = None,
    as_of: str | None = typer.Option(None, help="Knowledge cutoff; default window end."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Summarise the macro window; endpoints use values knowable at each boundary.

    Endpoints carry the last observation on or before the boundary, capped by --as-of.
    Min/max use observations inside the window as known at --as-of. Missing values stay null.
    """
    lower, upper = _date(start), _date(end)
    _bounds(lower, upper)
    assert lower is not None and upper is not None
    cutoff = _date(as_of, upper)
    assert cutoff is not None
    data_dir = AlphaSettings().data_dir
    rows = []
    try:
        for series_id in dict.fromkeys(series or _stored(data_dir)):
            df = load_series(series_id, data_dir=data_dir)
            start_value, end_value = _endpoint(df, lower, cutoff), _endpoint(df, upper, cutoff)
            inside = as_known(df, as_of=cutoff).filter(pl.col("obs_date").is_between(lower, upper))
            rows.append(
                {
                    "series_id": series_id,
                    "start_value": start_value,
                    "end_value": end_value,
                    "change": end_value - start_value
                    if start_value is not None and end_value is not None
                    else None,
                    "min": inside["value"].min(),
                    "max": inside["value"].max(),
                }
            )
    except (DataError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from None
    _emit(
        {
            "view": "as_known",
            "as_of": str(cutoff),
            "start": str(lower),
            "end": str(upper),
            "series": rows,
        },
        json_out,
    )


context_app.command("pull-edgar")(sources.pull_edgar)
context_app.command("pull-binance")(sources.pull_binance)
context_app.command("show-edgar")(sources.show_edgar)
context_app.command("show-binance")(sources.show_binance)
