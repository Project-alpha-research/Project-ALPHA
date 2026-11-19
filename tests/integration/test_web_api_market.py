"""``/api/market/overview``: relays the read-only CLI overview (real ``alpha`` subprocess)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from alpha_data.store import ParquetStore
from alpha_web.app import create_app


def _seed(root: Path, symbol: str, n: int, close: float, volume: float) -> None:
    closes = [close + i for i in range(n)]
    frame = pl.DataFrame(
        {
            "ts": [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n)],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [volume] * n,
        }
    )
    ParquetStore(root / "store").write_bars(symbol, frame)


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    _seed(tmp_path, "BIG", 60, 100.0, 1000.0)
    _seed(tmp_path, "SML", 60, 10.0, 1000.0)
    _seed(tmp_path, "NEW", 5, 10.0, 1000.0)
    return TestClient(create_app())


def test_overview_ranks_assets_and_lists_short_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = (
        _client(tmp_path, monkeypatch).get("/api/market/overview", params={"window": "30"}).json()
    )
    assert [row["asset"] for row in body["assets"]] == ["BIG", "SML"]
    assert body["assets"][0]["series"][0] == pytest.approx(100.0)
    assert body["too_few_bars"] == [{"asset": "NEW", "bar_count": 5, "needed": 30}]
    assert body["store"] == "1D" and body["data_to"] is not None
    assert body["scan_cap"] == 200 and body["bars_cap"] == 400


def test_overview_limit_is_applied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = (
        _client(tmp_path, monkeypatch)
        .get("/api/market/overview", params={"window": "30", "limit": 1})
        .json()
    )
    assert [row["asset"] for row in body["assets"]] == ["BIG"]
    assert body["eligible_assets"] == 2


def test_overview_rejects_bad_input_before_any_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/market/overview", params={"window": "45"}).status_code == 422
    assert client.get("/api/market/overview", params={"limit": 99}).status_code == 422
    assert client.get("/api/market/overview", params={"store": "../x"}).status_code == 422


def test_overview_cli_failure_is_a_409_with_the_cli_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _client(tmp_path, monkeypatch).get("/api/market/overview", params={"store": "5m"})
    assert response.status_code == 409
    assert "no stored bars" in response.json()["message"]


def test_overview_on_an_empty_store_is_a_409_not_a_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    assert TestClient(create_app()).get("/api/market/overview").status_code == 409
