"""`/api/desk/runs` relays stored run facts and a thinned curve; `/status` relays nightly."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

from alpha_web import _desk
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
    body = _client(tmp_path, monkeypatch).get("/api/desk/runs?limit=10").json()
    assert body["total"] == 2
    first, second = body["items"]
    assert first["run_id"] == "b" * 16 and first["oos_sharpe"] == -0.2
    assert first["evidence"] == "too little to read" and first["tries"] == 4
    assert first["symbol"] == "SPY" and first["spark"] == [float(1 + i) for i in range(10)]
    assert len(second["spark"]) == _desk.SPARK_POINTS
    assert second["spark"][0] == 1.0 and second["spark"][-1] == 200.0


def test_recent_runs_can_skip_the_sparkline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(tmp_path, "c" * 16, sharpe=0.1, word="some evidence", mtime=1_000, bars=5)
    body = _client(tmp_path, monkeypatch).get("/api/desk/runs?spark=false").json()
    assert body["items"][0]["spark"] == []


def test_status_relays_the_last_nightly_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts: dict[str, Any] = {
        "last": {
            "date": "2026-11-20",
            "run_number": 2,
            "complete": "all three paths",
            "blocking": 0,
        },
        "ready": False,
        "reasons": ["(a) Both latest runs are on the same date."],
    }
    calls: list[list[str]] = []

    def relay(args: list[str], **_: Any) -> Any:
        calls.append(args)
        return facts

    monkeypatch.setattr(_desk, "_run_json", relay)
    body = _client(tmp_path, monkeypatch).get("/api/desk/status").json()
    assert calls == [["nightly", "status", "--json"]]
    assert body["reserved_start"] == "2024-01-01"
    assert body["nightly"]["date"] == "2026-11-20" and body["nightly"]["blocking"] == 0
    assert body["nightly_problem"] is None


def test_status_says_why_the_nightly_record_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def relay(args: list[str], **_: Any) -> Any:
        raise RuntimeError("no nightly records")

    monkeypatch.setattr(_desk, "_run_json", relay)
    body = _client(tmp_path, monkeypatch).get("/api/desk/status").json()
    assert body["nightly"] is None and body["nightly_problem"] == "no nightly records"
