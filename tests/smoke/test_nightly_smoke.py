"""`alpha nightly run --only N1` through the installed commands on a tiny synthetic store."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from alpha_data.sessions import daily_session_closes
from alpha_data.store import ParquetStore
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def _seed_exchange_days(data: Path, symbol: str) -> None:
    """Weekday bars on real exchange days, so data health does not fail the synthetic store."""
    days = sorted(daily_session_closes("XNYS", date(2021, 1, 4), date(2022, 8, 31)))
    rng = np.random.default_rng(1)
    close = 100.0 * np.cumprod(1.0 + 0.002 + rng.normal(0.0, 0.01, len(days)))
    opens = np.concatenate(([100.0], close[:-1]))
    bars = pl.DataFrame(
        {
            "ts": [datetime(d.year, d.month, d.day, tzinfo=UTC) for d in days],
            "open": opens,
            "high": np.maximum(opens, close) * 1.002,
            "low": np.minimum(opens, close) * 0.998,
            "close": close,
            "volume": np.full(len(days), 1000.0),
        }
    )
    store = ParquetStore(data / "store")
    store.write_bars(symbol, bars)
    store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")


def test_nightly_rule_path_runs_the_real_commands(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _seed_exchange_days(home / "data", "SPY")
    (tmp_path / "rule.toml").write_text(
        'name = "nightly-ma-cross"\nidea = "Nightly system check"\nassets = ["SPY"]\n'
        '[rule]\nkind = "ma_cross"\nfast = 5\nslow = 20\n'
    )
    (tmp_path / "setup.toml").write_text("")
    config = tmp_path / "nightly.toml"
    config.write_text(
        'assets = ["SPY"]\nrule_spec = "rule.toml"\nsetup_spec = "setup.toml"\nquick = true\n'
    )
    record = alpha(
        home, "nightly", "run", "--config", str(config), "--only", "N1", "--json", timeout=600
    ).json()
    assert record["blocking"] == 0, record["defects"]
    assert record["full"] is False
    ids = [step["id"] for step in record["steps"]]
    assert ids == [
        "N1.next",
        "N1.health.SPY",
        "N1.test",
        "N1.diagnose.SPY",
        "N1.check.SPY",
    ]
    folder = home / "data" / "nightly" / f"{record['date']}-1"
    assert json.loads((folder / "record.json").read_text()) == record
    summary = (folder / "summary.txt").read_text()
    print(summary)
    assert summary.startswith("Last night: 1 of 1 paths worked (partial run: N1 only).")
    shown = alpha(home, "nightly", "status", "--config", str(config), "--json").json()
    assert shown["last"]["run_number"] == 1 and shown["ready"] is False
    assert "oos_sharpe" not in json.dumps(record)
    evidence = {step["id"]: step["evidence"] for step in record["steps"]}
    assert evidence["N1.test"] == "computed"  # the first test of this spec on this data
    assert record["paths_run"] == ["N1"] and shown["ready"] is False
    assert shown["missing"], "a one-path run must say what is missing"
