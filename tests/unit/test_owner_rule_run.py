"""An owner rule through the whole spine: ledger family, diagnostics, repeat, recheck, follow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.owner_rule import OwnerRule
from alpha_cli.spine.recheck import recheck_idea
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import IdeaSpec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

SPEC: dict[str, Any] = {
    "long_when": [
        {"left": {"indicator": "rsi", "params": [14]}, "op": "<", "right": {"value": 60}},
        {"left": {"source": "close"}, "op": ">", "right": {"indicator": "sma", "params": [20]}},
    ]
}


def _idea(level: int = 60) -> IdeaSpec:
    cond = dict(SPEC["long_when"][0], right={"value": level})
    return IdeaSpec.model_validate(
        {
            "assets": ["SPY"],
            "rule": {"kind": "owner", "spec": {"long_when": [cond, SPEC["long_when"][1]]}},
        }
    )


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("owner") / "home"
    seed_store(path, symbol="SPY", n=700)
    ParquetStore(path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    return path


def test_owner_rule_runs_the_whole_pipeline_and_recheck_matches(home: Path) -> None:
    idea = _idea()
    first = run_idea(idea, home=home, quick=True)
    result = first["results"][0]
    assert result["error"] is None, result["error"]
    assert result["reading"] and "all-in" in result["labels"]
    row = read_trials(home)[0]
    assert row["rule"] == idea.rule.family_key and row["rule"].startswith("owner:")
    assert row["spec_sha256"] == idea.spec_sha256
    run_dir = Path(result["run_dir"])
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text())
    assert diagnostics["trials"]["family"]["family_id"] == f"spine:{idea.rule.family_key}"
    names = [v["name"] for v in diagnostics["sensitivity"]["variants"]]
    assert names[0] == "costs_x2" and 1 < len(names) <= 9
    assert "note" not in diagnostics["sensitivity"]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["spine"]["family"] == idea.rule.family_key
    assert manifest["spine"]["rule_words"].startswith("Long while RSI(14) < 60")
    assert isinstance(idea.rule, OwnerRule)
    assert manifest["rules_spec"] == idea.rule.rules_json
    # Another threshold of the same shape joins the same family and counts as a second try.
    second = run_idea(_idea(55), home=home, quick=True)
    assert read_trials(home)[1]["rule"] == row["rule"]
    assert second["results"][0]["error"] is None
    again = run_idea(idea, home=home, quick=True)
    assert "repeat" in again["results"][0]["labels"] and not again["results"][0]["executed"]
    found = recheck_idea(idea, home=home, quick=True)["results"][0]["recheck"]
    assert found["match"] is True and found["computed"] is True


def test_follow_replay_runs_an_owner_rule(home: Path) -> None:
    from alpha_cli import _runner
    from alpha_cli.follow_replay import replay

    bars, _ = _runner.load_bars("SPY", data_dir=home)
    result = replay(bars, _idea(), len(bars) - 5)
    assert len(result.sessions) == 5
