"""`alpha test --recheck`: compute a stored test again and compare; it writes nothing."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_cli.main import app
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.recheck import MISMATCH_EXIT, recheck_idea
from alpha_cli.spine.recheck_compare import diff_trees
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import IdeaSpec, load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

TOLERANCE = pytest.approx(0.0, rel=1e-9, abs=1e-12)
SPEC_TEXT = 'assets = ["SPY"]\n[rule]\nkind = "ma_cross"\nfast = 5\nslow = 20\n'


def _idea() -> IdeaSpec:
    return load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])


def _listing(root: Path) -> dict[str, tuple[int, int]]:
    """Every path under the home with its size and modification time."""
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
    }


@pytest.fixture(scope="module")
def stored(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A home with a synthetic store and one stored (quick) rule test."""
    home = tmp_path_factory.mktemp("recheck") / "home"
    seed_store(home, symbol="SPY", n=1100)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    first = run_idea(_idea(), home=home, quick=True)
    assert first["results"][0]["error"] is None
    return home


@pytest.fixture
def home(stored: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "home"
    shutil.copytree(stored, copy)
    return copy


def _recheck(home: Path) -> dict[str, Any]:
    found: dict[str, Any] = recheck_idea(_idea(), home=home, quick=True)["results"][0]["recheck"]
    return found


def test_recheck_matches_and_writes_nothing(home: Path) -> None:
    before = _listing(home)
    rows = len(read_trials(home))
    found = _recheck(home)
    assert found["match"] is True and found["computed"] is True
    assert found["differences"] == [] and found["code_changed"] is False
    assert found["bit_identical"] is True
    assert found["seconds"] > 0
    assert _listing(home) == before  # no file, size or modification time changed
    assert len(read_trials(home)) == rows == 1


def test_changed_code_still_matches_and_says_so(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _listing(home)
    monkeypatch.setattr(_runner, "execution_fingerprint", lambda: "f" * 64)
    found = _recheck(home)
    assert found["match"] is True and found["code_changed"] is True
    assert _listing(home) == before


def test_drift_in_a_stored_number_is_named_and_exits_non_zero(
    home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = next((home / "runs").iterdir())
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["oos_metrics"]["sharpe"] += 0.5
    (folder / "manifest.json").write_text(json.dumps(manifest))
    spec = tmp_path / "idea.toml"
    spec.write_text(SPEC_TEXT)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    before = _listing(home)
    done = CliRunner().invoke(app, ["test", str(spec), "--quick", "--recheck", "--json"])
    assert done.exit_code == MISMATCH_EXIT == 4
    found = json.loads(done.stdout)["results"][0]["recheck"]
    assert found["match"] is False
    assert found["differences"][0]["field"] == "manifest.oos_metrics.sharpe"
    assert found["differences"][0]["stored"] == pytest.approx(
        found["differences"][0]["recomputed"] + 0.5
    )
    assert _listing(home) == before


def test_no_stored_result_computes_nothing_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "empty"
    seed_store(home, symbol="SPY", n=1100)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    spec = tmp_path / "idea.toml"
    spec.write_text(SPEC_TEXT)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    before = _listing(home)
    done = CliRunner().invoke(app, ["test", str(spec), "--quick", "--recheck", "--json"])
    assert done.exit_code == 0
    found = json.loads(done.stdout)["results"][0]["recheck"]
    assert found["match"] is None and found["reason"] == "no stored result to compare with"
    assert found["computed"] is False
    text = CliRunner().invoke(app, ["test", str(spec), "--quick", "--recheck"]).stdout
    assert "Run `alpha test" in text and "once first" in text
    assert _listing(home) == before


def test_recheck_refuses_check_data(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = tmp_path / "idea.toml"
    spec.write_text(SPEC_TEXT)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    done = CliRunner().invoke(app, ["test", str(spec), "--recheck", "--check-data", "--json"])
    assert done.exit_code == 1
    assert "writes" in json.loads(done.stdout)["error"]["message"]


def test_executed_is_true_when_computed_and_false_when_served(home: Path, tmp_path: Path) -> None:
    other = tmp_path / "fresh"
    shutil.copytree(home, other)
    shutil.rmtree(other / "runs")
    (other / "ledger" / "trials.jsonl").unlink()
    first = run_idea(_idea(), home=other, quick=True)["results"][0]
    again = run_idea(_idea(), home=other, quick=True)["results"][0]
    assert first["executed"] is True and "repeat" not in first["labels"]
    assert again["executed"] is False and "repeat" in again["labels"]
    row = read_trials(other)[-1]
    assert "executed" not in row  # the ledger row is exactly what it was


def test_code_change_after_a_run_is_repeat_but_executed(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The label says the same test; `executed` says the engine really ran."""
    monkeypatch.setattr(_runner, "execution_fingerprint", lambda: "e" * 64)
    result = run_idea(_idea(), home=home, quick=True)["results"][0]
    assert "repeat" in result["labels"] and result["executed"] is True


def test_numbers_within_tolerance_match_but_are_not_bit_identical() -> None:
    near = diff_trees({"a": 1.0, "n": 3, "w": "x"}, {"a": 1.0 + 1e-13, "n": 3, "w": "x"}, "m")
    assert near.differences == [] and near.bit_identical is False
    far = diff_trees({"a": 1.0, "n": 3}, {"a": 1.0 + 1e-6, "n": 4}, "m")
    assert [d["field"] for d in far.differences] == ["m.a", "m.n"]
    assert far.differences[0]["stored"] == 1.0
    gone = diff_trees({"a": [1, 2]}, {"a": [1]}, "m")
    assert gone.differences == [{"field": "m.a[1]", "stored": 2, "recomputed": None}]
    assert TOLERANCE == 0.0
