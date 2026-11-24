"""`alpha data coverage` and `alpha data update`: what is stored, and bring it up to date.

An update runs the same `alpha data pull` the owner would type, per stored symbol, with the source
recorded for that symbol. A pull replaces the whole stored series (after freezing it), so an update
starts at the first stored bar and ends at the newest closed day; the nightly refresh does the same.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import typer
from polars.exceptions import PolarsError

from alpha_cli.nightly_steps import alpha_argv
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_data.store import ParquetStore
from alpha_data.timeframe import DAILY, store_dir


def _health(store: ParquetStore, symbol: str) -> str:
    from alpha_cli._data_health import current_fingerprint, read_report

    try:
        saved = read_report(store, symbol)
        if saved is None:
            return "unchecked"
        stale = saved.source_fingerprint != current_fingerprint(store, symbol, saved)
        return "out of date" if stale else saved.verdict
    except (DataError, OSError, ValueError):
        return "unreadable"


def coverage_rows(data_dir: Path) -> list[dict[str, object]]:
    """One row per stored symbol. Bars are read through the cut read, so the last date stops at the
    held-back boundary. A series that cannot be read says why; it is never shown as zero bars."""
    from alpha_cli._runner import load_bars
    from alpha_cli.spine import reserve

    store = ParquetStore(store_dir(data_dir, DAILY))
    rows: list[dict[str, object]] = []
    for symbol in store.list_symbols():
        row: dict[str, object] = {
            "symbol": symbol,
            "first": None,
            "last": None,
            "bars": None,
            "note": None,
            "health": _health(store, symbol),
        }
        try:
            bars, _ = load_bars(symbol, data_dir=data_dir, as_of=reserve.CUTOFF)
            row.update(
                first=bars[0].ts.date().isoformat(),
                last=bars[-1].ts.date().isoformat(),
                bars=len(bars),
            )
        except (DataError, OSError, ValueError, PolarsError) as exc:
            row["note"] = f"cannot be read: {exc}"
        rows.append(row)
    return rows


def out_of_date_reason(row: dict[str, object], today: date) -> str:
    """Why a health report is "out of date": the bars changed after it was written."""
    return (
        "the health report is out of date: the stored bars changed after it was written "
        f"(newest stored bar {row['last'] or 'unknown'}; today is {today.isoformat()}). "
        f"Run alpha data health {row['symbol']} to check it again."
    )


def run_coverage(json_out: bool) -> None:
    rows = coverage_rows(AlphaSettings().data_dir)
    if json_out:
        typer.echo(json.dumps({"symbols": rows}, sort_keys=True))
        return
    if not rows:
        typer.echo(
            "No data is stored yet. Pull some with: alpha data pull SYMBOL --start ... --end ..."
        )
        return
    from alpha_core.reserve import RESERVED_START

    typer.echo(
        f"Dates and bars stop before {RESERVED_START}: later bars are stored but held back "
        "for the final check (alpha confirm)."
    )
    typer.echo(f"{'symbol':<14}{'first date':<12}{'last date':<12}{'bars':>6}  health")
    for row in rows:
        bars = "-" if row["bars"] is None else str(row["bars"])
        typer.echo(
            f"{row['symbol']!s:<14}{row['first'] or '-':<12}{row['last'] or '-':<12}"
            f"{bars:>6}  {row['health']}"
        )
        if row["note"]:
            typer.echo(f"  {row['symbol']}: {row['note']}")
        if row["health"] == "out of date":
            typer.echo(f"  {row['symbol']}: {out_of_date_reason(row, datetime.now(UTC).date())}")


def run_update(dry_run: bool) -> None:
    from alpha_cli.nightly_refresh import _plan

    home = AlphaSettings().data_dir
    today = datetime.now(UTC).date()
    symbols = ParquetStore(store_dir(home, DAILY)).list_symbols()
    if not symbols:
        typer.echo("No data is stored yet, so there is nothing to update.")
        return
    failed = 0
    planned = 0
    for symbol in symbols:
        try:
            tail, _ = _plan(home, symbol, today)
        except (ValueError, DataError) as exc:
            typer.echo(f"{symbol}: skipped. {exc}")
            failed += 1
            continue
        line = "alpha " + " ".join(tail)
        if dry_run:
            typer.echo(f"{symbol}: would run {line}")
            planned += 1
            continue
        done = subprocess.run(alpha_argv(tail), capture_output=True, text=True, check=False)
        if done.returncode == 0:
            typer.echo(f"{symbol}: updated.")
            # The pull's own report: counts, the snapshot, and any revised or removed old bars.
            for line in done.stdout.strip().splitlines():
                typer.echo(f"  {line}")
        else:
            failed += 1
            last = (done.stderr.strip().splitlines() or ["no message"])[-1]
            typer.echo(f"{symbol}: failed (exit {done.returncode}). {last}")
    if planned:
        typer.echo(
            "A pull replaces the whole stored series (after freezing it), so each of these "
            "re-pulls every day from the first stored bar, not only the new days."
        )
    typer.echo(
        f"The newest day asked for is {today - timedelta(days=1)} (UTC). Today's bar arrives "
        "with the next update after the UTC day ends."
    )
    if failed:
        raise typer.Exit(1)
