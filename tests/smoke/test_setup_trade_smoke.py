"""Installed CLI: find, trade, cite, then repeat without a second counted trial."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

pytestmark = pytest.mark.smoke


def test_setup_trade_and_repeat(tmp_path: Path) -> None:
    seed_store(tmp_path, n=400)
    store = ParquetStore(tmp_path / "store")
    store.write_provenance("SPY", source="alpaca", adapter_version="1", parser_version="1")
    frame = store.read_bars("SPY").with_columns(
        pl.Series("volume", [float(i % 20 == 5) for i in range(400)])
    )
    store.write_bars("SPY", frame)
    spec = tmp_path / "setup.toml"
    spec.write_text(
        '[setup]\nname="Smoke"\nidea="Smoke trade"\nassets=["SPY"]\n'
        'timeframe="1D"\nevent="volume == 1"\n[exit]\n'
        'stop="5 %"\ntarget="10 %"\ntime_bars=5\n'
    )
    env = {**os.environ, "ALPHA_DATA_DIR": str(tmp_path)}

    def command(*args: str) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, "-m", "alpha_cli", *args, "--json"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        output: dict[str, Any] = json.loads(result.stdout)
        return output

    found = command("setup", "find", str(spec))
    traded = command("setup", "trade", found["find_id"])
    fact = command("results", "cite", traded["trade_id"], "setup_trade_mean_net_return")
    assert fact == next(f for f in traded["facts"] if f["metric"] == fact["metric"])
    folder = Path(traded["folder"])
    original = {p.name: p.read_bytes() for p in folder.iterdir()}
    repeated = command("setup", "trade", found["find_id"])
    assert "repeat" in repeated["labels"]
    assert original == {p.name: p.read_bytes() for p in folder.iterdir()}
    assert command("ledger", "summary")["all_trials"] == 1
