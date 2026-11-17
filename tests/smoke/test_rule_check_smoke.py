"""Draft checking and comparison through the installed command on stored rule tests."""

from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_rule_answer_check_and_compare(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    seed_store(data, symbol="SPY", n=400)
    # Strict pull provenance: bar reads reject a partial provenance file.
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    ids = []
    for fast in (5, 8):
        result = alpha(
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
        ).json()["results"][0]
        assert result["error"] is None, result
        ids.append(result["run_id"])
    run_id = ids[0]
    fact = alpha(home, "results", "cite", run_id, "oos_sharpe", "--json").json()
    trials = alpha(home, "results", "cite", run_id, "total_trials", "--json").json()
    answer = tmp_path / "answer.md"
    value = f"{fact['value']:.6f}"
    answer.write_text(
        f"Quick, short history, too few trades. Sharpe {value} [{run_id}:oos_sharpe]. "
        f"{trials['value']} [{run_id}:total_trials] trials."
    )
    assert alpha(home, "results", "check", str(answer), "--json").json()["ok"]
    changed = value[:-1] + str((int(value[-1]) + 1) % 10)
    answer.write_text(answer.read_text().replace(value, changed, 1))
    failed = alpha(home, "results", "check", str(answer), "--json", expect=1).json()
    assert failed["problems"][0]["kind"] == "VALUE_MISMATCH"
    comparison = alpha(home, "results", "compare", *ids, "--json").json()
    for cells in comparison["metrics"].values():
        assert len(cells) == 2
        for cell in cells:
            for fact in cell.values():
                assert {"value", "run_id", "metric", "basis", "reason"} <= fact.keys()
