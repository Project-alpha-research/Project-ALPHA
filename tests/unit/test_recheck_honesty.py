"""`alpha test --recheck` honesty: it writes nothing on any branch, it compares every stored
fact, and it compares only with a stored run of the same test, data and engine settings."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli.spine import recheck
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.recheck import DATA_CHANGED, OTHER_SETTINGS, recheck_idea
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.unit.test_recheck import _idea, _listing


@pytest.fixture(scope="module")
def stored(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One stored quick test, then a test of another idea of the same family after it."""
    home = tmp_path_factory.mktemp("honesty") / "home"
    seed_store(home, symbol="SPY", n=1100)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    assert run_idea(_idea(), home=home, quick=True)["results"][0]["error"] is None
    other = load_spec(None, rule="ma_cross", param=["fast=8", "slow=30"], asset=["SPY"])
    assert run_idea(other, home=home, quick=True)["results"][0]["error"] is None
    return home


@pytest.fixture
def home(stored: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "home"
    shutil.copytree(stored, copy)
    return copy


def _found(home: Path, quick: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = recheck_idea(_idea(), home=home, quick=quick)["results"][0]
    return result


def _run_folder(home: Path) -> Path:
    row = read_trials(home)[0]
    return home / "runs" / str(row["run_id"])


def test_a_later_row_of_the_same_family_does_not_change_the_recomputed_trial_count(
    home: Path,
) -> None:
    """The stored run counted one ledger row fewer than the ledger has now; the recheck uses
    the ledger as it was, so it matches. With today's ledger the count would differ."""
    rows = read_trials(home)
    assert len(rows) == 2
    (home / "ledger" / "trials.jsonl.lock").unlink()  # a recheck must not create the lock file
    before = _listing(home)
    found = _found(home)["recheck"]
    assert found["match"] is True, found["differences"]
    assert found["compared_with"] == rows[0]["run_id"]
    assert _listing(home) == before


def test_todays_ledger_would_give_another_trial_count_and_a_difference(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test above: the later row really changes the count."""
    real = recheck._earlier_ledger
    monkeypatch.setattr(recheck, "_earlier_ledger", lambda h, s, upto: real(h, s, 99))
    found = _found(home)["recheck"]
    assert found["match"] is False
    assert any("trials" in d["field"] or "dsr" in d["field"] for d in found["differences"])


def test_a_crash_mid_way_removes_the_scratch_folder_and_writes_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch_root))

    def crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("crash after the run was written")

    monkeypatch.setattr(recheck, "compare_runs", crash)
    before = _listing(home)
    result = _found(home)
    assert result["error"] == "RuntimeError: crash after the run was written"
    assert result["executed"] is False and result["recheck"]["match"] is None
    assert list(scratch_root.iterdir()) == []
    assert _listing(home) == before


def test_other_engine_settings_are_nothing_to_compare_and_compute_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recheck, "write_run", lambda *a, **k: pytest.fail("the engine ran"))
    before = _listing(home)
    result = _found(home, quick=False)
    assert result["recheck"]["match"] is None and result["recheck"]["reason"] == OTHER_SETTINGS
    assert result["executed"] is False and _listing(home) == before


def test_changed_data_is_said_plainly_and_is_neither_a_match_nor_a_mismatch(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ParquetStore(home / "store")
    frame = store.read_bars("SPY")
    store.write_bars("SPY", frame.with_columns(pl.col("volume") + 1.0))
    monkeypatch.setattr(recheck, "write_run", lambda *a, **k: pytest.fail("the engine ran"))
    before = _listing(home)
    result = _found(home)
    assert result["recheck"]["match"] is None and result["recheck"]["reason"] == DATA_CHANGED
    assert _listing(home) == before


def _edit_manifest(home: Path, change: Any) -> None:
    path = _run_folder(home) / "manifest.json"
    manifest = json.loads(path.read_text())
    change(manifest)
    path.write_text(json.dumps(manifest))


def _fields(home: Path) -> list[str]:
    found = _found(home)["recheck"]
    assert found["match"] is False and found["computed"] is True
    return [str(d["field"]) for d in found["differences"]]


def test_one_changed_trade_price_is_a_difference_with_the_same_trade_count(home: Path) -> None:
    path = _run_folder(home) / "trades.parquet"
    frame = pl.read_parquet(path)
    column = next(n for n, t in frame.schema.items() if t == pl.Float64)
    frame.with_columns(pl.col(column) * 1.01).write_parquet(path)
    assert any(f.startswith(f"trades.parquet.columns.{column}") for f in _fields(home))


def test_fold_boundary_cost_and_data_fingerprint_are_compared(home: Path) -> None:
    def change(manifest: dict[str, Any]) -> None:
        manifest["folds"][0]["test_end"] += 1
        manifest["metadata"]["fee_bps"] += 1.0
        manifest["source_fingerprint"] = "0" * 64

    _edit_manifest(home, change)
    fields = _fields(home)
    assert "manifest.folds[0].test_end" in fields
    assert "manifest.metadata.fee_bps" in fields
    assert "manifest.source_fingerprint" in fields


def test_a_field_missing_from_the_stored_run_is_a_difference_not_a_match(home: Path) -> None:
    _edit_manifest(home, lambda manifest: manifest.pop("nulls"))
    folder = _run_folder(home)
    diagnostics = json.loads((folder / "diagnostics.json").read_text())
    diagnostics.pop("price_noise")
    (folder / "diagnostics.json").write_text(json.dumps(diagnostics))
    (folder / "fills.parquet").unlink()
    fields = _fields(home)
    assert {"manifest.nulls", "diagnostics.price_noise", "file fills.parquet"} <= set(fields)
