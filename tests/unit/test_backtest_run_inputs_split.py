"""Backtest run inputs and the cross-sectional command live apart; the CLI is unchanged."""

import importlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import _runner, backtest_cmds
from alpha_cli.main import app

MOVED_FUNCTIONS = ["_load_run_bars", "_annualised", "_run_timeframes"]
COMMANDS = ["holdout", "oos", "run", "portfolio", "cross-sectional"]


def test_run_input_helpers_live_in_their_own_module() -> None:
    inputs = importlib.import_module("alpha_cli._backtest_run_inputs")
    for name in MOVED_FUNCTIONS:
        function = getattr(inputs, name)
        assert function.__module__ == "alpha_cli._backtest_run_inputs", name
        assert not hasattr(backtest_cmds, name), f"{name} still in backtest_cmds"
    assert isinstance(inputs._RESEARCH_GATE_OVERRIDE_HELP, str)
    assert backtest_cmds._RESEARCH_GATE_OVERRIDE_HELP is inputs._RESEARCH_GATE_OVERRIDE_HELP
    assert inputs._load_bars is _runner.load_bars
    assert inputs._load_dividends is _runner.load_dividends
    assert backtest_cmds._load_bars is _runner.load_bars
    assert backtest_cmds._load_dividends is _runner.load_dividends


def test_cross_sectional_command_lives_in_its_own_module() -> None:
    module = importlib.import_module("alpha_cli.backtest_cross_sectional_cmds")
    assert module.cross_sectional.__module__ == "alpha_cli.backtest_cross_sectional_cmds"
    registered = module.cross_sectional_app.registered_commands
    assert [command.name for command in registered] == ["cross-sectional"]
    assert registered[0].callback is module.cross_sectional
    assert not hasattr(backtest_cmds, "cross_sectional")


def test_backtest_help_lists_every_command() -> None:
    result = CliRunner().invoke(app, ["backtest", "--help"])
    assert result.exit_code == 0, result.output
    for name in COMMANDS:
        assert name in result.output, name


def test_cross_sectional_help_keeps_its_options() -> None:
    runner = CliRunner(env={"COLUMNS": "200", "TERM": "dumb"})
    result = runner.invoke(backtest_cmds.backtest_app, ["cross-sectional", "--help"])
    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    for option in ("--top-quantile", "--as-of", "--snapshot"):
        assert option in text, option


def test_run_rejects_manifest_and_snapshot_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(
        app,
        ["backtest", "run", "SPY", "--manifest-id", "m1", "--snapshot", "s1"],
    )
    assert result.exit_code == 2, result.output
    assert "mutually exclusive" in " ".join(result.output.split())
