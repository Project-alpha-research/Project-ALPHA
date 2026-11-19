"""The `rdagent.toml` model and the argument list it gives the RD-Agent launcher.

This module only assembles the arguments `workers/rdagent/factor_loop_launch.py` already accepts.
It sets no prompt, memory, threshold, cap or counting rule, and reads nothing RD-Agent reads.
It never opens the key file: it only checks that the file exists.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

LAUNCHER = "workers/rdagent/factor_loop_launch.py"
PYTHON = ".venv/bin/python"
KEYFILE_VARIABLE = "ALPHA_RDAGENT_KEYFILE"
SOURCE_VARIABLE = "ALPHA_RDAGENT_SOURCE"
PYTHON_VARIABLE = "ALPHA_FACTOR_PYTHON"
SHELL = f'set -a; . "${KEYFILE_VARIABLE}"; set +a; exec "$@"'
SETUP_HINT = "bash scripts/setup_rdagent.sh --with-factor-runtime"


class RdagentConfigError(Exception):
    """The config is wrong. The message lists every problem in plain words."""


class RdagentConfig(BaseModel):
    """One key per launcher argument. A key left out keeps the launcher's own default."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    working_directory: Path
    data_dir: Path
    gateway_state: Path
    trial_ledger: Path
    funding_dir: Path | None = None
    universe: Path | None = None
    loop_n: int = Field(default=2, ge=1)
    discuss: bool = False
    discuss_wait_minutes: int | None = Field(default=None, ge=0)
    on_timeout: Literal["proceed", "stop"] | None = None
    wall_seconds: float | None = Field(default=None, gt=0)
    chat_route: Literal["codex", "api", "fake"] | None = None
    api_model: str | None = None
    api_price_in_per_mtok: float | None = None
    api_price_out_per_mtok: float | None = None
    api_openrouter: bool = False
    rdagent_source: Path | None = None
    factor_python: Path | None = None
    key_file: Path | None = None


def _absolute(value: object, base: Path) -> object:
    if isinstance(value, str):
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else base / path)
    return value


def _words(error: ValidationError) -> list[str]:
    lines: list[str] = []
    for item in error.errors():
        key = ".".join(str(part) for part in item["loc"]) or "the file"
        if item["type"] == "extra_forbidden":
            lines.append(f"Unknown key '{key}'. Remove it or fix its spelling.")
        elif item["type"] == "missing":
            lines.append(f"The key '{key}' is missing. Add it.")
        else:
            lines.append(f"The key '{key}' is wrong: {item['msg']}.")
    return lines


def _missing(config: RdagentConfig, environ: dict[str, str]) -> list[str]:
    work = config.working_directory
    checks: list[tuple[str, Path | None, bool]] = [
        ("working_directory", work, True),
        ("working_directory's launcher", work / LAUNCHER, False),
        ("working_directory's Python", work / PYTHON, False),
        ("data_dir", config.data_dir, True),
        ("funding_dir", config.funding_dir, True),
        ("universe", config.universe, False),
        ("key_file", config.key_file, False),
        ("trial_ledger's folder", config.trial_ledger.parent, True),
        ("gateway_state's parent folder", config.gateway_state.parent, True),
    ]
    problems = [
        f"The path for {name} does not exist: {path}"
        for name, path, folder in checks
        if path is not None and not (path.is_dir() if folder else path.exists())
    ]
    for name, path, variable in (
        ("rdagent_source", config.rdagent_source, SOURCE_VARIABLE),
        ("factor_python", config.factor_python, PYTHON_VARIABLE),
    ):
        chosen = path or (Path(environ[variable]) if environ.get(variable) else None)
        if chosen is None:
            problems.append(
                f"Set {name} in the config or {variable} in the environment. {SETUP_HINT}"
            )
        elif not chosen.exists():
            problems.append(f"The path for {name} does not exist: {chosen}")
    return problems


