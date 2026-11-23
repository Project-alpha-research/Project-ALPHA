"""`alpha rdagent run` and `status`: start RD-Agent with one command, then watch it.

The command builds the argument list the launcher already accepts and starts that launcher as a
child process. It adds no cap, retry or rule, and it never reads or prints the key file.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from alpha_cli._cli_json import emit
from alpha_cli.rdagent_bench_cmds import bench_app
from alpha_cli.rdagent_defaults import SETUP_HINT
from alpha_cli.rdagent_init import init_text, write_init
from alpha_cli.rdagent_run_config import (
    RdagentConfig,
    RdagentConfigError,
    check_run_id,
    child_command,
    child_environment,
    launcher_argv,
    limits_text,
    load_config,
    next_run,
    runs_root,
)
from alpha_cli.rdagent_run_status import NotARunFolder, read_status, status_text
from alpha_core.config import AlphaSettings

rdagent_app = typer.Typer(help="Start RD-Agent with one command and watch the run.")
rdagent_app.add_typer(bench_app, name="bench")
CONFIG = Annotated[
    Path | None,
    typer.Option("--config", help="An rdagent.toml file. Default: the one in the data folder."),
]
CONFIG_NAME = "rdagent.toml"


def _plain(config: RdagentConfig, argv: list[str], run_dir: Path) -> str:
    route = config.chat_route or "the launcher's default"
    lines = [
        "RD-Agent would start with these settings:",
        f"  data folder: {config.data_dir}",
        f"  universe file: {config.universe or 'the launcher default'}",
        f"  run folder: {run_dir}",
        f"  loops: {config.loop_n if config.loop_n is not None else 'the launcher default'}",
        f"  asks you before coding: {'yes' if config.discuss else 'no'}",
        f"  model route: {route}",
        f"  key file (its contents are never read here): {config.key_file or 'none'}",
        "Limits:",
        *[f"  {line}" for line in limits_text(config)],
        "The exact command (with a key file, it starts inside bash after the file is loaded):",
        f"  cd {shlex.quote(str(config.working_directory))} && {shlex.join(argv)}",
    ]
    return "\n".join(lines)


def _config_path(path: Path | None) -> Path | None:
    """The file to read: the one named, else the data folder's, else none (all defaults)."""
    if path is not None:
        return path
    home_file = AlphaSettings().data_dir / CONFIG_NAME
    return home_file if home_file.is_file() else None


def _load(path: Path | None, runtime: list[str] | None = None) -> RdagentConfig:
    try:
        return load_config(_config_path(path), dict(os.environ), runtime_problems=runtime)
    except RdagentConfigError as error:
        typer.echo(f"The RD-Agent config has a problem:\n{error}", err=True)
        raise typer.Exit(2) from error


@rdagent_app.command("init")
def init(config: CONFIG = None) -> None:
    """Write a config with every path filled in; say which ones are not installed yet."""
    path = config or AlphaSettings().data_dir / CONFIG_NAME
    try:
        paths = write_init(path, dict(os.environ))
    except RdagentConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    typer.echo(init_text(path, paths))


@rdagent_app.command("run")
def run(
    config: CONFIG = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print what would start.")] = False,
    run_id: Annotated[str | None, typer.Option("--run-id", help="Default: date-number.")] = None,
) -> None:
    """Start the RD-Agent factor loop. No config file is needed. --dry-run shows it only."""
    missing_runtime: list[str] = []
    settings = _load(config, missing_runtime if dry_run else None)
    default_id, default_dir = next_run(settings, datetime.now(UTC).date())
    try:
        chosen = check_run_id(run_id) if run_id else default_id
    except RdagentConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    run_dir = runs_root(settings) / chosen if run_id else default_dir
    argv = launcher_argv(settings, run_dir, chosen)
    if dry_run:
        typer.echo(_plain(settings, argv, run_dir))
        if missing_runtime:
            names = [
                name
                for name, path in (
                    ("rdagent_source", settings.rdagent_source),
                    ("factor_python", settings.factor_python),
                )
                if path is None or not path.exists()
            ]
            typer.echo(
                f"The factor runtime is missing ({', '.join(names)}), and a real run needs it. "
                f"Build it with: {SETUP_HINT}"
            )
        typer.echo("Nothing was started.")
        return
    for folder in (runs_root(settings), settings.trial_ledger.parent, settings.gateway_data_dir):
        folder.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Starting RD-Agent. Run folder: {run_dir}")
    typer.echo("When it asks for you, or when it ends, type:")
    typer.echo(f"  alpha ledger proposal --run-dir {shlex.quote(str(run_dir))}")
    typer.echo(f"  alpha rdagent status --run-dir {shlex.quote(str(run_dir))}")
    done = subprocess.run(
        child_command(argv, settings.key_file),
        cwd=settings.working_directory,
        env=child_environment(settings, dict(os.environ)),
        check=False,
    )
    raise typer.Exit(done.returncode)


@rdagent_app.command("status")
def status(
    run_dir: Annotated[
        Path | None, typer.Option("--run-dir", help="Default: the last run.")
    ] = None,
    config: CONFIG = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Say where a run is: working, waiting for you, finished or stopped, and what to type next."""
    folder = run_dir
    if folder is None:
        root = runs_root(_load(config))
        records = list(root.glob("*/launch-command.json")) if root.is_dir() else []
        if not records:
            typer.echo(f"No RD-Agent run was found in {root}.", err=True)
            raise typer.Exit(2)
        folder = max(records, key=lambda record: record.stat().st_mtime_ns).parent
    try:
        value = read_status(folder)
    except NotARunFolder as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    emit(value, json_out=json_out, fallback=status_text(value))
