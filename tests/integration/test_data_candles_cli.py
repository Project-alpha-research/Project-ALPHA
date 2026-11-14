"""``alpha data candles`` — PIT-adjusted OHLCV for the workstation price chart."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from tests.fixtures.cli_fixtures import seed_store

runner = CliRunner()


def test_candles_json_returns_ohlcv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=30)
    result = runner.invoke(app, ["data", "candles", "SPY", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["symbol"] == "SPY" and len(payload["bars"]) == 30
    assert set(payload["bars"][0]) == {"t", "o", "h", "l", "c", "v"}
    assert payload["provenance"] == {
        "source": "unknown",
        "venue": None,
        "timeframe": "1D",
        "snapshot_id": None,
        "provenance_sha256": None,
        "receipt_id": None,
        "knowledge_cutoff": "2020-01-30T00:00:00+00:00",
        "quality_status": "legacy_unqualified",
    }


def test_candles_window_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=30)  # daily bars from 2020-01-01
    result = runner.invoke(
        app, ["data", "candles", "SPY", "--start", "2020-01-10", "--end", "2020-01-20", "--json"]
    )
    assert result.exit_code == 0
    bars = json.loads(result.stdout)["bars"]
    lo = dt.datetime(2020, 1, 10, tzinfo=dt.UTC).timestamp()
    hi = dt.datetime(2020, 1, 20, 23, 59, 59, tzinfo=dt.UTC).timestamp()
    assert bars and all(lo <= b["t"] <= hi for b in bars) and len(bars) < 30


def test_candles_unknown_symbol_fails_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    result = runner.invoke(app, ["data", "candles", "NOPE", "--json"])
    assert result.exit_code != 0


def seed_intraday(tmp_path, *, dataset_timeframe="5m"):
    import polars as pl

    from alpha_data.adapters.base import DatasetIdentity, FetchReceipt
    from alpha_data.store import ParquetStore

    start = dt.datetime(2026, 3, 9, 13, 30, tzinfo=dt.UTC)
    frame = pl.DataFrame(
        {
            "ts": [start + dt.timedelta(minutes=5 * i) for i in range(78)],
            **{col: [100.0] * 78 for col in ("open", "high", "low", "close", "volume")},
        }
    )
    store = ParquetStore(tmp_path / "store-5m")
    store.write_bars("SPY", frame)
    identity = DatasetIdentity(
        symbol="SPY",
        provider="alpaca",
        provider_symbol="SPY",
        venue="US",
        asset_class="etf",
        timeframe=dataset_timeframe,
        calendar="XNYS",
        currency="USD",
        price_basis="raw",
    )
    receipt = FetchReceipt.create(
        identity=identity,
        requested_start=start.date(),
        requested_end=start.date(),
        fetched_at=start,
        adapter_version="1",
        parser_version="1",
        response_sha256="0" * 64,
        response_bytes=0,
        row_count=78,
        action_count=0,
        request_metadata={},
    )
    store.write_provenance(
        "SPY",
        source="alpaca",
        adapter_version="1",
        parser_version="1",
        identity=identity,
        receipt=receipt,
    )
    return store


def test_candles_intraday_and_iso_cutoff(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_intraday(tmp_path)
    result = runner.invoke(
        app,
        [
            "data",
            "candles",
            "SPY",
            "--timeframe",
            "5m",
            "--end",
            "2026-03-09T10:02:00-04:00",
            "--start",
            "2026-03-09T09:40:00-04:00",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["bars"]) == 4
    assert payload["bars"][-1]["t"] == dt.datetime(2026, 3, 9, 13, 55, tzinfo=dt.UTC).timestamp()
    assert payload["provenance"]["timeframe"] == "5m"
    assert payload["provenance"]["session"] == "regular"
    assert payload["provenance"]["source"] == "alpaca"


def test_candles_resample_from_five_minutes(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_intraday(tmp_path)
    result = runner.invoke(
        app, ["data", "candles", "SPY", "--from-timeframe", "5m", "--timeframe", "1h", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["bars"]) == 7
    assert payload["bars"][-1]["v"] == pytest.approx(600)
    assert payload["provenance"]["timeframe"] == "1h"
    assert payload["provenance"]["source"] == "alpaca"


def test_candles_mismatched_stored_timeframe(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_intraday(tmp_path, dataset_timeframe="1h")
    result = runner.invoke(app, ["data", "candles", "SPY", "--timeframe", "5m", "--json"])
    assert result.exit_code != 0
    assert "1h" in result.output and "5m" in result.output


def test_snapshot_timeframe_mismatch(tmp_path):
    from alpha_cli._runner import load_bars, load_dividends
    from alpha_core import DataError
    from alpha_data.snapshot import create_snapshot

    store = seed_intraday(tmp_path)
    create_snapshot(
        store,
        tmp_path / "snapshots",
        "five",
        ["SPY"],
        source="alpaca",
        adapter_version="1",
        parser_version="1",
        created_at=dt.datetime(2026, 3, 10, tzinfo=dt.UTC),
        timeframe="5m",
    )
    for load in (load_bars, load_dividends):
        with pytest.raises(DataError, match="5m.*1h|1h.*5m"):
            load("SPY", data_dir=tmp_path, snapshot_id="five", timeframe="1h")
        load("SPY", data_dir=tmp_path, snapshot_id="five", timeframe="5m")


@pytest.mark.parametrize("value", ["2026-03-09T10:02:00", "nonsense", "20260309"])
def test_parse_cutoff_rejects_noncanonical_or_naive(value):
    from alpha_cli._runner import parse_cutoff
    from alpha_core import DataError

    with pytest.raises(DataError):
        parse_cutoff(value)


def test_parse_cutoff_date_and_instant():
    from alpha_cli._runner import parse_as_of, parse_cutoff

    assert parse_cutoff(None) is None
    assert parse_cutoff("2026-03-09") == parse_as_of("2026-03-09")
    assert parse_cutoff("2026-03-09T10:02:00-04:00") == dt.datetime(
        2026, 3, 9, 14, 2, tzinfo=dt.UTC
    )
