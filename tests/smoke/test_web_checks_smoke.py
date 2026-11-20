"""Rule test -> its standard check set -> the web API returns the stored readings."""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha, get_json, web_server

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]

STANDARD_SET = "market-context"


def test_web_api_returns_the_readings_of_a_rule_tests_standard_set(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    for symbol, seed, sigma in (("SPY", 0, 0.01), ("QQQ", 1, 0.02)):
        seed_store(data, symbol=symbol, n=500, seed=seed, sigma=sigma)
        ParquetStore(data / "store").write_provenance(
            symbol, source="alpaca", adapter_version="1", parser_version="1"
        )
    result = alpha(
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
    ).json()["results"][0]
    assert result["error"] is None, result
    run_id = result["run_id"]

    with web_server(home) as base:
        before = get_json(f"{base}/api/runs/{run_id}/checks")
        assert (before["run_id"], before["checks"]) == (run_id, [])
        assert before["reading"]["schema"] == "AlphaReadingV1"

        ran = alpha(home, "tool", "run-set", STANDARD_SET, run_id, "--json").json()
        readings = {item["tool"]: item["reading"] for item in ran}
        assert set(readings) == {"market.attribution", "market.vol_regimes", "market.changepoints"}

        after = get_json(f"{base}/api/runs/{run_id}/checks")
        assert after["run_id"] == run_id
        assert {check["tool"]: check["reading"] for check in after["checks"]} == readings
        assert all(check["outcome"] == "ok" and check["error"] is None for check in after["checks"])
        assert all(check["reading"] and check["recorded_at"] for check in after["checks"])
