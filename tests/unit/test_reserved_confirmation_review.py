"""A finished confirmation, checked from the sides: plan facts, near-duplicates and reuse.

One temporary home with one confirmed rule test (diagnostics on); no real slot.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import follow_source
from alpha_cli.spine import reserve
from alpha_cli.spine.confirm import plan
from alpha_cli.spine.confirm_run import confirm_run
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import read_json
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


def _test(home: Path, rule: str, *params: str, diagnose: bool = False) -> str:
    spec = load_spec(None, rule=rule, param=list(params), asset=["SPY"])
    out = run_idea(spec, home=home, quick=True, no_diagnose=not diagnose)["results"][0]
    assert out["error"] is None, out
    return str(out["run_id"])


@pytest.fixture(scope="module")
def done(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    home = tmp_path_factory.mktemp("confirmed")
    seed_store(home, symbol="SPY", n=1600)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    run_id = _test(home, "ma_cross", "fast=5", "slow=20", diagnose=True)
    found = plan(home, run_id)
    yield {"home": home, "run_id": run_id, "output": confirm_run(home, run_id), "plan": found}


def test_the_owner_reads_the_code_state_slots_and_earlier_confirmations(
    done: dict[str, Any],
) -> None:
    assert done["plan"]["slots"] == {"used": 0, "left": 10, "total": 10}
    assert done["plan"]["earlier_confirmations"] == [] and done["plan"]["code_changed"] is False
    assert done["output"]["slot"] == 1 and done["output"]["slots_left"] == 9
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


def test_a_finished_confirmation_is_only_shown_again(
    done: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*_: Any, **__: Any) -> None:
        raise AssertionError("a finished confirmation read reserved bars again")

    monkeypatch.setattr(reserve, "open_with_receipt", never)
    again = confirm_run(done["home"], done["run_id"])
    assert again["reserved"] == done["output"]["reserved"]
