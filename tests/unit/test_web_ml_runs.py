"""`/api/ml-runs` lists stored `alpha ml run` runs from their run folders (synthetic fixtures)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

from alpha_web.app import create_app

UTC_TS = pl.Datetime("us", "UTC")


def _ml_run(home: Path, run_id: str, *, mtime: float, sharpe: float | None = 0.8) -> None:
    folder = home / "runs" / run_id
    folder.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "command": "ml_replay",
        "label": "OOS replay validated — model not recomputed under counterfactual",
        "universe": ["SPY", "QQQ", "IWM", "TLT", "GLD"],
        "worker": {"kind": "qlib", "implementation_version": "1"},
        "costs": {"fee_bps": 1.0, "slippage_bps": 2.0},
        "n_oos_periods": 126,
        "metrics": {
            "total_return": 0.085,
            "benchmark_total_return": 0.12,
            "max_drawdown": -0.07,
            "sharpe": sharpe,
            "cagr": 0.04,
            "mean_turnover": 0.3,
            "total_fees": 12.5,
            "total_slippage_cost": 25.0,
        },
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    start = datetime(2020, 1, 1, tzinfo=UTC)
    day = timedelta(days=1)
    rows = [
        {
            "fold": i,
            "train_start": start + 100 * i * day,
            "train_end": start + (100 * i + 50) * day,
            "validation_start": start + (100 * i + 51) * day,
            "validation_end": start + (100 * i + 60) * day,
            "test_start": start + (100 * i + 61) * day,
            "test_end": start + (100 * i + 90) * day,
        }
        for i in range(3)
    ]
    schema = {
        name: (pl.Int64 if name == "fold" else UTC_TS)
        for name in ("fold", "train_start", "train_end", "validation_start", "validation_end")
    } | {"test_start": UTC_TS, "test_end": UTC_TS}
    pl.DataFrame(rows, schema=schema).write_parquet(folder / "folds.parquet")
    os.utime(folder / "manifest.json", (mtime, mtime))


def _other_run(home: Path, run_id: str) -> None:
    folder = home / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"command": "validate"}), encoding="utf-8")


def _client(home: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    return TestClient(create_app())


def test_lists_only_ml_runs_with_split_assets_model_costs_and_folds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ml_run(tmp_path, "a" * 16, mtime=1_000)
    _other_run(tmp_path, "b" * 16)
    body = _client(tmp_path, monkeypatch).get("/api/ml-runs").json()
    assert body["total"] == 1
    run = body["items"][0]
    assert run["assets"] == ["SPY", "QQQ", "IWM", "TLT", "GLD"]
    assert run["model"] == "Qlib worker; the model type is not recorded in the run"
    assert run["costs"] == "1 bp fee and 2 bp slippage per trade"
    assert run["split_sentence"].startswith("The model was refit 3 times")
    assert run["split_sentence"].endswith("No model saw its own test days.")
    assert run["folds"][0] == {
        "fold": 0,
        "train_start": "2020-01-01",
        "train_end": "2020-02-20",
        "test_start": "2020-03-02",
        "test_end": "2020-03-31",
    }
    assert run["metrics"]["total_return"] == pytest.approx(0.085, rel=1e-9, abs=1e-12)
    assert run["metrics"]["sharpe_reason"] is None


def test_a_missing_sharpe_stays_null_with_a_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ml_run(tmp_path, "c" * 16, mtime=1_000, sharpe=None)
    run = _client(tmp_path, monkeypatch).get("/api/ml-runs").json()["items"][0]
    assert run["metrics"]["sharpe"] is None
    assert run["metrics"]["sharpe_reason"]


def test_no_ml_run_gives_an_empty_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = _client(tmp_path, monkeypatch).get("/api/ml-runs").json()
    assert body == {"total": 0, "items": []}


def test_newest_first_and_unreadable_run_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ml_run(tmp_path, "d" * 16, mtime=1_000)
    _ml_run(tmp_path, "e" * 16, mtime=2_000)
    (tmp_path / "runs" / ("e" * 16) / "folds.parquet").write_bytes(b"not parquet")
    items = _client(tmp_path, monkeypatch).get("/api/ml-runs").json()["items"]
    assert [item["run_id"] for item in items] == ["d" * 16]


def test_ml_runs_are_found_behind_many_newer_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ml_run(tmp_path, "f" * 16, mtime=1)
    for index in range(520):
        _other_run(tmp_path, f"{index:016x}")
        os.utime(tmp_path / "runs" / f"{index:016x}" / "manifest.json", (10_000 + index,) * 2)
    body = _client(tmp_path, monkeypatch).get("/api/ml-runs").json()
    assert [item["run_id"] for item in body["items"]] == ["f" * 16]


def test_the_split_sentence_covers_every_fold_when_the_table_is_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_web import _ml_runs

    monkeypatch.setattr(_ml_runs, "MAX_FOLDS", 2)
    _ml_run(tmp_path, "9" * 16, mtime=1)
    run = _client(tmp_path, monkeypatch).get("/api/ml-runs").json()["items"][0]
    assert len(run["folds"]) == 2 and run["folds_total"] == 3
    assert run["split_sentence"].startswith("The model was refit 3 times")
