"""A screen says in plain words how many assets it needs; the help names signals (M112)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import _hypothesis_scan as scan
from alpha_cli.main import app
from alpha_core import DataError
from tests.unit.test_hypothesis_scan_signals import request


def test_one_asset_screen_says_how_many_assets_it_needs(tmp_path: Path) -> None:
    one = {**request(), "symbols": ["SPY"]}
    with pytest.raises(DataError) as caught:
        scan.freeze_spec(tmp_path, one)
    message = str(caught.value)
    assert "at least 5 assets" in message
    assert "you gave 1" in message


def test_scan_help_shows_replay_and_signal_names() -> None:
    runner = CliRunner()
    assert "replay" in runner.invoke(app, ["scan", "--help"]).output
    out = runner.invoke(app, ["scan", "hypotheses", "--help"]).output
    text = " ".join(out.replace("│", " ").split())
    for name in (*scan.EQUITY_SIGNALS, *scan.CRYPTO_SIGNALS):
        assert name in text
