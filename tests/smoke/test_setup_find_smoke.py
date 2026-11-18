"""Installed setup command publishes sheets once and counts repeats."""

from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_setup_find_and_repeat(tmp_path: Path) -> None:
    home = tmp_path / "home"
    data = home / "data"
    data.mkdir(parents=True)
    seed_store(data, symbol="SPY", n=100)
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    spec = home / "setup.toml"
    spec.write_text(
        '[setup]\nname="Smoke"\nidea="Inspect daily matches"\nassets=["SPY"]\n'
        'timeframe="1D"\nevent="close > 0"\n[reference]\nbase="low"\n'
    )
    first = alpha(home, "setup", "find", str(spec), "--json").json()
    assert first["data_health"]["verdict"] == "unchecked"
    assert "data-health-unchecked" in first["labels"]
    folder = Path(first["folder"])
    assert folder == data / "setups" / first["find_id"]
    for name in (
        "spec.json",
        "candidates.parquet",
        "summary.json",
        "manifest.json",
        "sheets/accepted-001.png",
        "sheets/rejected-001.png",
    ):
        assert (folder / name).is_file()
    before = {p: p.stat().st_mtime_ns for p in folder.rglob("*")}
    again = alpha(home, "setup", "find", str(spec), "--json").json()
    assert again["find_id"] == first["find_id"] and "repeat" in again["labels"]
    assert again["trials_total"] == first["trials_total"] + 1
    assert before == {p: p.stat().st_mtime_ns for p in before}
