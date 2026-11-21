"""A finished confirmation, attacked from the sides: words, near-duplicates, reuse and removal.

One temporary home with one confirmed rule test (diagnostics on), the Touch ID test double, no
real slot. Each test reads that home, or a copy of it when it edits the store.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import follow_source, reserved_slots
from alpha_cli.spine import reserve
from alpha_cli.spine.confirm import plan, summary
from alpha_cli.spine.confirm_run import confirm_run
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import read_json
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.fixtures.reserved_owner import enroll, install_double, owner_yes


def _test(home: Path, rule: str, *params: str, diagnose: bool = False) -> str:
    spec = load_spec(None, rule=rule, param=list(params), asset=["SPY"])
    out = run_idea(spec, home=home, quick=True, no_diagnose=not diagnose)["results"][0]
    assert out["error"] is None, out
    return str(out["run_id"])


@pytest.fixture(scope="module")
def done(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    home = tmp_path_factory.mktemp("confirmed")
    with pytest.MonkeyPatch.context() as patch:
        install_double(patch)
        seed_store(home, symbol="SPY", n=1600)
        ParquetStore(home / "store").write_provenance(
            "SPY", source="alpaca", adapter_version="1", parser_version="1"
        )
        run_id = _test(home, "ma_cross", "fast=5", "slow=20", diagnose=True)
        enroll(home)
        found = plan(home, run_id)
        payload = {"run_id": run_id, "reserved_end": found["frozen"]["reserved_end"]}
        # Words that do not describe the test (a link not made by `alpha confirm request`).
        wrong = owner_yes(
            home, {**payload, "summary": "Approve a paper trade."}, found["frozen"]["artifact_hash"]
        )
        with pytest.raises(SpineError, match="No slot was used") as refused:
            confirm_run(home, run_id, authorization_id=wrong)
        spent_after_wrong = len(reserved_slots.receipts(home))
        output = confirm_run(
            home,
            run_id,
            authorization_id=owner_yes(home, payload, found["frozen"]["artifact_hash"]),
        )
        yield {
            "home": home,
            "run_id": run_id,
            "output": output,
            "plan": found,
            "refused": refused.value.payload["code"],
            "spent_after_wrong": spent_after_wrong,
            "patch": patch,
        }


def test_words_the_owner_did_not_read_spend_nothing(done: dict[str, Any]) -> None:
    assert done["refused"] == "OWNER_WORDS_DIFFER" and done["spent_after_wrong"] == 0
    assert done["output"]["slot"] == 1


def test_the_owner_reads_the_code_state_slots_and_earlier_confirmations(
    done: dict[str, Any],
) -> None:
    words = summary(done["plan"])
    assert "Slots: 0 of 10 used, 10 left." in words and "Already confirmed: none." in words
    assert "The code is the same as for the stored test." in words
    assert done["plan"]["code_changed"] is False
    other = _test(done["home"], "tsmom", "lookback=60", "skip=5")
    later = plan(done["home"], other)
    assert later["earlier_confirmations"] == [
        {
            "slot": 1,
            "rule": "ma_cross",
            "symbol": "SPY",
            "run_id": done["run_id"],
            "date": done["output"]["completed_at"][:10],
        }
    ]
    assert "Already confirmed: slot 1: ma_cross on SPY" in summary(later)


def test_the_confirmation_runs_no_parameter_neighbours(done: dict[str, Any]) -> None:
    rdir = done["home"] / "runs" / done["output"]["confirmation_run_id"]
    sensitivity = read_json(rdir / "diagnostics.json")["sensitivity"]
    assert [v["kind"] for v in sensitivity["variants"]] == ["costs"]
    assert "no parameter neighbours" in sensitivity["note"]
    earlier = read_json(done["home"] / "runs" / done["run_id"] / "diagnostics.json")
    assert "parameter" in {v["kind"] for v in earlier["sensitivity"]["variants"]}


def test_a_confirmation_run_cannot_be_followed(done: dict[str, Any]) -> None:
    with pytest.raises(SpineError, match="one look at the reserved period"):
        follow_source.rule_test_source(done["home"], done["output"]["confirmation_run_id"])
    assert follow_source.rule_test_source(done["home"], done["run_id"]).source_id == done["run_id"]


def test_a_removed_last_slot_is_found_from_the_ledger(done: dict[str, Any], tmp_path: Path) -> None:
    home = tmp_path / "copy"
    shutil.copytree(done["home"], home)
    with sqlite3.connect(home / "control" / "workstation.sqlite3") as connection:
        connection.execute("DELETE FROM reserved_period_results")
        connection.execute("DELETE FROM reserved_period_receipts")
    assert reserved_slots.receipts(home) == []
    with pytest.raises(SpineError, match="changed outside ALPHA"):
        plan(home, done["run_id"])


def test_a_finished_confirmation_is_only_shown_again(
    done: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*_: Any, **__: Any) -> None:
        raise AssertionError("a finished confirmation read reserved bars again")

    monkeypatch.setattr(reserve, "open_with_receipt", never)
    again = confirm_run(done["home"], done["run_id"], authorization_id=None)
    assert again["reserved"] == done["output"]["reserved"]
