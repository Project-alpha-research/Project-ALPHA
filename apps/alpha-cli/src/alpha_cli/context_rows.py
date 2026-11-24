"""One shared row limit for the `alpha context show-*` commands: newest 20 rows unless asked."""

from __future__ import annotations

from typing import Annotated, Any

import typer

DEFAULT_ROWS = 20
LIMIT = Annotated[
    int | None, typer.Option("--limit", min=1, help="Show only the newest N rows (default 20).")
]
SHOW_ALL = Annotated[bool, typer.Option("--all", help="Show every stored row.")]


def trim_rows(
    payload: dict[str, Any], *, limit: int | None, show_all: bool, json_out: bool
) -> str | None:
    """Keep the newest rows of ``payload['rows']`` (oldest first); return the line that says so.

    Text output keeps the newest 20 rows. ``--json`` and ``--all`` keep every row unless ``--limit``
    is given. When rows are cut, ``rows_in_all`` is added to the payload.
    """
    rows = payload["rows"]
    keep = limit if limit is not None else None if (show_all or json_out) else DEFAULT_ROWS
    if keep is None or len(rows) <= keep:
        return None
    payload["rows"] = rows[-keep:]
    payload["rows_in_all"] = len(rows)
    return f"{len(rows)} rows in all; use --all (or --limit N) to see more."


def echo_note(note: str | None, json_out: bool) -> None:
    if note and not json_out:
        typer.echo(note)
