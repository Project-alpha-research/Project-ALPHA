"""The alpha_cli layer fences name every command file, and every module they name exists."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
PACKAGE = ROOT / "apps" / "alpha-cli" / "src" / "alpha_cli"
FENCES = (
    "spine imports no toolbox, figures or command file directly",
    "toolbox, figures, core and store modules import no command file directly",
)


def _contracts() -> dict[str, dict]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {c["name"]: c for c in config["tool"]["importlinter"]["contracts"]}


def _exists(module: str) -> bool:
    relative = Path(*module.split(".")[1:])
    return (PACKAGE / relative).with_suffix(".py").is_file() or (PACKAGE / relative).is_dir()


def test_every_command_file_is_fenced() -> None:
    contracts = _contracts()
    commands = {f"alpha_cli.{path.stem}" for path in PACKAGE.glob("*_cmds.py")}
    for name in FENCES:
        missing = commands - set(contracts[name]["forbidden_modules"])
        assert not missing, (name, sorted(missing))


def test_fenced_modules_exist_and_only_direct_imports_are_checked() -> None:
    contracts = _contracts()
    for name in FENCES:
        contract = contracts[name]
        assert str(contract["allow_indirect_imports"]).lower() == "true"
        named = set(contract["source_modules"]) | set(contract["forbidden_modules"])
        assert all(_exists(module) for module in named), sorted(
            module for module in named if not _exists(module)
        )
