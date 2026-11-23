"""Shared CLI JSON output and object options."""

from __future__ import annotations

import json
from typing import cast

import typer


def emit(value: object, *, json_out: bool, fallback: str) -> None:
    if json_out:
        # The screen says `alpha`; a stored sentence may still say `uv run alpha` (it stays stored).
        text = json.dumps(value, sort_keys=True, allow_nan=False)
        typer.echo(text.replace("uv run alpha ", "alpha "))
    else:
        # Stored sentences may still say `uv run alpha`; the screen says `alpha`, the stored text
        # stays as written.
        typer.echo(fallback.replace("uv run alpha ", "alpha "))


def json_object_option(raw: str, label: str) -> dict[str, object]:
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{label} must be a valid JSON object") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise typer.BadParameter(f"{label} must be a valid JSON object")
    return cast(dict[str, object], value)
