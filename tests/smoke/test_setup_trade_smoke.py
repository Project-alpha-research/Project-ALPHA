"""Installed find/trade/cite/repeat path; run outside the builder sandbox."""

from pathlib import Path

import polars as pl
import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_setup_trade_and_repeat(tmp_path: Path) -> None:
    home = tmp_path / "home"
    data = home / "data"
    data.mkdir(parents=True)
    seed_store(data, symbol="SPY", n=400)
    store = ParquetStore(data / "store")
    store.write_provenance("SPY", source="alpaca", adapter_version="1", parser_version="1")
    frame = store.read_bars("SPY").with_columns(
        pl.Series("volume", [float(i % 20 == 5) for i in range(400)])
    )
    store.write_bars("SPY", frame)
    spec = home / "setup.toml"
    spec.write_text(
        '[setup]\nname="Smoke"\nidea="Smoke trade"\nassets=["SPY"]\n'
        'timeframe="1D"\nevent="volume == 1"\n[exit]\n'
        'stop="5 %"\ntarget="10 %"\ntime_bars=5\n'
    )
    found = alpha(home, "setup", "find", str(spec), "--json").json()
    traded = alpha(home, "setup", "trade", found["find_id"], "--json").json()
    folder = Path(traded["folder"])
    assert {p.name for p in folder.iterdir()} == {
        "trades.parquet",
        "summary.json",
        "manifest.json",
        "trades.png",
    }
    assert traded["costs"]["SPY"] == {"fee_bps": 1.0, "slippage_bps": 2.0}
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in folder.iterdir()}
    fact = alpha(
        home, "results", "cite", traded["trade_id"], "setup_trade_mean_net_return", "--json"
    ).json()
    assert fact in traded["facts"]
    again = alpha(home, "setup", "trade", found["find_id"], "--json").json()
    assert again["trade_id"] == traded["trade_id"] and "repeat" in again["labels"]
    assert before == {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in folder.iterdir()}
    assert alpha(home, "ledger", "summary", "--json").json()["all_trials"] == 1
