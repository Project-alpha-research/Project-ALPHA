"""`alpha confirm run` in plain mode: a refusal prints its reason, and the slot line appears only
when the receipt is written."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import confirm_cmds, reserved_slots
from alpha_cli.spine import recheck, recheck_compare
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

SPENDING = "Spending 1 slot now."


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=1600)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    return str(run_idea(spec, home=tmp_path, quick=True, no_diagnose=True)["results"][0]["run_id"])


def test_a_refused_run_prints_the_reason_and_spends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _home(tmp_path, monkeypatch)

    def drifted(stored: Path, fresh: Path) -> recheck_compare.Comparison:
        found = recheck_compare.compare_runs(stored, fresh)
        found.differences.append(
            {"field": "manifest.oos_metrics.sharpe", "stored": 1, "recomputed": 2}
        )
        return found

    monkeypatch.setattr(recheck, "compare_runs", drifted)
    ran = CliRunner().invoke(confirm_cmds.confirm_app, ["run", run_id])
    assert ran.exit_code == 1
    assert "not the same as stored run" in ran.output and "No slot was used." in ran.output
    assert SPENDING not in ran.output
    assert reserved_slots.receipts(tmp_path) == []


def test_the_slot_line_is_printed_when_the_receipt_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _home(tmp_path, monkeypatch)
    seen: list[Any] = []
    take = reserved_slots.take_slot

    def spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append("taken")
        return take(*args, **kwargs)

    monkeypatch.setattr(reserved_slots, "take_slot", spy)
    ran = CliRunner().invoke(confirm_cmds.confirm_app, ["run", run_id])
    assert ran.exit_code == 0, ran.output
    assert seen == ["taken"]
    assert ran.output.count(SPENDING) == 1
    assert ran.output.index("It cannot be undone.") < ran.output.index(SPENDING)
    assert ran.output.index(SPENDING) < ran.output.index("Slot 1 of 10")


def test_an_older_run_of_the_test_names_the_newest_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli import _runner

    run_id = _home(tmp_path, monkeypatch)
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    with pytest.MonkeyPatch.context() as patch:  # the same test after a code change: a new run
        patch.setattr(_runner, "execution_fingerprint", lambda: "f" * 64)
        newer = str(
            run_idea(spec, home=tmp_path, quick=True, no_diagnose=True)["results"][0]["run_id"]
        )
    assert newer != run_id
    ran = CliRunner().invoke(confirm_cmds.confirm_app, ["run", run_id])
    assert ran.exit_code == 1
    assert f"alpha confirm run {newer}" in ran.output and "No slot was used." in ran.output
    assert "0 differences" not in ran.output and SPENDING not in ran.output
    assert reserved_slots.receipts(tmp_path) == []
