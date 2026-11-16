"""Two installed rule tests expose growing recorded family counts."""

from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_family_deflation_grows(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    seed_store(home / "data", symbol="SPY", n=400)
    ParquetStore(home / "data/store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    counts = []
    for fast in (5, 6):
        output = alpha(
            home,
            "test",
            "--rule",
            "ma_cross",
            "--param",
            f"fast={fast}",
            "--param",
            "slow=20",
            "--asset",
            "SPY",
            "--quick",
            "--json",
        ).json()
        result = output["results"][0]
        assert result["error"] is None, result
        run_id = result["run_id"]
        counts.append(
            alpha(home, "results", "cite", run_id, "family_trials", "--json").json()["value"]
        )
        shown = alpha(home, "results", "show", run_id, "--json").json()["runs"][0]
        assert shown["family"]["trials_at_run"] == counts[-1]
        assert shown["family"]["now"]["reader_trials"] == len(counts)
    assert counts[1] > counts[0]
