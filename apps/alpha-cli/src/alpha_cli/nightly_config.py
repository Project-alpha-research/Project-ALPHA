"""Read `nightly.toml`: which assets, which two spec files, and whether RD-Agent runs too."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class NightlyConfigError(ValueError):
    """The nightly config is missing, unreadable or wrong. The message says what to fix."""


@dataclass(frozen=True)
class NightlyConfig:
    assets: tuple[str, ...]
    rule_spec: Path
    setup_spec: Path
    quick: bool = False
    step_timeout: float = 1800.0
    post_tools: tuple[str, ...] = ()
    rdagent_config: Path | None = None
    rdagent_timeout: float = 14400.0


KEYS = (
    "assets",
    "rule_spec",
    "setup_spec",
    "quick",
    "step_timeout_seconds",
    "post_tools",
    "rdagent_config",
    "rdagent_timeout_seconds",
)


def _strings(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise NightlyConfigError(f"`{key}` must be a list of text values.")
    return tuple(value)


def _file(raw: object, key: str, base: Path) -> Path:
    if not isinstance(raw, str) or not raw:
        raise NightlyConfigError(f"`{key}` must be a file path.")
    path = Path(raw)
    path = path if path.is_absolute() else base / path
    if not path.is_file():
        raise NightlyConfigError(f"`{key}` names {path}, which is not a file.")
    return path


def _seconds(table: dict[str, object], key: str, default: float) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise NightlyConfigError(f"`{key}` must be a number of seconds above zero.")
    return float(value)


def load_config(path: Path) -> NightlyConfig:
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise NightlyConfigError(f"Cannot read {path}: {error}") from error
    unknown = sorted(set(table) - set(KEYS))
    if unknown:
        raise NightlyConfigError(
            f"Unknown setting(s): {', '.join(unknown)}. Known: {', '.join(KEYS)}."
        )
    assets = _strings(table.get("assets"), "assets")
    if not assets:
        raise NightlyConfigError("`assets` needs at least one asset name.")
    base = path.resolve().parent
    quick = table.get("quick", False)
    if not isinstance(quick, bool):
        raise NightlyConfigError("`quick` must be true or false.")
    rdagent = table.get("rdagent_config")
    return NightlyConfig(
        assets=assets,
        rule_spec=_file(table.get("rule_spec"), "rule_spec", base),
        setup_spec=_file(table.get("setup_spec"), "setup_spec", base),
        quick=quick,
        step_timeout=_seconds(table, "step_timeout_seconds", 1800.0),
        post_tools=_strings(table.get("post_tools", []), "post_tools"),
        rdagent_config=_file(rdagent, "rdagent_config", base) if rdagent else None,
        rdagent_timeout=_seconds(table, "rdagent_timeout_seconds", 14400.0),
    )
