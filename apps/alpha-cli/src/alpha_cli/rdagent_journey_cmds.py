"""Read-only projections of recorded RD-Agent runs."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

rdagent_app = typer.Typer(help="Read stored RD-Agent evaluations and their evidence.")


class Theme(StrEnum):
    light = "light"
    dark = "dark"


@rdagent_app.command()
def journey(
    run_dir: Annotated[
        Path, typer.Option(exists=True, file_okay=False, help="Recorded run folder.")
    ],
    factor: Annotated[
        str | None, typer.Option(help="Select all iterations of this factor name.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option(file_okay=False, help="Parent for the journey folder.")
    ] = None,
    theme: Annotated[Theme, typer.Option(help="Figure background.")] = Theme.light,
) -> None:
    """Write seven-step journeys, annotated pictures and their plotted data."""
    from alpha_cli.rdagent_journey import build

    typer.echo(build(run_dir, out, factor, theme == Theme.dark))
