"""`alpha lookalike` and `alpha unusual` through the installed program, on a seeded store."""

import json
from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_lookalike_and_unusual_write_labelled_results(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    seed_store(data, symbol="SPY", n=400)
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    ran = alpha(
        home, "lookalike", "--asset", "SPY", "--last", "20", "--max-distance", "1e6", "--json"
    ).json()
    assert ran["schema"] == "AlphaLookalikeV1"
    assert ran["settings"]["max_distance"] == 1e6
    assert ran["search"]["max_distance_basis"] == "--max-distance given by the caller"
    assert len(ran["search"]["items"]) == 10
    assert all(item["end"] < ran["query"]["start"] for item in ran["search"]["items"])
    assert "descriptive, not a forecast" in ran["labels"]
    assert "exploratory" in ran["labels"] and "N=10 matches" in ran["labels"]
    assert any(label.startswith("multiple looks") for label in ran["labels"])
    folder = Path(ran["result_dir"])
    assert json.loads((folder / "result.json").read_text())["facts"] == ran["facts"]
    assert (folder / "figure.png").read_bytes()[:4] == b"\x89PNG"
    fact = next(item for item in ran["facts"] if item["metric"] == "next_5_median")
    assert fact["value"] is not None and fact["reason"] is None
    assert {"value", "basis", "reason", "source", "labels"} <= fact.keys()
    trials = (data / "ledger" / "trials.jsonl").read_text().splitlines()
    assert json.loads(trials[-1])["rule"] == "lookalike"
    assert "exploratory" in json.loads(trials[-1])["labels"]

    few = alpha(home, "lookalike", "--asset", "SPY", "--last", "20", "--json").json()
    withheld = next(item for item in few["facts"] if item["metric"] == "next_5_median")
    if len(few["search"]["items"]) < 5:
        assert withheld["value"] is None and "too few" in withheld["reason"]
    assert few["trial"]["looks"] == 2

    unusual = alpha(home, "unusual", "--asset", "SPY", "--window", "20", "--json").json()
    assert unusual["schema"] == "AlphaUnusualV1"
    assert 0.0 <= unusual["novelty"]["percentile"] <= 100.0
    assert (Path(unusual["result_dir"]) / "figure.png").exists()
    assert "descriptive, not a forecast" in unusual["labels"]

    missing = alpha(home, "unusual", "--asset", "NOPE", "--json", expect=1).json()
    assert missing["error"]["code"] == "UNKNOWN_ASSET"
    assert "alpha unusual" in missing["error"]["next"]
