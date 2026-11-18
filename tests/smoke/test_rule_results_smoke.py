"""Rule test -> stored diagnostics -> list, show and an exact citation."""

from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_rule_results_and_diagnostics(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    seed_store(data, symbol="SPY", n=400)
    # Strict pull provenance: bar reads reject a partial provenance file.
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    ran = alpha(
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
    result = ran["results"][0]
    assert result["error"] is None, result
    run_id = result["run_id"]
    listing = alpha(home, "results", "--json").json()
    assert listing["items"][0]["run_id"] == run_id
    shown = alpha(home, "results", "show", run_id, "--json").json()["runs"][0]
    fact = next(item for item in shown["facts"] if item["metric"] == "oos_sharpe")
    cited = alpha(home, "results", "cite", run_id, "oos_sharpe", "--json").json()
    assert cited == fact
    assert cited["value"] == pytest.approx(result["oos_sharpe"])
    stored = alpha(home, "diagnose", run_id, "--json").json()
    assert shown["audit"] == stored["audit"]
    assert {item["check"] for item in stored["audit"]} == {
        "fills-after-decisions",
        "fills-inside-bar-range",
        "costs-charged",
        "enough-trades",
        "benchmark-present",
        "history-length",
        "artifacts-intact",
        "quick-run",
        "variants-counted",
    }
    assert stored["variants_evaluated"] == result["variants_evaluated"] == 5
    unknown = alpha(home, "results", "cite", run_id, "nonsense", "--json", expect=1).json()
    assert unknown["error"]["code"] == "UNKNOWN_METRIC"
    assert "oos_sharpe" in unknown["error"]["known"]
    assert "alpha results cite" in unknown["error"]["next"]
    skipped = alpha(
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
        "--no-diagnose",
        "--json",
    ).json()["results"][0]
    assert "no-diagnostics" in skipped["labels"]
    assert skipped["run_id"] != run_id
    assert skipped["variants_evaluated"] == 0
    # Dated period facts are recorded even without diagnostics: buy and hold is cited from them.
    facts = {fact["metric"]: fact for fact in skipped["facts"]}
    assert skipped["benchmark_sharpe"] == facts["benchmark_sharpe"]["value"]
    assert facts["benchmark_sharpe"]["period"] == "full_history"
    absent = alpha(home, "diagnose", skipped["run_id"], "--json", expect=1).json()
    assert absent["error"]["code"] == "NO_DIAGNOSTICS"
    assert "alpha test" in absent["error"]["next"]
