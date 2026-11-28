"""The run-analytics readers live in ``alpha_web._run_analytics_reads``; HTTP output unchanged."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from alpha_web import _runs
from alpha_web.app import create_app

MOVED = (
    "forecast_series",
    "MAX_FORECAST_PATHS",
    "forecast_paths",
    "null_distributions",
    "optim_trials",
    "propfirm_paths",
    "forecast_origins",
    "tearsheet_file",
)


def test_moved_readers_import_from_new_module() -> None:
    module = importlib.import_module("alpha_web._run_analytics_reads")
    for name in MOVED:
        assert hasattr(module, name), name


def test_moved_readers_left_runs_module_without_shim() -> None:
    for name in MOVED:
        assert not hasattr(_runs, name), name


def test_runs_module_is_under_800_lines() -> None:
    lines = Path(_runs.__file__).read_text(encoding="utf-8").splitlines()
    assert len(lines) < 800, len(lines)


def _seed_run(data_dir: Path, run_id: str, *, tearsheet: bool) -> Path:
    rdir = data_dir / "runs" / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    manifest = {"command": "backtest_run", "symbol": "SPY", "passed": True}
    (rdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if tearsheet:
        (rdir / "tearsheet.html").write_text("<html><body>TS</body></html>")
    return rdir


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    return TestClient(create_app())


def test_nulls_and_trials_endpoints_serve_grouped_artifacts(
    tmp_path: Path, client: TestClient
) -> None:
    rdir = _seed_run(tmp_path, "bbbb000000000001", tearsheet=False)
    pl.DataFrame(
        {
            "tier": ["a", "a", "b"],
            "path_index": [0, 1, 0],
            "statistic": [0.5, 1.5, 2.0],
        }
    ).write_parquet(rdir / "nulls.parquet")
    pl.DataFrame(
        {"trial": [0, 0, 1], "step": [0, 1, 0], "oos_return": [0.1, -0.2, 0.3]}
    ).write_parquet(rdir / "trials.parquet")

    nulls = client.get("/api/runs/bbbb000000000001/nulls")
    assert nulls.status_code == 200, nulls.text
    assert nulls.json()["tiers"] == [
        {"tier": "a", "statistics": [0.5, 1.5]},
        {"tier": "b", "statistics": [2.0]},
    ]
    trials = client.get("/api/runs/bbbb000000000001/trials")
    assert trials.status_code == 200, trials.text
    assert trials.json()["trials"] == [
        {"trial": 0, "returns": [0.1, -0.2]},
        {"trial": 1, "returns": [0.3]},
    ]
    assert client.get("/api/runs/bbbb000000000001/origins").status_code == 404


def test_tearsheet_endpoint_serves_file_and_404s_when_absent(
    tmp_path: Path, client: TestClient
) -> None:
    _seed_run(tmp_path, "cccc000000000001", tearsheet=True)
    _seed_run(tmp_path, "cccc000000000002", tearsheet=False)

    found = client.get("/api/runs/cccc000000000001/tearsheet")
    assert found.status_code == 200
    assert "TS" in found.text
    assert client.get("/api/runs/cccc000000000002/tearsheet").status_code == 404
