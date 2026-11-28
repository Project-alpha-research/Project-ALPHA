"""data_cmds.py hands snapshots, display and universe commands to their own modules."""

from __future__ import annotations

import importlib
import re

import pytest
from typer.testing import CliRunner

from alpha_cli import data_cmds
from alpha_cli.main import app
from alpha_core import DataError

runner = CliRunner()

MOVED = {
    "alpha_cli.data_snapshots_cmds": ("snapshots", "verify"),
    "alpha_cli.data_display_cmds": (
        "market_overview_command",
        "run_price_command",
        "chart_datasets_command",
    ),
    "alpha_cli.data_universe_cmds": ("universe_app", "universe_import", "universe_show"),
}


def test_moved_names_import_from_their_new_modules() -> None:
    for module_name, names in MOVED.items():
        module = importlib.import_module(module_name)
        for name in names:
            assert callable(getattr(module, name)), f"{module_name}.{name}"


def test_moved_names_are_not_reexported_from_data_cmds() -> None:
    for names in MOVED.values():
        for name in names:
            assert not hasattr(data_cmds, name), f"data_cmds still holds {name}"


def test_kept_helpers_stay_in_data_cmds() -> None:
    for name in ("_store", "_snaps_root", "_adapter", "_candle_provenance", "candles", "snapshot"):
        assert hasattr(data_cmds, name), name


def _row_index(lines: list[str], name: str) -> int:
    pattern = re.compile(rf"^(?:│ |  ){re.escape(name)}\s")
    for index, line in enumerate(lines):
        if pattern.match(line):
            return index
    raise AssertionError(f"{name} not listed in data --help")


def test_data_help_lists_moved_commands_in_the_same_order() -> None:
    result = runner.invoke(app, ["data", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    order = [
        "symbols",
        "snapshots",
        "verify",
        "market-overview",
        "run-price",
        "chart-datasets",
        "universe",
    ]
    positions = [_row_index(lines, name) for name in order]
    assert positions == sorted(positions), dict(zip(order, positions, strict=True))


def test_universe_show_reaches_the_store_through_data_cmds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStore:
        def read_universe(self, name: str) -> list[object]:
            raise DataError(f"no universe {name} sentinel")

    monkeypatch.setattr(data_cmds, "_store", lambda: FakeStore())
    result = runner.invoke(app, ["data", "universe", "show", "demo", "--as-of", "2024-01-02"])
    assert result.exit_code == 2, result.output
    assert "sentinel" in result.output
    assert "Traceback" not in result.output
