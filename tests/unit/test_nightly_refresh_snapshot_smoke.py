"""Smoke test: N0 freezes a followed asset with the REAL `alpha data snapshot`, then the REAL
`alpha data verify` accepts the snapshot. No network: the pull is faked, the snapshot is not."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from alpha_cli.nightly_refresh import refresh_assets
from alpha_cli.nightly_steps import Outcome, alpha_argv, subprocess_runner
from alpha_data.adapters.yfinance_adapter import YFinanceAdapter
from alpha_data.store import ParquetStore
from tests.unit.test_nightly import config


def test_the_real_snapshot_command_freezes_the_bars_and_verify_accepts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    rows = [
        {
            "ts": datetime(2026, 11, d, tzinfo=UTC),
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        }
        for d in (2, 3, 4)
    ]
    store = ParquetStore(home / "store")
    store.write_bars("AAA", pl.DataFrame(rows))
    store.write_provenance(
        "AAA",
        source=YFinanceAdapter.name,
        adapter_version=YFinanceAdapter.version,
        parser_version=YFinanceAdapter.parser_version,
    )
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    pulled: list[list[str]] = []

    def runner(argv: Sequence[str], timeout: float) -> Outcome:
        if list(argv)[3:5] == ["data", "snapshot"]:
            return subprocess_runner(argv, timeout)
        pulled.append(list(argv))
        return Outcome(0, "pulled", "", 0.0, False)

    cfg = config(tmp_path, refresh_followed=True)
    steps = refresh_assets(cfg, home, runner, ["AAA"], date(2026, 11, 20))
    freeze = next(s for s in steps if s["id"] == "N0.freeze.AAA")
    assert freeze["state"] == "pass", freeze["defect"]
    assert len(pulled) == 1
    snap_id = freeze["ids"]["snapshot"]
    assert (home / "snapshots" / snap_id / "bars" / "AAA.parquet").is_file()
    verified = subprocess_runner(alpha_argv(["data", "verify", snap_id]), 120)
    assert verified.exit_code == 0 and "integrity OK" in verified.stdout
