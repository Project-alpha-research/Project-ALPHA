"""`alpha data market-overview`, `run-price` and `chart-datasets`: read-only chart data."""

from __future__ import annotations

import json

import typer

from alpha_cli.market_overview_cmds import run_market_overview
from alpha_cli.run_price_cmds import run_run_price
from alpha_core import DataError


def market_overview_command(
    store: str = typer.Option("1D", help="stored bar size: 1D (default), 1h, 5m, ..."),
    window: int = typer.Option(90, help="bars shown: 30, 90 or 365"),
    limit: int = typer.Option(15, help="how many assets (1..30)"),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Read-only market overview of stored bars. Market view. Not a test result."""
    run_market_overview(store, window, limit, json_out)


def run_price_command(
    run_id: str = typer.Argument(..., help="a completed rule-test run id"),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Stored price bars of a rule test, only when they hash to the run's recorded source."""
    run_run_price(run_id, json_out)


def chart_datasets_command(json_out: bool = typer.Option(False, "--json")) -> None:
    """Discover qualified external archive chart datasets without hashing all artifacts."""
    from alpha_cli._chart_data import chart_datasets
    from alpha_cli.crypto_data_cmds import BulkVolumeUnconfigured, _bulk_store

    try:
        store = _bulk_store()
        store.verify_readable()
        result = {"datasets": chart_datasets(store), "authority": "none", "state": "available"}
    except BulkVolumeUnconfigured:
        result = {"datasets": [], "authority": "none", "state": "unconfigured"}
    except (DataError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_out:
        typer.echo(json.dumps(result))
    else:
        typer.echo(f"{len(result['datasets'])} archive chart datasets")
