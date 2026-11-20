"""Smoke test: N0 runs the REAL `alpha data pull --json` (in process, provider faked), the pull
freezes the stored bars, and the REAL `alpha data verify` accepts the snapshot. No network."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_cli.nightly_refresh import refresh_assets
from alpha_cli.nightly_steps import Outcome
from alpha_data.adapters.base import FetchResult
from alpha_data.adapters.yfinance_adapter import YFinanceAdapter
from alpha_data.store import ParquetStore
from tests.unit.test_nightly import config


def _frame(days: list[int], close: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [datetime(2026, 11, d, tzinfo=UTC) for d in days],
            "open": [close] * len(days),
            "high": [close] * len(days),
            "low": [close] * len(days),
            "close": [close] * len(days),
            "volume": [1.0] * len(days),
        }
    )


class _Provider(YFinanceAdapter):
    """The yfinance adapter's name and versions, with a canned answer instead of the network."""

    def __init__(self) -> None:
        pass

    def fetch(self, symbol: str, start: date, end: date) -> FetchResult:
        return FetchResult(symbol, _frame([2, 3, 4, 5], 2.0), [])


def test_the_pull_freezes_for_n0_and_the_real_verify_accepts_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    store = ParquetStore(home / "store")
    store.write_bars("AAA", _frame([2, 3, 4], 1.0))
    store.write_provenance(
        "AAA",
        source=YFinanceAdapter.name,
        adapter_version=YFinanceAdapter.version,
        parser_version=YFinanceAdapter.parser_version,
    )
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    monkeypatch.setattr("alpha_cli.data_cmds._ADAPTERS", {"yfinance": _Provider})
    cli = CliRunner()
    seen: list[list[str]] = []

    def runner(argv: Sequence[str], timeout: float) -> Outcome:
        tail = list(argv)[3:]
        seen.append(tail)
        result = cli.invoke(app, tail)
        return Outcome(result.exit_code, result.stdout, "", 0.0, False)

    cfg = config(tmp_path, refresh_followed=True)
    steps = refresh_assets(cfg, home, runner, ["AAA"], date(2026, 11, 20))
    assert [t[:2] for t in seen] == [["data", "pull"]]
    pull = next(s for s in steps if s["id"] == "N0.pull.AAA")
    assert pull["evidence"] == "computed" and pull["state"] == "defect-minor"  # close was revised
    snap_id = pull["ids"]["snapshot"]
    assert (home / "snapshots" / snap_id / "bars" / "AAA.parquet").is_file()
    verified = cli.invoke(app, ["data", "verify", snap_id])
    assert verified.exit_code == 0 and "integrity OK" in verified.stdout
