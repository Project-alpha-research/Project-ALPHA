"""Every module and attribute named by a CLI string resolves, so a move that forgets a string fails."""

from __future__ import annotations

import importlib
import importlib.util

import pytest

import alpha_cli.main as entry

# Modules the product starts with `python -m`.
MODULE_TARGETS = ("alpha_cli.main", "alpha_cli.native_supervisor", "alpha_cli.assistant_worker")


@pytest.mark.parametrize(
    ("name", "module", "attribute"),
    [*entry.GROUPS, *entry.COMMANDS],
    ids=lambda value: str(value),
)
def test_registry_entry_resolves(name: str, module: str, attribute: str) -> None:
    loaded = importlib.import_module(module)
    assert hasattr(loaded, attribute), f"{name}: {module} has no attribute {attribute}"


@pytest.mark.parametrize("module", MODULE_TARGETS)
def test_python_m_target_imports(module: str) -> None:
    assert importlib.util.find_spec(module) is not None, f"no module {module}"
    importlib.import_module(module)
