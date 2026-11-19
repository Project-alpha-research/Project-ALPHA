"""The `rdagent.toml` model and the argument list it gives the RD-Agent launcher.

This module only assembles the arguments `workers/rdagent/factor_loop_launch.py` already accepts.
Each launcher option has one config key with the same name (`--loop-n` is `loop_n`). A key left
out puts no option in the list, so the launcher's own default applies. It sets no prompt, memory,
threshold, cap or counting rule, and reads nothing RD-Agent reads.
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
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# The launcher's optional options, in the order its parser lists them. The key is the option's
# name without "--" and with "_" for "-". `--run-dir` and `--run-id` come from the command.
OPTIONAL_KEYS: tuple[str, ...] = (
    "funding_dir",
    "loop_n",
    "memory_dir",
    "discuss",
    "discuss_wait_minutes",
    "discuss_on_timeout",
    "no_memory",
    "coder_max_loop",
    "run_max_calls",
    "wall_seconds",
    "chat_route",
    "embedding_route",
    "provider_embed_model",
    "provider_embed_usd_per_mtok",
    "accept_unhonoured",
    "api_model",
    "api_price_in_per_mtok",
    "api_price_out_per_mtok",
    "api_openrouter",
    "no_router_session",
    "api_timeout",
    "provider_retries",
    "coding_reasoning_tokens",
    "family_switch_after",
    "universe",
)
PATH_KEYS = frozenset(
    {
        "working_directory",
        "data_dir",
        "gateway_data_dir",
        "trial_ledger",
        "funding_dir",
        "memory_dir",
        "universe",
        "rdagent_source",
        "factor_python",
        "key_file",
    }
)


class RdagentConfigError(Exception):
    """The config is wrong. The message lists every problem in plain words."""


class RdagentConfig(BaseModel):
    """One key per launcher option, same name. A key left out keeps the launcher's own default.

    Numbers keep the type written in the file (`10800` stays `10800`), so the launcher receives
    the same text the owner would type. The launcher does its own range checks.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    working_directory: Path
    data_dir: Path
    gateway_data_dir: Path
    trial_ledger: Path
    funding_dir: Path | None = None
    loop_n: int | None = None
    memory_dir: Path | None = None
    discuss: bool = False
    discuss_wait_minutes: int | None = None
    discuss_on_timeout: Literal["proceed", "stop"] | None = None
    no_memory: bool = False
    coder_max_loop: int | None = None
    run_max_calls: int | None = None
    wall_seconds: int | float | None = Field(default=None, union_mode="smart")
    chat_route: Literal["codex", "api", "fake"] | None = None
    embedding_route: Literal["local", "provider", "ollama", "fake"] | None = None
    provider_embed_model: str | None = None
    provider_embed_usd_per_mtok: int | float | None = Field(default=None, union_mode="smart")
    accept_unhonoured: str | None = None
    api_model: str | None = None
    api_price_in_per_mtok: int | float | None = Field(default=None, union_mode="smart")
    api_price_out_per_mtok: int | float | None = Field(default=None, union_mode="smart")
    api_openrouter: bool = False
    no_router_session: bool = False
    api_timeout: int | float | None = Field(default=None, union_mode="smart")
    provider_retries: int | None = None
    coding_reasoning_tokens: int | None = None
    family_switch_after: int | None = None
    universe: Path | None = None
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
        ("gateway_data_dir's parent folder", config.gateway_data_dir.parent, True),
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
    base = path.resolve().parent
    raw = {k: _absolute(v, base) if k in PATH_KEYS else v for k, v in raw.items()}
    try:
        config = RdagentConfig.model_validate(raw)
    except ValidationError as error:
        raise RdagentConfigError("\n".join(_words(error))) from error
    if problems := _missing(config, environ if environ is not None else {}):
        raise RdagentConfigError("\n".join(problems))
    return config


def runs_root(config: RdagentConfig) -> Path:
    return config.data_dir / "runs" / "rdagent"


def check_run_id(run_id: str) -> str:
    if not RUN_ID.fullmatch(run_id):
        raise RdagentConfigError(
            f"The run id '{run_id}' is not allowed. Use letters, digits, '.', '_' and '-' only."
        )
    return run_id


def next_run(config: RdagentConfig, today: date) -> tuple[str, Path]:
    """A run id of the form YYYYMMDD-NN, one past the highest number of that day in the folder."""
    stem = f"{today:%Y%m%d}"
    root = runs_root(config)
    numbers = [
        int(match.group(1))
        for path in (root.glob(f"{stem}-*") if root.is_dir() else [])
        if (match := re.fullmatch(rf"{stem}-([0-9]+)", path.name))
    ]
    run_id = f"{stem}-{max(numbers, default=0) + 1:02d}"
    return run_id, root / run_id


def launcher_argv(config: RdagentConfig, run_dir: Path, run_id: str) -> list[str]:
    """The launcher's own argument list. An optional option appears only when the config sets it."""
    values = config.model_dump()
    argv = [PYTHON, LAUNCHER, "run", "--data-dir", str(config.data_dir)]
    for key in OPTIONAL_KEYS:
        value = values[key]
        flag = "--" + key.replace("_", "-")
        if value is True:
            argv.append(flag)
        elif value is not None and value is not False:
            argv += [flag, str(value)]
        if key == "funding_dir":
            argv += ["--run-dir", str(run_dir), "--gateway-data-dir", str(config.gateway_data_dir)]
            argv += ["--trial-ledger", str(config.trial_ledger), "--run-id", run_id]
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


def limits_text(config: RdagentConfig) -> list[str]:
    """The limits in plain words. A number is shown only when this config passes it on."""
    calls = config.run_max_calls
    seconds = config.wall_seconds
    return [
        f"model calls per run: {calls if calls is not None else 'set by the launcher'}",
        f"seconds per run: {seconds if seconds is not None else 'set by the launcher'}",
        "dollars per run and per month: set by the gateway; this command does not change them",
    ]