def load_config(path: Path, environ: dict[str, str] | None = None) -> RdagentConfig:
    """Read, type-check and path-check the config. Relative paths count from the config's folder."""
    if not path.is_file():
        raise RdagentConfigError(f"The config file does not exist: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise RdagentConfigError(f"The config is not valid TOML: {error}") from error
    path_keys = {
        "working_directory",
        "data_dir",
        "gateway_state",
        "trial_ledger",
        "funding_dir",
        "universe",
        "rdagent_source",
        "factor_python",
        "key_file",
    }
    base = path.resolve().parent
    raw = {k: _absolute(v, base) if k in path_keys else v for k, v in raw.items()}
    try:
        config = RdagentConfig.model_validate(raw)
    except ValidationError as error:
        raise RdagentConfigError("\n".join(_words(error))) from error
    if problems := _missing(config, environ if environ is not None else {}):
        raise RdagentConfigError("\n".join(problems))
    return config


def runs_root(config: RdagentConfig) -> Path:
    return config.data_dir / "runs" / "rdagent"


def next_run(config: RdagentConfig, today: date) -> tuple[str, Path]:
    """A run id of the form YYYYMMDD-NN, one past the runs of that day already in the folder."""
    stem = f"{today:%Y%m%d}"
    root = runs_root(config)
    taken = len(list(root.glob(f"{stem}-*"))) if root.is_dir() else 0
    run_id = f"{stem}-{taken + 1:02d}"
    return run_id, root / run_id


def launcher_argv(config: RdagentConfig, run_dir: Path, run_id: str) -> list[str]:
    """The launcher's own argument list. Each option appears only when the config sets it."""
    argv = [
        PYTHON,
        LAUNCHER,
        "run",
        "--data-dir",
        str(config.data_dir),
        "--run-dir",
        str(run_dir),
        "--gateway-data-dir",
        str(config.gateway_state),
        "--trial-ledger",
        str(config.trial_ledger),
        "--run-id",
        run_id,
        "--loop-n",
        str(config.loop_n),
    ]
    values: list[tuple[str, object | None]] = [
        ("--funding-dir", config.funding_dir),
        ("--universe", config.universe),
    ]
    argv += [x for flag, value in values if value is not None for x in (flag, str(value))]
    if config.discuss:
        argv.append("--discuss")
    later: list[tuple[str, object | None]] = [
        ("--discuss-wait-minutes", config.discuss_wait_minutes),
        ("--discuss-on-timeout", config.on_timeout),
        ("--wall-seconds", None if config.wall_seconds is None else f"{config.wall_seconds:g}"),
        ("--chat-route", config.chat_route),
        ("--api-model", config.api_model),
        ("--api-price-in-per-mtok", config.api_price_in_per_mtok),
        ("--api-price-out-per-mtok", config.api_price_out_per_mtok),
    ]
    argv += [x for flag, value in later if value is not None for x in (flag, str(value))]
    if config.api_openrouter:
        argv.append("--api-openrouter")
    return argv


def child_command(argv: list[str], key_file: Path | None) -> list[str]:
    """The process to start. The key file's path travels in the environment, never in this text."""
    if key_file is None:
        return argv
    return ["bash", "-c", SHELL, "alpha-rdagent", *argv]


def child_environment(config: RdagentConfig, base: dict[str, str]) -> dict[str, str]:
    env = dict(base)
    if config.rdagent_source is not None:
        env[SOURCE_VARIABLE] = str(config.rdagent_source)
    if config.factor_python is not None:
        env[PYTHON_VARIABLE] = str(config.factor_python)
    if config.key_file is not None:
        env[KEYFILE_VARIABLE] = str(config.key_file)
    return env


def _first(pattern: str, path: Path) -> str | None:
    if not path.is_file():
        return None
    match = re.search(pattern, path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return match.group(1) if match else None


def launcher_limits(config: RdagentConfig) -> dict[str, str]:
    """The limits the launcher and gateway already hold, read from their files, not set here."""
    worker = config.working_directory / "workers" / "rdagent"
    launcher, gateway = worker / "factor_loop_launch.py", worker / "model_gateway.py"
    wall = _first(r'"--wall-seconds".*?default=([0-9.]+)', launcher)
    return {
        "calls per run": _first(r"^MAX_CALLS = ([0-9]+)", launcher) or "set by the launcher",
        "seconds per run": str(config.wall_seconds)
        if config.wall_seconds is not None
        else (wall or "set by the launcher"),
        "dollars per run": _dollars(_first(r"run_max_usd: float = ([0-9.]+)", gateway)),
        "dollars per month": _dollars(_first(r"month_max_usd: float = ([0-9.]+)", gateway)),
    }


def _dollars(value: str | None) -> str:
    return f"${float(value):.2f}" if value else "set by the gateway"
