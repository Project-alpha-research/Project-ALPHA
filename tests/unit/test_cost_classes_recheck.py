"""A recheck of a stored run uses the costs frozen in that run, and an older run still matches."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine import cost_classes as cc
from alpha_cli.spine.recheck import recheck_idea
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import IdeaSpec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


def _idea(costs: object = None) -> IdeaSpec:
    body: dict[str, Any] = {"assets": ["SPY"], "rule": {"kind": "ma_cross", "fast": 5, "slow": 20}}
    if costs is not None:
        body["costs"] = costs
    return IdeaSpec.model_validate(body)


def _home(root: Path, idea: IdeaSpec) -> Path:
    home = root / "home"
    seed_store(home, symbol="SPY", n=1100)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    first = run_idea(idea, home=home, quick=True)
    assert first["results"][0]["error"] is None
    return home


# Every run stored before M99 states the flat default in its stored spec.
FLAT = {"fee_bps": 1.0, "slippage_bps": 2.0}


@pytest.fixture(scope="module")
def stated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _home(tmp_path_factory.mktemp("stated"), _idea(FLAT))


@pytest.fixture(scope="module")
def by_class(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _home(tmp_path_factory.mktemp("by_class"), _idea("class-default"))


def _recheck(home: Path, idea: IdeaSpec) -> dict[str, Any]:
    found: dict[str, Any] = recheck_idea(idea, home=home, quick=True)["results"][0]["recheck"]
    return found


def test_recheck_of_a_run_stored_before_the_costs_line_matches(
    stated: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    shutil.copytree(stated, home)
    path = next((home / "runs").iterdir()) / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["spine"].pop("costs")  # a run written before this change stored no costs block
    if isinstance(manifest.get("reading"), dict):
        manifest["reading"].pop("costs", None)
    path.write_text(json.dumps(manifest))
    found = _recheck(home, _idea(FLAT))
    assert found["computed"] is True
    assert found["match"] is True, found["differences"]


def test_recheck_of_a_class_default_run_uses_the_frozen_costs(
    by_class: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    shutil.copytree(by_class, home)
    stored = json.loads(next((home / "runs").iterdir()).joinpath("manifest.json").read_text())
    used = stored["spine"]["costs"]
    # A later change of the class table must not change what a stored run is rechecked with.
    changed = {key: replace(row, fee_bps=row.fee_bps + 7.0) for key, row in cc.ROWS.items()}
    monkeypatch.setattr(cc, "ROWS", changed)
    monkeypatch.setattr(cc, "CONSERVATIVE", replace(cc.CONSERVATIVE, fee_bps=99.0))
    found = _recheck(home, _idea("class-default"))
    assert found["computed"] is True
    assert found["match"] is True, found["differences"]
    assert used["fee_bps"] not in {99.0, *(row.fee_bps for row in changed.values())}


@pytest.fixture(scope="module")
def plain(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _home(tmp_path_factory.mktemp("plain"), _idea())


def test_a_new_test_without_costs_takes_the_us_large_etf_row(plain: Path) -> None:
    stored = json.loads(next((plain / "runs").iterdir()).joinpath("manifest.json").read_text())
    used = stored["spine"]["costs"]
    assert (used["fee_bps"], used["slippage_bps"]) == (1.0, 1.0)
    assert used["asset_class"] == "us_large_etf"
    assert used["line"].endswith("the default for a US large ETF.")
    assert cc.CLASS_DEFAULT_LABEL in stored["spine"]["labels"]


def test_an_explicit_cost_still_wins(stated: Path) -> None:
    stored = json.loads(next((stated / "runs").iterdir()).joinpath("manifest.json").read_text())
    used = stored["spine"]["costs"]
    assert (used["fee_bps"], used["slippage_bps"]) == (1.0, 2.0)
    assert used["asset_class"] is None  # as every stored stated-cost run of SPY recorded it
    assert cc.CLASS_DEFAULT_LABEL not in stored["spine"]["labels"]


def test_recheck_of_an_idea_file_without_costs_finds_its_run_stored_with_the_flat_default(
    stated: Path,
) -> None:
    # Before M99 a spec without costs meant the flat default, so its runs are stored as `stated`.
    found = _recheck(stated, _idea())
    assert found["computed"] is True
    assert found["match"] is True, found["differences"]
    assert "states no costs" in found["identity_note"]
