"""Command definitions."""

from __future__ import annotations

from ._base import StrictModel


class CommandOption(StrictModel):
    name: str
    flag: str | None
    type: str
    default: str | int | float | bool | list[str] | None
    required: bool
    multiple: bool
    help: str
    choices: list[str] | None


class CommandArgument(StrictModel):
    name: str
    type: str
    required: bool
    nargs: int


class CommandDefinition(StrictModel):
    id: str
    run_type: str | None
    args: list[CommandArgument]
    options: list[CommandOption]
