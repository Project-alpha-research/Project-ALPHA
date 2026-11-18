"""The installed `alpha data health` checks a stored series, saves it, and spots a change."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_health_report_is_printed_saved_and_goes_out_of_date(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    # The synthetic bars include weekends, so the stock checks must find closed-exchange days.
    seed_store(data, n=60)
    store = ParquetStore(data / "store")
    store.write_provenance("SPY", source="alpaca", adapter_version="1", parser_version="1")

    printed = alpha(home, "data", "health", "SPY@home").stdout
    order = ["Adjustments:", "Timestamps:", "Gaps:", "Survivorship:", "Verdict:", "cannot tell"]
    positions = [printed.index(word) for word in order]
    assert positions == sorted(positions), printed
    assert "Timestamps: fail" in printed and "Verdict: fail" in printed
    assert "on a day the exchange was closed" in printed
    assert "safe" not in printed.lower()

    sidecar = store.root / "health" / "SPY.json"
    saved = json.loads(sidecar.read_bytes())
    assert saved["verdict"] == "fail" and len(saved["source_fingerprint"]) == 64
    assert alpha(home, "data", "health", "SPY@home", "--stored", "--json").json() == saved

    bars = store.root / "bars" / "SPY.parquet"
    raw = bars.read_bytes()
    bars.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    stale = alpha(home, "data", "health", "SPY@home", "--stored", "--json").json()
    assert stale == {"symbol": "SPY", "status": "out of date"}
