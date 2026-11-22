from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import crypto_data_cmds
from alpha_cli.main import app
from alpha_data.crypto.contracts import (
    CryptoDatasetIdentityV1,
)
from alpha_data.crypto.ingestion import ingest_provider_payload
from alpha_data.crypto.storage import Capacity, CryptoBulkStore

runner = CliRunner()


def _manifest(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _funding_feature_fixture(tmp_path: Path) -> tuple[CryptoBulkStore, str, datetime]:
    """Publish the exact qualified funding source the feature-create tests share."""
    bulk = tmp_path / "bulk"
    bulk.mkdir()
    store = CryptoBulkStore(
        bulk_root=bulk,
        manifest_root=tmp_path / "control" / "crypto" / "manifests",
        expected_volume_uuid="TEST-UUID",
        volume_uuid=lambda _: "TEST-UUID",
        capacity=lambda _: Capacity(total_bytes=20_000_000, free_bytes=10_000_000),
        minimum_free_bytes=100,
    )
    now = datetime.fromisoformat("2026-08-15T00:00:00+00:00")
    source = ingest_provider_payload(
        store,
        dataset=CryptoDatasetIdentityV1(
            provider="bybit",
            venue="bybit",
            market_type="linear",
            family="funding",
            instrument="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            frequency="funding_interval",
            units="provider_native_rate",
            timestamp_convention="provider_event_utc",
        ),
        payload=b"fixture-funding",
        request=(("symbol", "BTCUSDT"),),
        fetched_at=now,
        provider_schema="fixture",
        parser_version="fixture-v1",
        logical_name="funding.json",
        parser=lambda _payload: pl.DataFrame(
            {
                "timestamp": [now - timedelta(hours=2), now - timedelta(hours=1)],
                "funding_rate": [0.001, -0.0005],
            }
        ),
        observed_column="timestamp",
        key_columns=("timestamp",),
    )
    source_id = str(source.normalized_manifest["manifest_id"])
    return store, source_id, now


def test_feature_create_persists_and_reverifies_exact_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, source_id, now = _funding_feature_fixture(tmp_path)
    monkeypatch.setattr(crypto_data_cmds, "_bulk_store", lambda: store)
    monkeypatch.setattr(crypto_data_cmds, "_now", lambda: now)

    created = runner.invoke(
        app,
        [
            "crypto-data",
            "feature-create",
            "funding",
            "--input",
            f"funding={source_id}",
            "--json",
        ],
    )
    assert created.exit_code == 0, created.output
    payload = json.loads(created.stdout)
    assert payload["state"] == "frozen"
    assert payload["research_authority"] is False
    assert payload["execution_authority"] is False
    manifest = _manifest(store.verify_manifest(payload["manifest_id"]))
    assert manifest["derived_kind"] == "crypto-feature"
    assert manifest["input_manifest_ids"] == [source_id]
    assert manifest["metadata"]["feature"]["artifact_sha256"] == manifest["artifact_sha256"]

    shown = runner.invoke(
        app,
        ["crypto-data", "feature-show", payload["manifest_id"], "--json"],
    )
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout)["state"] == "verified"
    listed = runner.invoke(app, ["crypto-data", "features", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout)["count"] == 1

    duplicated = runner.invoke(
        app,
        [
            "crypto-data",
            "feature-create",
            "funding",
            "--input",
            f"funding={source_id}",
            "--input",
            f"funding={source_id}",
        ],
    )
    assert duplicated.exit_code == 2
    assert "requires inputs: funding" in duplicated.output


def test_feature_create_is_idempotent_for_identical_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, source_id, now = _funding_feature_fixture(tmp_path)
    monkeypatch.setattr(crypto_data_cmds, "_bulk_store", lambda: store)
    command = [
        "crypto-data",
        "feature-create",
        "funding",
        "--input",
        f"funding={source_id}",
        "--json",
    ]

    monkeypatch.setattr(crypto_data_cmds, "_now", lambda: now)
    first = runner.invoke(app, command)
    monkeypatch.setattr(crypto_data_cmds, "_now", lambda: now + timedelta(days=3))
    second = runner.invoke(app, command)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload["feature_id"] == second_payload["feature_id"]
    assert first_payload["artifact_sha256"] == second_payload["artifact_sha256"]
    assert first_payload["available_at"] == "2026-08-14T23:00:00+00:00"

    early = runner.invoke(app, [*command, "--available-at", "2026-08-01T00:00:00Z"])
    assert early.exit_code != 0
    assert "availability precedes" in early.output
