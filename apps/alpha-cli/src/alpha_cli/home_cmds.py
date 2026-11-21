"""`alpha home backup`, `verify-backup` and `restore`: one checked archive of the data home.

The commands only print. The work and its rules are in `home_backup`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha_cli._cli_json import emit
from alpha_cli.home_backup import HomeBackupError, backup, restore, verify
from alpha_cli.home_disk import human
from alpha_core.config import AlphaSettings

home_app = typer.Typer(help="Back up the data home, check a backup, restore it to a new folder.")
JSON = Annotated[bool, typer.Option("--json", help="Print the same facts as one JSON object.")]


def _refuse(error: HomeBackupError) -> typer.Exit:
    typer.echo(str(error), err=True)
    return typer.Exit(2)


@home_app.command("backup")
def backup_command(
    folder: Annotated[Path, typer.Argument(help="Folder for the archive, outside the data home.")],
    json_out: JSON = False,
) -> None:
    """Write one archive of the whole data home, with a manifest and its SHA-256."""
    try:
        facts = backup(AlphaSettings().data_dir, folder)
    except HomeBackupError as error:
        raise _refuse(error) from error
    left = facts["excluded"]
    lines = [
        f"Backup written: {facts['archive']} ({human(facts['archive_bytes'])}).",
        f"It holds {facts['files']} files ({human(facts['total_bytes'])}) "
        f"and {facts['folders']} folders.",
        f"Its SHA-256 is in {facts['sha256_file']}.",
        "Nothing was left out." if not left else f"Left out ({len(left)}):",
        *(f"  {row['path']}: {row['reason']}" for row in left),
        f"Check it now: alpha home verify-backup {facts['archive']}",
    ]
    emit(facts, json_out=json_out, fallback="\n".join(lines))


@home_app.command("verify-backup")
def verify_command(
    archive: Annotated[Path, typer.Argument(help="The .tar file `alpha home backup` wrote.")],
    json_out: JSON = False,
) -> None:
    """Read a backup again and check every file against its manifest. Extracts nothing."""
    try:
        facts = verify(archive)
    except HomeBackupError as error:
        raise _refuse(error) from error
    head = "Backup check passed" if facts["ok"] else "BACKUP CHECK FAILED"
    lines = [
        f"{head}: {facts['files_checked']} files checked, {facts['files_ok']} match the "
        f"manifest, {facts['files_bad']} do not. Left out when it was made: {facts['excluded']}.",
        f"The archive's own SHA-256: {facts['archive_hash']}.",
        *(f"  {problem}" for problem in facts["problems"]),
    ]
    emit(facts, json_out=json_out, fallback="\n".join(lines))
    raise typer.Exit(0 if facts["ok"] else 1)


@home_app.command("restore")
def restore_command(
    archive: Annotated[Path, typer.Argument(help="The .tar file `alpha home backup` wrote.")],
    folder: Annotated[Path, typer.Argument(help="A new or empty folder. Never the live home.")],
    json_out: JSON = False,
) -> None:
    """Check a backup, then write it into a NEW EMPTY folder. The live home is never changed."""
    try:
        facts = restore(archive, folder, AlphaSettings().data_dir)
    except HomeBackupError as error:
        raise _refuse(error) from error
    words = (
        f"Restored {facts['files']} files into {facts['target']}. Every file matched the "
        "manifest. The live data home was not changed. To look at the copy, run a command "
        f"with ALPHA_DATA_DIR={facts['target']}"
    )
    emit(facts, json_out=json_out, fallback=words)
