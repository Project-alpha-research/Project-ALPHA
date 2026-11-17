"""Installed commands expose immutable price controls and stable idea links."""

from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_price_noise_diagnose_and_cite(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    seed_store(data, n=400)
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    output = alpha(
        home,
        "test",
        "--rule",
        "ma_cross",
        "--param",
        "fast=5",
        "--param",
        "slow=20",
        "--asset",
        "SPY",
        "--quick",
        "--json",
    ).json()
    run = output["results"][0]
    assert run["error"] is None, run
    assert output["trials_total"] == 1
    ledger = data / "ledger/trials.jsonl"
    before = ledger.read_bytes()
    diagnostic = alpha(home, "diagnose", run["run_id"], "--json").json()
    noise = diagnostic["price_noise"]
    assert noise["copies"] == len(noise["runs"]) == 50
    # The installed pass stores the plausibility check; under 30 trades it cannot fire.
    assert diagnostic["closed_oos_trades"] < 30 and diagnostic["plausibility"] == []
    assert diagnostic["sentence"].startswith("Only ") and "too-few-trades" in diagnostic["labels"]
    for field in ("median_sharpe", "p05_sharpe", "p95_sharpe", "sign_flip_share", "median_trades"):
        fact = alpha(
            home, "results", "cite", run["run_id"], f"price_noise_{field}", "--json"
        ).json()
        assert fact["value"] == noise[field]
        assert fact["unit"] in {"ratio", "fraction", "count"}
    listed = alpha(home, "results", "--idea-id", run["idea_id"], "--json").json()
    assert listed["items"][0]["run_id"] == run["run_id"]
    assert "price_noise" in alpha(home, "diagnose", run["run_id"]).stdout
    assert ledger.read_bytes() == before
