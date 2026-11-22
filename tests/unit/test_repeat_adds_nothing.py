"""An exact repeat is served from the stored run and adds nothing to any count."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alpha_cli.spine.deflation import same_asset_tests
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_cli.spine.trial_reader import family_counts, spine_snapshot, trials_for_deflation
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


def _counts(home: Path) -> dict[str, Any]:
    snapshot = spine_snapshot(home)
    return {
        "rows": len(read_trials(home)),
        "families": family_counts(snapshot),
        "all": trials_for_deflation(snapshot, "")["all_trials"],
        "asset": same_asset_tests(snapshot, "SPY"),
    }


def test_an_exact_repeat_writes_no_ledger_row_and_moves_no_count(tmp_path: Path) -> None:
    seed_store(tmp_path, symbol="SPY", n=1100)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    first = run_idea(spec, home=tmp_path, quick=True)
    before = _counts(tmp_path)
    again = run_idea(spec, home=tmp_path, quick=True)
    result = again["results"][0]
    assert result["executed"] is False and "repeat" in result["labels"]
    assert result["run_id"] == first["results"][0]["run_id"]
    assert _counts(tmp_path) == before
    assert again["trials_total"] == first["trials_total"] == before["rows"] == 1


def test_a_stored_run_without_a_ledger_row_is_recorded_once(tmp_path: Path) -> None:
    """A run published before its ledger row was written (a crash between the two) is recorded
    by the next attempt, once; it is not skipped as a repeat forever."""
    seed_store(tmp_path, symbol="SPY", n=1100)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    first = run_idea(spec, home=tmp_path, quick=True)
    (tmp_path / "ledger" / "trials.jsonl").write_text("", encoding="utf-8")  # the row was lost
    again = run_idea(spec, home=tmp_path, quick=True)
    rows = read_trials(tmp_path)
    assert again["results"][0]["executed"] is False
    assert [row["run_id"] for row in rows] == [first["results"][0]["run_id"]]
    run_idea(spec, home=tmp_path, quick=True)
    assert len(read_trials(tmp_path)) == 1
