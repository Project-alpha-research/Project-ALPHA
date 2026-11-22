"""`alpha ml run`: plain spec -> frozen snapshot -> worker -> costed replay -> ordinary run."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import ml_cmds, ml_run
from alpha_cli.main import app
from alpha_cli.ml_contract import validate_result_bundle
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.trial_record import map_row
from alpha_data.store import ParquetStore

REPO = Path(__file__).parents[2]
SYMBOLS = [f"S{i:02d}" for i in range(20)]
SESSIONS = 1200  # from 2021-01-04: crosses the held-back day 2024-01-01


def _seed_store(home: Path) -> None:
    store = ParquetStore(home / "store")
    first = datetime(2021, 1, 4, tzinfo=UTC)
    for index, symbol in enumerate(SYMBOLS):
        rows = []
        for day in range(SESSIONS):
            price = 100.0 + day * 0.01 + index * 0.1 + ((day * (index + 3)) % 7) * 0.05
            rows.append(
                {
                    "ts": first + timedelta(days=day),
                    "open": price,
                    "high": price + 1.0,
                    "low": price - 1.0,
                    "close": price + 0.25,
                    "volume": 1_000_000.0,
                }
            )
        store.write_bars(symbol, pl.DataFrame(rows))
        store.write_provenance(
            symbol, source="synthetic:test", adapter_version="1", parser_version="1"
        )


def _spec(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "spec.toml"
    assets = ", ".join(f'"{s}"' for s in SYMBOLS)
    path.write_text(
        f'name = "synthetic gbm"\nassets = [{assets}]\n{extra}'
        "[split]\ntrain_days = 504\nvalidation_days = 120\ntest_days = 63\n",
        encoding="utf-8",
    )
    return path


def _fake_worker(exchange: Path, **_: object) -> object:
    """Run the repo's fake worker the way `test_ml_cli` does, then validate its result."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "workers/qlib/src")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alpha_qlib_worker",
            "fake",
            str(exchange),
            "--worker-lock",
            str(REPO / "workers/qlib/uv.lock"),
        ],
        cwd=REPO,
        env=env,
        check=True,
    )
    return validate_result_bundle(exchange)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ml_cmds, "train_exchange", _fake_worker)
    monkeypatch.setattr(ml_run, "_require_worker", lambda project: REPO / "workers/qlib")
    data = tmp_path / "alpha-data"
    _seed_store(data)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(data))
    return data


def test_run_end_to_end_with_fake_worker(home: Path, tmp_path: Path) -> None:
    result = ml_run.run_spec(_spec(tmp_path), data_dir=home)
    manifest = json.loads((home / "runs" / result["run_id"] / "manifest.json").read_text())
    assert manifest["command"] == "ml_replay"
    assert manifest["costs"]["fee_bps"] > 0
    # Training and test windows are stated and never overlap; nothing from the held-back day on.
    folds = result["folds"]
    assert all(f["train_end"] < f["test_start"] for f in folds)
    assert folds[-1]["test_end"] < "2024-01-01"
    assert f"refit {len(folds)} times" in result["split_sentence"]
    assert "No model saw its own test days" in result["split_sentence"]
    assert "Held back" in result["reserve_sentence"]
    assert manifest["reserve"]["held_back_bars"] > 0


def test_run_counts_one_try_in_family_qlib(home: Path, tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    first = ml_run.run_spec(spec, data_dir=home)
    rows = [row for row in read_trials(home) if row["kind"] == "ml_run"]
    assert len(rows) == 1
    assert rows[0]["run_id"] == first["run_id"]
    assert "1 try" in first["tries_sentence"]
    again = ml_run.run_spec(spec, data_dir=home)
    assert again["run_id"] == first["run_id"]
    assert "counted before" in again["tries_sentence"]
    mapped = map_row("spine", home / "ledger" / "trials.jsonl", 1, rows[0])
    assert mapped.family_id == "qlib"


def test_missing_worker_environment_says_what_to_run(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    project = tmp_path / "worker"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='x'\n")
    (project / "uv.lock").write_text("")
    with pytest.raises(ml_run.MlRunError, match=r"bash scripts/setup\.sh"):
        ml_run.run_spec(_spec(tmp_path), data_dir=home, worker_project=project)


@pytest.mark.parametrize(
    ("extra", "words"),
    [
        ('model = "xgboost"\n', "lightgbm"),
        ('features = "alpha999"\n', "alpha158"),
        ("horizon_days = 5\n", "1 day"),
    ],
)
def test_bad_spec_fails_loud(home: Path, tmp_path: Path, extra: str, words: str) -> None:
    with pytest.raises(ml_run.MlRunError, match=words):
        ml_run.run_spec(_spec(tmp_path, extra), data_dir=home)


def test_cli_command_is_registered(home: Path, tmp_path: Path) -> None:
    out = CliRunner().invoke(app, ["ml", "run", str(tmp_path / "missing.toml")])
    assert out.exit_code != 0
    assert "missing.toml" in out.output


def test_new_split_action_makes_a_new_snapshot(home: Path) -> None:
    store = ParquetStore(home / "store")
    first = ml_run._freeze(home, SYMBOLS)
    assert ml_run._freeze(home, SYMBOLS) == first
    actions = store._actions_path(SYMBOLS[0])
    actions.parent.mkdir(parents=True, exist_ok=True)
    actions.write_text("changed")
    assert ml_run._freeze(home, SYMBOLS) != first
