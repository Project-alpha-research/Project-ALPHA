"""Verified archive bars retain dataset identity through relabeling and resampling."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import _chart_data
from alpha_core import Bar, DataError
from alpha_data.crypto.storage import CryptoBulkStore
from alpha_data.timeframe import parse_timeframe


def _archive(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    list[Bar],
    list[tuple[CryptoBulkStore, str, str, datetime | None]],
    dict[str, object],
]:
    bars = [
        Bar(
            symbol="BTCUSDT",
            ts=datetime(2024, 1, 2, tzinfo=UTC) + timedelta(minutes=5 * i),
            open=100.0 + i,
            high=102.0 + i,
            low=99.0 + i,
            close=101.0 + i,
            volume=1.0,
        )
        for i in range(24)
    ]
    calls: list[tuple[CryptoBulkStore, str, str, datetime | None]] = []
    dataset: dict[str, object] = {
        "manifest_id": "group",
        "manifest_ids": ["member"],
        "frequency": "5m",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "instrument": "BTCUSDT",
        "provider": "binance",
        "venue": "binance",
        "family": "market_bars",
        "market_type": "spot",
    }

    def loader(
        store: CryptoBulkStore, manifest_id: str, *, symbol: str, as_of: datetime | None
    ) -> tuple[list[Bar], dict[str, Any]]:
        calls.append((store, manifest_id, symbol, as_of))
        return [bar for bar in bars if as_of is None or bar.ts + timedelta(minutes=5) <= as_of], {}

    monkeypatch.setattr(_chart_data, "load_chart_dataset", loader)
    monkeypatch.setattr(_chart_data, "chart_datasets", lambda store: [dataset])
    return bars, calls, dataset


@pytest.fixture
def archive_store(tmp_path: Path) -> CryptoBulkStore:
    return CryptoBulkStore(
        bulk_root=tmp_path / "bulk",
        manifest_root=tmp_path / "manifests",
        expected_volume_uuid="test-volume",
    )


def test_archive_relabels_from_dataset_identity(
    monkeypatch: pytest.MonkeyPatch, archive_store: CryptoBulkStore
) -> None:
    from alpha_cli._archive_bars import load_archive_bars

    original, calls, _ = _archive(monkeypatch)
    cutoff = original[-1].ts + timedelta(minutes=5)
    store = archive_store
    bars = load_archive_bars(
        store, "group", symbol="BTCUSDT", timeframe=parse_timeframe("5m"), as_of=cutoff
    )
    assert {bar.symbol for bar in bars} == {"BTC/USDT"}
    assert [bar.ts for bar in bars] == [bar.ts for bar in original]
    assert calls == [(store, "group", "BTCUSDT", cutoff)]
    assert original[0].symbol == "BTCUSDT"


def test_archive_frequency_mismatch_fails(
    monkeypatch: pytest.MonkeyPatch, archive_store: CryptoBulkStore
) -> None:
    from alpha_cli._archive_bars import load_archive_bars

    _archive(monkeypatch)
    with pytest.raises(DataError, match="frequency"):
        load_archive_bars(archive_store, "group", symbol="BTCUSDT", timeframe=parse_timeframe("1h"))


def test_archive_resamples_complete_known_bins(
    monkeypatch: pytest.MonkeyPatch, archive_store: CryptoBulkStore
) -> None:
    from alpha_cli._archive_bars import load_archive_bars

    original, _, _ = _archive(monkeypatch)
    bars = load_archive_bars(
        archive_store,
        "group",
        symbol="BTCUSDT",
        timeframe=parse_timeframe("1h"),
        source_timeframe=parse_timeframe("5m"),
        as_of=original[18].ts,
    )
    assert len(bars) == 1
    assert bars[0].symbol == "BTC/USDT"
    assert bars[0].ts == original[0].ts
    assert bars[0].open == pytest.approx(original[0].open)
    assert bars[0].close == pytest.approx(original[11].close)
    assert bars[0].volume == pytest.approx(12.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "bybit"),
        ("venue", "bybit"),
        ("family", "derivative_bars"),
        ("market_type", "inverse"),
    ],
)
def test_archive_refuses_non_binance_spot_identity(
    monkeypatch: pytest.MonkeyPatch, archive_store: CryptoBulkStore, field: str, value: str
) -> None:
    from alpha_cli._archive_bars import load_archive_bars

    _, _, dataset = _archive(monkeypatch)
    dataset.update(provider="binance", venue="binance", family="market_bars", market_type="spot")
    dataset[field] = value
    with pytest.raises(DataError, match="Binance spot"):
        load_archive_bars(archive_store, "group", symbol="BTCUSDT", timeframe=parse_timeframe("5m"))


def test_archive_cli_manifest_and_margin_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archive_store: CryptoBulkStore
) -> None:
    import json

    from typer.testing import CliRunner

    from alpha_cli import crypto_data_cmds
    from alpha_cli.main import app

    _archive(monkeypatch)
    monkeypatch.setattr(crypto_data_cmds, "_bulk_store", lambda: archive_store)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    args = [
        "backtest",
        "run",
        "BTCUSDT",
        "--manifest-id",
        "group",
        "--timeframe",
        "5m",
        "--strategy",
        "ma_crossover",
        "--periods-per-year",
        "20000",
    ]
    cli = CliRunner()
    cash = cli.invoke(app, args)
    assert cash.exit_code != 0
    assert "MARGIN" in cash.output
    margin = cli.invoke(app, [*args, "--account-type", "MARGIN"])
    assert margin.exit_code == 0, margin.output
    paths = list((tmp_path / "runs").glob("*/manifest.json"))
    assert len(paths) == 1
    manifest = json.loads(paths[0].read_text())
    assert manifest["symbol"] == "BTC/USDT"
    assert manifest["session"] == "continuous"
    assert manifest["manifest_id"] == "group"
    assert manifest["snapshot_id"] is None
    assert manifest["snapshot_hash"] is None
    assert manifest["timeframe"] == manifest["source_timeframe"] == "5m"
    conflict = cli.invoke(app, [*args, "--snapshot", "frozen"])
    assert conflict.exit_code != 0
    assert "mutually exclusive" in conflict.output
    invalid_session = cli.invoke(app, [*args, "--session", "regular"])
    assert invalid_session.exit_code != 0
    assert "incompatible" in invalid_session.output
    mismatch = cli.invoke(app, [*args, "--from-timeframe", "1h"])
    assert mismatch.exit_code != 0
    assert "frequency" in mismatch.output
