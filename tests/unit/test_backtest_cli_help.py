"""The backtest CLI lists every command and keeps its options and checks."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import backtest_cmds
from alpha_cli.main import app

COMMANDS = ["holdout", "oos", "run", "portfolio", "cross-sectional"]


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
