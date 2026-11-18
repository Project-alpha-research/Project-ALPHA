"""Read-only projection of one recorded RD-Agent run, mounted as `alpha ledger journey`."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer


class Theme(StrEnum):
    light = "light"
    dark = "dark"


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
