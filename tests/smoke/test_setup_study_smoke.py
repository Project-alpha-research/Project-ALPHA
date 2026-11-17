"""Installed find/study/cite/repeat path; run outside the builder sandbox."""

from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_setup_study_and_repeat(tmp_path: Path) -> None:
    home = tmp_path / "home"
    data = home / "data"
    data.mkdir(parents=True)
    seed_store(data, symbol="SPY", n=100)
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    spec = home / "setup.toml"
    spec.write_text(
        '[setup]\nname="Smoke"\nidea="Study daily matches"\nassets=["SPY"]\n'
        'timeframe="1D"\nevent="close > 0"\n[study]\nhorizons=[1,5,20]\nprimary=5\n'
    )
    found = alpha(home, "setup", "find", str(spec), "--json").json()
    first = alpha(home, "setup", "study", found["find_id"], "--json").json()
    folder = Path(first["folder"])
    assert {p.name for p in folder.iterdir()} == {
        "outcomes.parquet",
        "summary.json",
        "manifest.json",
        "event-study.png",
    }
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in folder.iterdir()}
    fact = alpha(
        home, "results", "cite", first["study_id"], "setup_mean_net_return", "--json"
    ).json()
    assert fact in first["facts"]
    again = alpha(home, "setup", "study", found["find_id"], "--json").json()
    assert again["study_id"] == first["study_id"] and "repeat" in again["labels"]
    assert before == {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in folder.iterdir()}
    assert alpha(home, "ledger", "summary", "--json").json()["all_trials"] == 1
