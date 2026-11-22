"""`alpha propfirm run` says which rules it used, simulates a realistic evaluation length by
default, and rejects an unknown preset before any data is read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import _propfirm
from alpha_cli.propfirm_cmds import propfirm_app
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

ARGS = ["SPY", "--n-paths", "200", "--seed", "7"]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=1100)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    return tmp_path


def _manifest(home: Path) -> dict[str, object]:
    (path,) = sorted((home / "propfirm").glob("*/manifest.json"))
    found: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return found


def test_the_rules_come_first_and_the_default_length_is_30_trading_days(home: Path) -> None:
    ran = CliRunner().invoke(propfirm_app, [*ARGS, "--firm", "takeprofit"])
    assert ran.exit_code == 0, ran.output
    lines = ran.output.splitlines()
    assert lines[0] == "Rules used (takeprofit preset, approximate; check the firm's own terms):"
    assert "  Profit target: $3,000 on a $50,000 account" in lines
    assert "  Daily loss limit: $1,200 (end of day)" in lines
    assert "  Maximum loss: $2,000, trailing the high-water mark" in lines
    assert "  Time limit: none set by this preset" in lines
    assert (
        "Evaluation length: 30 trading days (the default when the preset sets no time limit; "
        "change it with --horizon)." in lines
    )
    assert "over 30 days" in ran.output
    assert _manifest(home)["horizon_days"] == 30


def test_a_given_horizon_is_used_and_said(home: Path) -> None:
    ran = CliRunner().invoke(propfirm_app, [*ARGS, "--horizon", "60"])
    assert ran.exit_code == 0, ran.output
    assert "Rules used (custom rules):" in ran.output
    assert "  Daily loss limit: none" in ran.output
    assert "Evaluation length: 60 trading days (set with --horizon)." in ran.output
    assert _manifest(home)["horizon_days"] == 60


def test_an_unknown_preset_is_rejected_with_the_valid_names_before_any_read(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*_: object, **__: object) -> None:
        raise AssertionError("an unknown preset read data")

    monkeypatch.setattr(_propfirm, "_returns_from_backtest", never)
    ran = CliRunner().invoke(propfirm_app, [*ARGS, "--firm", "ftmo"])
    assert ran.exit_code != 0
    assert "Unknown firm preset 'ftmo'" in ran.output
    assert "apex, takeprofit, topstep" in ran.output
    assert not (home / "propfirm").exists()
