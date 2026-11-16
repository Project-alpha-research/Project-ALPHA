"""EDGAR and Binance context commands; local reads always apply a UTC cutoff."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import typer

from alpha_cli._cli_json import emit
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_data.context import binance_bulk, edgar
from alpha_data.context.events import (
    FILINGS_SCHEMA,
    FUNDING_SCHEMA,
    INSIDER_SCHEMA,
    METRICS_SCHEMA,
    as_known_events,
    load_events,
)

sources_app = typer.Typer()


def _emit(payload: dict[str, Any], json_out: bool) -> None:
    emit(payload, json_out=json_out, fallback=json.dumps(payload, indent=2, allow_nan=False))


def _cutoff(raw: str | None) -> datetime:
    if raw is None:
        return datetime.now(UTC)
    try:
        fmt = "%Y-%m-%d" if len(raw) == 10 else "%Y-%m-%dT%H:%M"
        value = datetime.strptime(raw, fmt)
        if value.strftime(fmt) != raw:
            raise ValueError
        return value.replace(tzinfo=UTC)
    except ValueError:
        raise typer.BadParameter("expected YYYY-MM-DD or YYYY-MM-DDTHH:MM (UTC)") from None


def _fail(exc: Exception, *, pull: str) -> typer.BadParameter:
    """Say what went wrong and the one thing to do next."""
    text = str(exc)
    if "ALPHA_SEC_USER_AGENT" in text:
        step = "set ALPHA_SEC_USER_AGENT to your name and e-mail, as the SEC asks, then retry"
    elif "not found" in text:
        step = f"nothing is stored yet; run `alpha context {pull}` first"
    elif "BAD_RANGE" in text or "invalid" in text:
        step = f"check the values and run `alpha context {pull} --help`"
    else:
        step = "check your network and wait a minute; nothing was stored, so it is safe to retry"
    return typer.BadParameter(f"{text}. Next: {step}.")


def _rows(df: pl.DataFrame) -> list[dict[str, Any]]:
    return [
        {k: v.isoformat() if isinstance(v, date) else v for k, v in row.items()}
        for row in df.iter_rows(named=True)
    ]


@sources_app.command("pull-edgar")
def pull_edgar(
    ticker: str | None = typer.Option(None),
    cik: str | None = typer.Option(None),
    forms: str = typer.Option("4,8-K"),
    since: str = typer.Option("2016-01-01"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Pull filings and insider transactions with the declared ALPHA_SEC_USER_AGENT."""
    lower = _cutoff(since).date()
    try:
        report = edgar.pull_edgar(
            data_dir=AlphaSettings().data_dir,
            ticker=ticker,
            cik=cik,
            forms=forms,
            since=lower,
            fetched_at=datetime.now(UTC),
        )
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-edgar") from None
    _emit(report, json_out)


@sources_app.command("pull-binance")
def pull_binance(
    symbol: str = typer.Option(...),
    kind: str = typer.Option(...),
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Pull checksum-verified funding months or metrics days (at most 400 days)."""
    try:
        report = binance_bulk.pull_binance(
            data_dir=AlphaSettings().data_dir,
            symbol=symbol,
            kind=kind,
            start=start,
            end=end,
            fetched_at=datetime.now(UTC),
        )
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-binance") from None
    _emit(report, json_out)


@sources_app.command("show-edgar")
def show_edgar(
    ticker: str | None = typer.Option(None),
    cik: str | None = typer.Option(None),
    view: str = typer.Option(..., help="filings, earnings or insider."),
    as_of: str | None = typer.Option(None, help="UTC date or minute; default now."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show locally stored EDGAR events as known at the cutoff."""
    cutoff = _cutoff(as_of)
    if view not in {"filings", "earnings", "insider"}:
        raise typer.BadParameter("--view must be filings, earnings or insider")
    data_dir = AlphaSettings().data_dir
    try:
        identifier = edgar.resolve_cik(data_dir, ticker=ticker, cik=cik)
        table = "insider" if view == "insider" else "filings"
        schema = INSIDER_SCHEMA if table == "insider" else FILINGS_SCHEMA
        df = load_events(
            data_dir / "context/edgar" / identifier / f"{table}.parquet",
            source="edgar",
            schema=schema,
        )
        df = as_known_events(df, as_of=cutoff)
        if view == "earnings":
            df = edgar.earnings(df)
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-edgar --ticker <T>") from None
    _emit(
        dict(
            cik=identifier, dataset=view, view="as_known", as_of=cutoff.isoformat(), rows=_rows(df)
        ),
        json_out,
    )


@sources_app.command("show-binance")
def show_binance(
    symbol: str = typer.Option(...),
    kind: str = typer.Option(...),
    as_of: str | None = typer.Option(None, help="UTC date or minute; default now."),
    start: str | None = typer.Option(None),
    end: str | None = typer.Option(None),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show stored funding or metrics as known, with optional inclusive UTC date bounds."""
    cutoff = _cutoff(as_of)
    lower, upper = (_cutoff(v).date() if v is not None else None for v in (start, end))
    if lower is not None and upper is not None and upper < lower:
        raise typer.BadParameter("BAD_RANGE: --end precedes --start")
    try:
        path = binance_bulk.table_path(AlphaSettings().data_dir, kind, symbol)
        schema = FUNDING_SCHEMA if kind == "funding" else METRICS_SCHEMA
        df = as_known_events(load_events(path, source="binance", schema=schema), as_of=cutoff)
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-binance --symbol <S> --kind <K>") from None
    key = "funding_time" if kind == "funding" else "ts"
    if lower is not None:
        df = df.filter(pl.col(key).dt.date() >= lower)
    if upper is not None:
        df = df.filter(pl.col(key).dt.date() <= upper)
    _emit(
        dict(symbol=symbol, kind=kind, view="as_known", as_of=cutoff.isoformat(), rows=_rows(df)),
        json_out,
    )
