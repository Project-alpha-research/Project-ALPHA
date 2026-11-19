"""Free key-less context commands: CFTC, FINRA short volume and published factor returns."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Annotated, Any

import polars as pl
import typer

from alpha_cli._cli_json import emit
from alpha_cli.context_sources_cmds import _cutoff, _rows
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_data.context import cftc_cot, finra_short, osap_portfolios
from alpha_data.context.events import as_known_events, load_events

free_app = typer.Typer()


def _emit(payload: dict[str, Any], json_out: bool) -> None:
    emit(payload, json_out=json_out, fallback=json.dumps(payload, indent=2, allow_nan=False))


def _day(raw: str) -> date:
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        raise typer.BadParameter("dates must be YYYY-MM-DD") from None
    if parsed.isoformat() != raw:
        raise typer.BadParameter("dates must be YYYY-MM-DD")
    return parsed


def _fail(exc: Exception, *, pull: str) -> typer.BadParameter:
    text = str(exc)
    if "not found" in text:
        step = f"nothing is stored yet; run `alpha context {pull}` first"
    elif "offline" in text or "HTTP" in text:
        step = "check your network and wait a minute; nothing was stored, so it is safe to retry"
    else:
        step = f"check the values and run `alpha context {pull} --help`"
    return typer.BadParameter(f"{text}. Next: {step}.")


def free_listing() -> list[dict[str, Any]]:
    """Stored free context tables for `alpha context list`; read locally, no network."""
    data_dir = AlphaSettings().data_dir
    try:
        return [
            *cftc_cot.describe(data_dir),
            *finra_short.describe(data_dir),
            *osap_portfolios.describe(data_dir),
        ]
    except (DataError, OSError) as exc:
        raise typer.BadParameter(f"{exc}. Next: re-pull the named source.") from None


@free_app.command("pull-cftc-cot")
def pull_cftc_cot(
    market: Annotated[
        list[str], typer.Option("--market", help="CFTC contract market code, e.g. 13874A.")
    ],
    since: str = typer.Option("2016-01-01", help="First report date, YYYY-MM-DD."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Pull weekly CFTC positioning (legacy, futures only); no key. Known at the Friday release."""
    try:
        report = cftc_cot.pull_cot(
            data_dir=AlphaSettings().data_dir,
            markets=market,
            since=_day(since),
            fetched_at=datetime.now(UTC),
        )
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-cftc-cot") from None
    _emit(report, json_out)


@free_app.command("pull-finra-short-volume")
def pull_finra_short_volume(
    symbol: Annotated[list[str], typer.Option("--symbol", help="Ticker; repeat for several.")],
    start: str = typer.Option(..., help="First trade date, YYYY-MM-DD."),
    end: str = typer.Option(..., help="Last trade date, YYYY-MM-DD."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Pull FINRA daily short sale volume; no key. Covers FINRA-reported trades only."""
    try:
        report = finra_short.pull_short_volume(
            data_dir=AlphaSettings().data_dir,
            symbols=symbol,
            start=_day(start),
            end=_day(end),
            fetched_at=datetime.now(UTC),
        )
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-finra-short-volume") from None
    _emit(report, json_out)
    if not json_out:
        typer.echo(finra_short.CAVEAT)


@free_app.command("show-cftc-cot")
def show_cftc_cot(
    market: str = typer.Option(..., help="CFTC contract market code."),
    as_of: str | None = typer.Option(None, help="UTC date or minute; default now."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show stored CFTC positioning known at the cutoff (a row appears only once published)."""
    cutoff = _cutoff(as_of)
    try:
        path = cftc_cot.table_path(AlphaSettings().data_dir, market)
        df = as_known_events(
            load_events(path, source=cftc_cot.SOURCE, schema=cftc_cot.SCHEMA), as_of=cutoff
        )
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-cftc-cot --market <CODE>") from None
    _emit(
        dict(
            market_code=market,
            view="as_known",
            as_of=cutoff.isoformat(),
            known_from_rule=cftc_cot.KNOWN_RULE,
            rows=_rows(df.sort("report_date")),
        ),
        json_out,
    )


@free_app.command("show-finra-short-volume")
def show_finra_short_volume(
    symbol: str = typer.Option(...),
    as_of: str | None = typer.Option(None, help="UTC date or minute; default now."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show stored FINRA short volume known at the cutoff; FINRA-reported trades only."""
    cutoff = _cutoff(as_of)
    try:
        path = finra_short.table_path(AlphaSettings().data_dir, symbol)
        df = as_known_events(
            load_events(path, source=finra_short.SOURCE, schema=finra_short.SCHEMA), as_of=cutoff
        )
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-finra-short-volume --symbol <S>") from None
    _emit(
        dict(
            symbol=symbol,
            view="as_known",
            as_of=cutoff.isoformat(),
            known_from_rule=finra_short.KNOWN_RULE,
            caveat=finra_short.CAVEAT,
            rows=_rows(df.sort(pl.col("trade_date"))),
        ),
        json_out,
    )
    if not json_out:
        typer.echo(finra_short.CAVEAT)


@free_app.command("pull-osap-portfolios")
def pull_osap_portfolios(
    release: str = typer.Option(..., help="The source's release id, e.g. 2026.10."),
    released: str = typer.Option(
        ..., help="True release date, YYYY-MM-DD; not before the newest month plus one day."
    ),
    branch: str | None = typer.Option(None, help="Release branch if not Data-Release-<release>."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Pull one release of published long-short factor returns; no key. Never replaces a vintage."""
    try:
        report = osap_portfolios.pull_portfolios(
            data_dir=AlphaSettings().data_dir,
            release=release,
            released=_day(released),
            fetched_at=datetime.now(UTC),
            branch=branch,
        )
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-osap-portfolios") from None
    _emit(report, json_out)
    if not json_out:
        typer.echo(osap_portfolios.CAVEAT)


@free_app.command("show-osap-portfolios")
def show_osap_portfolios(
    as_of: str | None = typer.Option(None, help="UTC date or minute; default now."),
    release: str | None = typer.Option(None, help="Read this vintage; default the newest known."),
    signal: Annotated[
        list[str] | None, typer.Option("--signal", help="Signal id; repeat. None: counts only.")
    ] = None,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show stored factor returns known at the cutoff, naming the vintage used."""
    cutoff = _cutoff(as_of)
    try:
        used, df = osap_portfolios.read_known(
            AlphaSettings().data_dir, as_of=cutoff, release=release
        )
    except (DataError, OSError) as exc:
        raise _fail(exc, pull="pull-osap-portfolios --release <R> --released <DATE>") from None
    shown = df.filter(pl.col("signal").is_in(signal)) if signal else df.head(0)
    _emit(
        dict(
            view="as_known",
            as_of=cutoff.isoformat(),
            release=used,
            unit=osap_portfolios.UNIT_NOTE,
            known_from_rule=osap_portfolios.KNOWN_RULE,
            caveat=osap_portfolios.CAVEAT,
            signals=df["signal"].n_unique(),
            months=df["month"].n_unique(),
            rows=_rows(shown.sort(["signal", "month"])),
        ),
        json_out,
    )
