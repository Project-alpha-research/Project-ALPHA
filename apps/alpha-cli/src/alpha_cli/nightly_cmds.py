"""`alpha nightly run` and `status`: prove each night that the whole pipeline still works.

The run judges the system on the data stored here. It never judges whether an idea is good.
It installs no schedule. `status` prints the one crontab line the owner can paste.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha_cli._cli_json import emit
from alpha_cli.nightly_config import NightlyConfigError, load_config
from alpha_cli.nightly_record import ORDER
from alpha_cli.nightly_run import run_nightly
from alpha_cli.nightly_status import status_facts, status_text
from alpha_cli.nightly_steps import subprocess_runner
from alpha_core.config import AlphaSettings

nightly_app = typer.Typer(help="Run the golden paths on real stored data and read the record.")
CONFIG = Annotated[Path, typer.Option("--config", help="The nightly.toml file.")]
JSON = Annotated[bool, typer.Option("--json", help="Print the same facts as one JSON object.")]


@nightly_app.command("run")
def run(
    config: CONFIG = Path("nightly.toml"),
    only: Annotated[
        str | None,
        typer.Option("--only", help="Comma list of N1,N2,N3,N4,N0. A partial run is not full."),
    ] = None,
    json_out: JSON = False,
) -> None:
    """Run the golden paths end to end and write one dated record. Installs nothing."""
    chosen = (
        tuple(part.strip().upper() for part in only.split(",") if part.strip()) if only else None
    )
    if chosen is not None and (not chosen or not set(chosen) <= set(ORDER)):
        typer.echo(f"--only takes names from {', '.join(ORDER)}.", err=True)
        raise typer.Exit(2)
    try:
        settings = load_config(config)
    except NightlyConfigError as error:
        typer.echo(f"The nightly config has a problem:\n{error}", err=True)
        raise typer.Exit(2) from error
    record = run_nightly(settings, AlphaSettings().data_dir, subprocess_runner, only=chosen)
    folder = AlphaSettings().data_dir / "nightly" / f"{record['date']}-{record['run_number']}"
    emit(record, json_out=json_out, fallback=(folder / "summary.txt").read_text(encoding="utf-8"))
    raise typer.Exit(1 if record["blocking"] else 0)


@nightly_app.command("status")
def status(config: CONFIG = Path("nightly.toml"), json_out: JSON = False) -> None:
    """Say what the last run showed, the clean streak, and whether it is ready. Writes nothing."""
    facts = status_facts(AlphaSettings().data_dir, config)
    emit(facts, json_out=json_out, fallback=status_text(facts))
