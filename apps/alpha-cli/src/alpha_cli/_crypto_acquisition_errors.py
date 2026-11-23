"""Errors raised by the bounded crypto acquisition command."""

from typing import NoReturn

import typer

from alpha_core import DataError


class FixtureAccountingBlocked(DataError):
    """An acquisition option was refused; the command never turns it into a bad parameter."""

    def __init__(self, code: str) -> None:
        super().__init__(f"synthetic backfill accounting blocked: {code}")
        self.reason_code = code


def plain_error(exc: Exception) -> NoReturn:
    """One plain sentence on stderr and exit code 2; no "Invalid value" box."""
    typer.echo(str(exc).strip().splitlines()[0].rstrip(".") + ".", err=True)
    raise typer.Exit(2)
