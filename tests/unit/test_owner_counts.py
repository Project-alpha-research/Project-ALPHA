"""The count sentence and the owner-rule variant table."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine.owner_reading import count_sentence
from alpha_cli.spine.reading import stored_reading
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import IdeaSpec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

RSI = {"indicator": "rsi", "params": [14]}
SMA = {"indicator": "sma", "params": [20]}


def _rule(*conditions: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "owner", "spec": {"long_when": list(conditions)}}


def _idea(rule: dict[str, Any]) -> IdeaSpec:
    return IdeaSpec.model_validate({"assets": ["SPY"], "rule": rule})


def _rsi(level: float) -> dict[str, Any]:
    return {"left": RSI, "op": "<", "right": {"value": level}}


def _dip(level: float) -> dict[str, Any]:
    return _rule(_rsi(level), {"left": {"source": "close"}, "op": ">", "right": SMA})


SHAPE_B = {"left": {"source": "close"}, "op": ">", "right": SMA}
SHAPE_C = {"left": {"indicator": "ema", "params": [10]}, "op": ">", "right": SMA}


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("counts") / "home"
    seed_store(path, symbol="SPY", n=700)
    ParquetStore(path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    return path


@pytest.fixture(scope="module")
def runs(home: Path) -> list[dict[str, Any]]:
    """Three thresholds of one shape, then two other shapes, on one asset."""
    ideas = [
        _idea(_dip(60)),
        _idea(_dip(55)),
        _idea(_dip(50)),
        _idea(_rule(SHAPE_B)),
        _idea(_rule(SHAPE_C)),
    ]
    out = []
    for idea in ideas:
        result = run_idea(idea, home=home, quick=True)["results"][0]
        assert result["error"] is None, result["error"]
        out.append(result)
    return out


def _diag(result: dict[str, Any]) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((Path(result["run_dir"]) / "diagnostics.json").read_text())
    return loaded


def test_k_and_m_on_three_thresholds_of_one_shape_and_two_other_shapes(
    runs: list[dict[str, Any]],
) -> None:
    third = _diag(runs[2])["trials"]
    fam = third["family"]
    scored = fam["variants_scored"]
    assert fam["prior_trials"] == 2
    assert third["owner_counts"] == {
        "asset": "SPY",
        "shape_tests": 2 + 1 + scored,
        "asset_tests": 2 + 1 + scored,
        "n_used": 2 + 1 + scored,
    }
    last = _diag(runs[4])["trials"]
    scored = last["family"]["variants_scored"]
    assert last["family"]["prior_trials"] == 0
    assert last["owner_counts"] == {
        "asset": "SPY",
        "shape_tests": 1 + scored,
        "asset_tests": 4 + 1 + scored,
        "n_used": 4 + 1 + scored,
    }
    assert last["owner_counts"]["n_used"] == last["family"]["n_trials_used"]


def test_the_count_sentence_is_on_the_reading_and_states_n(runs: list[dict[str, Any]]) -> None:
    owner = _diag(runs[4])["trials"]["owner_counts"]
    sentence = (
        f"This rule shape: {owner['shape_tests']} tests on this data. "
        f"All rules on SPY: {owner['asset_tests']} tests. "
        f"The deflated Sharpe uses N = max({owner['shape_tests']}, {owner['asset_tests']})"
        f" = {owner['n_used']}."
    )
    reading = runs[4]["reading"]
    assert reading["count_sentence"] == sentence
    assert count_sentence(owner) == sentence
    manifest = json.loads((Path(runs[4]["run_dir"]) / "manifest.json").read_text())
    assert stored_reading(manifest)["count_sentence"] == sentence
    assert manifest["dsr"]["n_trials"] == owner["n_used"]


def test_a_repeat_of_the_same_test_counts_once(home: Path, runs: list[dict[str, Any]]) -> None:
    again = run_idea(_idea(_dip(60)), home=home, quick=True)["results"][0]
    assert "repeat" in again["labels"] and not again["executed"]
    assert again["reading"]["count_sentence"] == runs[0]["reading"]["count_sentence"]


def test_a_classic_rule_reading_has_no_count_sentence(tmp_path: Path) -> None:
    seed_store(tmp_path, symbol="SPY", n=400)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    idea = IdeaSpec.model_validate(
        {"assets": ["SPY"], "rule": {"kind": "ma_cross", "fast": 5, "slow": 20}}
    )
    result = run_idea(idea, home=tmp_path, quick=True)["results"][0]
    assert result["error"] is None, result["error"]
    assert "count_sentence" not in result["reading"]
    assert "variant_table" not in result["reading"]


def test_owner_variants_run_count_as_trials_and_show_as_a_table(
    runs: list[dict[str, Any]],
) -> None:
    diag = _diag(runs[0])
    names = [v["name"] for v in diag["sensitivity"]["variants"]]
    assert names[0] == "costs_x2"
    param = [v for v in diag["sensitivity"]["variants"] if v["kind"] == "parameter"]
    assert 1 <= len(param) <= 8
    assert "note" not in diag["sensitivity"]
    assert diag["variants_evaluated"] == len(diag["sensitivity"]["variants"])
    table = runs[0]["reading"]["variant_table"]
    assert [row["name"] for row in table] == names
    assert set(table[0]) == {"name", "kind", "sharpe", "total_return", "max_drawdown", "reasons"}
    assert not any(key in runs[0]["reading"] for key in ("best_variant", "verdict"))
