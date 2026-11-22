"""`/api/recent-runs` relays stored run facts and a thinned equity curve."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from alpha_web import _recent_runs
from alpha_web.app import create_app


def _run(home: Path, run_id: str, *, sharpe: float, word: str, mtime: float, bars: int) -> None:
    folder = home / "runs" / run_id
    folder.mkdir(parents=True)
    manifest = {
        "command": "validate",
        "metadata": {"symbol": "SPY"},
        "oos_metrics": {"sharpe": sharpe},
        "reading": {"evidence": {"word": word}, "counts": {"family_trials": 4}},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    start = datetime(2020, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "ts": [start + timedelta(days=i) for i in range(bars)],
            "equity": [1.0 + i for i in range(bars)],
        }
    )
    frame.write_parquet(folder / "equity_curve.parquet")
    os.utime(folder / "manifest.json", (mtime, mtime))


def _client(home: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    return TestClient(create_app())


def test_recent_runs_are_newest_first_with_stored_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(tmp_path, "a" * 16, sharpe=0.5, word="some evidence", mtime=1_000, bars=200)
    _run(tmp_path, "b" * 16, sharpe=-0.2, word="too little to read", mtime=2_000, bars=10)
    body = _client(tmp_path, monkeypatch).get("/api/recent-runs?limit=10").json()
    assert body["total"] == 2
    first, second = body["items"]
    assert first["run_id"] == "b" * 16 and first["oos_sharpe"] == -0.2
    assert first["evidence"] == "too little to read" and first["tries"] == 4
    assert first["symbol"] == "SPY" and first["spark"] == [float(1 + i) for i in range(10)]
    assert len(second["spark"]) == _recent_runs.SPARK_POINTS
    assert second["spark"][0] == 1.0 and second["spark"][-1] == 200.0


def test_recent_runs_can_skip_the_sparkline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(tmp_path, "c" * 16, sharpe=0.1, word="some evidence", mtime=1_000, bars=5)
    body = _client(tmp_path, monkeypatch).get("/api/recent-runs?spark=false").json()
    assert body["items"][0]["spark"] == []
