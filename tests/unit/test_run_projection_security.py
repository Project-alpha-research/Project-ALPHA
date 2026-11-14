from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import run_projection


def test_candle_projection_does_not_forward_provider_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setenv("ALPHA_TIINGO_API_KEY", "must-not-cross-projection-boundary")
    monkeypatch.setenv("QUANTPAD_API_KEY", "must-not-cross-projection-boundary")

    def complete(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"bars": [{key: 1.0 for key in "tohlcv"}]}),
            stderr="",
        )

    monkeypatch.setattr("alpha_cli.run_projection.subprocess.run", complete)

    rows = run_projection._candle_rows("SPY", "snapshot", data_dir=tmp_path, start=None, end=None)

    assert len(rows) == 1
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert environment["ALPHA_DATA_DIR"] == str(tmp_path)
    assert "ALPHA_TIINGO_API_KEY" not in environment
    assert "QUANTPAD_API_KEY" not in environment


def test_candle_projection_reads_a_run_at_its_own_bar_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An intraday run's chart reads its snapshot at its bar size; daily calls are unchanged."""
    commands: list[list[str]] = []

    def complete(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"bars": [{key: 1.0 for key in "tohlcv"}]}), stderr=""
        )

    monkeypatch.setattr("alpha_cli.run_projection.subprocess.run", complete)
    intraday = {"timeframe": "1h", "source_timeframe": "5m", "session": "regular"}
    run_projection._candle_rows(
        "SPY", "snap", data_dir=tmp_path, start=None, end=None, bars=intraday
    )
    run_projection._candle_rows("SPY", "snap", data_dir=tmp_path, start=None, end=None, bars={})
    assert commands[0][-6:] == [
        "--timeframe",
        "1h",
        "--from-timeframe",
        "5m",
        "--session",
        "regular",
    ]
    assert commands[1][1:] == ["data", "candles", "SPY", "--snapshot", "snap", "--json"]
