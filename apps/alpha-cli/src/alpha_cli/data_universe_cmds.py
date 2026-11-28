"""`alpha data universe`: point-in-time universe membership (survivorship-safe reads)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from alpha_core import DataError

universe_app = typer.Typer(help="Point-in-time universe membership (survivorship-safe reads).")


@universe_app.command("import")
def universe_import(
    name: str,
    csv_path: Path,
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Import symbol,effective_from,effective_to,delisting_return,reason rows as universe NAME."""
    from alpha_cli.data_cmds import _store
    from alpha_data.universe import parse_universe_csv

    try:
        rows = parse_universe_csv(csv_path.read_text(encoding="utf-8"))
        path = _store().write_universe(name, rows)
    except (OSError, DataError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = {
        "name": name,
        "memberships": len(rows),
        "symbols": len({r.symbol for r in rows}),
        "removed": sum(r.effective_to is not None for r in rows),
        "path": str(path),
        "authority": "none",
    }
    if json_out:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(
            f"universe {name}: {payload['memberships']} memberships, {payload['symbols']} symbols, "
            f"{payload['removed']} removed -> {path}"
        )


@universe_app.command("show")
def universe_show(
    name: str,
    as_of: str = typer.Option(
        ..., help="membership date YYYY-MM-DD (from inclusive, to exclusive)"
    ),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """List the members of universe NAME as of a date, including names that later left."""
    from alpha_cli.data_cmds import _store
    from alpha_core import members_as_of

    try:
        when = date.fromisoformat(as_of)
        rows = _store().read_universe(name)
    except (ValueError, DataError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    members = members_as_of(rows, when)
    later_removed = sorted(
        {r.symbol for r in rows if r.effective_to is not None and r.effective_to > when}
        & set(members)
    )
    payload = {
        "name": name,
        "as_of": when.isoformat(),
        "members": members,
        "count": len(members),
        "later_removed": later_removed,
        "authority": "none",
    }
    if json_out:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(
            f"{name} as of {when}: {len(members)} members ({len(later_removed)} later removed)"
        )
        typer.echo(" ".join(members))
