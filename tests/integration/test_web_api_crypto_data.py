"""Typed Crypto Data Center REST routes over the authoritative CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from alpha_web import _catalog
from alpha_web.api import crypto_data as crypto_api
from alpha_web.api.models import (
    CryptoAcquisitionRequest,
    CryptoAssetMasterCreateRequest,
    CryptoSnapshotCreateRequest,
    CryptoSnapshotRegisterRequest,
    CryptoSnapshotVerifyRequest,
)
from alpha_web.app import create_app


def test_crypto_catalog_route_uses_authoritative_cli_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    calls: list[list[str]] = []

    def project(args: list[str], **_: object) -> dict[str, object]:
        calls.append(args)
        return {
            "families": [{"family": "funding", "provider": "bybit", "role": "primary_acquisition"}],
            "automatic_fallback": False,
            "execution_authority": False,
            "next_action": "Check storage before estimating or acquiring data.",
        }

    monkeypatch.setattr(_catalog, "_run_json", project)

    response = TestClient(create_app()).get("/api/crypto-data/catalog")

    assert response.status_code == 200
    assert response.json()["families"][0]["provider"] == "bybit"
    assert calls == [["crypto-data", "catalog", "--json"]]


def test_crypto_route_functions_cover_closed_validation_and_recovery_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def project(args: list[str]) -> list[str]:
        calls.append(args)
        return args

    monkeypatch.setattr(crypto_api, "_project", project)
    defillama_request = CryptoAcquisitionRequest(
        provider="defillama",
        family="protocol_tvl",
        instrument="aave",
        base="AAVE",
        quote="USD",
        frequency="1d",
    )
    assert defillama_request.provider == "defillama"
    assert defillama_request.family == "protocol_tvl"
    assert crypto_api.storage()[1] == "storage"
    assert crypto_api.coverage()[1] == "coverage"
    with pytest.raises(HTTPException, match="asset-master"):
        crypto_api.asset_master_verify("bad")
    with pytest.raises(HTTPException, match="manifest id"):
        crypto_api.quality("bad")
    with pytest.raises(HTTPException, match="feature manifest"):
        crypto_api.feature_show("bad")
    with pytest.raises(HTTPException, match="snapshot id"):
        crypto_api.snapshot_verify(
            "bad", CryptoSnapshotVerifyRequest(required_families=[], purpose="research")
        )
    with pytest.raises(HTTPException, match="snapshot id"):
        crypto_api.snapshot_register("bad", CryptoSnapshotRegisterRequest(symbol="BTC"))

    with pytest.raises(HTTPException, match="unique"):
        crypto_api.snapshot_create(CryptoSnapshotCreateRequest(manifest_ids=["a" * 64, "a" * 64]))
    with pytest.raises(HTTPException, match="manifest id"):
        crypto_api.snapshot_create(CryptoSnapshotCreateRequest(manifest_ids=["bad"]))
    with pytest.raises(HTTPException, match="unique"):
        crypto_api.asset_master_create(
            CryptoAssetMasterCreateRequest(
                coingecko_manifest_id="a" * 64,
                geckoterminal_manifest_ids=["b" * 64, "b" * 64],
            )
        )

    request = CryptoAcquisitionRequest(
        provider="bybit",
        family="funding",
        instrument="BTCUSDT",
        base="BTC",
        quote="USDT",
        case_id="f03802b8-df35-4f19-a90c-0b3437aa587d",
        expected_case_revision="a" * 64,
        reason="Not valid for this family.",
    )
    with pytest.raises(HTTPException, match="only valid"):
        crypto_api.acquire(request)


def test_crypto_asset_master_routes_build_closed_exact_identity_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    cg_manifest, gt_manifest, version = "a" * 64, "b" * 64, "c" * 64
    calls: list[list[str]] = []

    def project(args: list[str], **_: object) -> dict[str, object]:
        calls.append(args)
        if args[1] == "asset-masters":
            return {
                "items": [
                    {
                        "asset_master_version": version,
                        "identity_count": 3,
                        "contract_identity_count": 1,
                        "builtin": False,
                        "state": "verified",
                    }
                ],
                "count": 1,
                "ticker_join_allowed": False,
                "next_action": "Select this master.",
            }
        return {
            "asset_master_version": version,
            "identity_count": 3,
            "contract_identity_count": 1,
            "source_manifest_ids": [cg_manifest, gt_manifest]
            if args[1] == "asset-master-create"
            else None,
            "ticker_join_allowed": False,
            "state": "frozen" if args[1] == "asset-master-create" else "verified",
            "next_action": "Continue.",
        }

    monkeypatch.setattr(_catalog, "_run_json", project)
    client = TestClient(create_app())
    created = client.post(
        "/api/crypto-data/asset-masters",
        json={
            "coingecko_manifest_id": cg_manifest,
            "geckoterminal_manifest_ids": [gt_manifest],
        },
    )
    listed = client.get("/api/crypto-data/asset-masters")
    verified = client.post(f"/api/crypto-data/asset-masters/{version}/verify", json={})
    assert created.status_code == 200
    assert listed.status_code == 200
    assert verified.status_code == 200
    assert calls == [
        [
            "crypto-data",
            "asset-master-create",
            "--coingecko-manifest-id",
            cg_manifest,
            "--geckoterminal-manifest-id",
            gt_manifest,
            "--json",
        ],
        ["crypto-data", "asset-masters", "--json"],
        ["crypto-data", "asset-master-verify", version, "--json"],
    ]


def test_crypto_routes_translate_cli_failure_to_actionable_api_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))

    def fail(*_: object, **__: object) -> object:
        raise RuntimeError("review the exact data-family requirements")

    monkeypatch.setattr(_catalog, "_run_json", fail)
    response = TestClient(create_app()).post(
        "/api/crypto-data/estimate",
        json={"family": "funding", "instruments": 1, "days": 30, "frequency": "1h"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "request_invalid"
    assert body["message"] == "review the exact data-family requirements"


def test_crypto_storage_actions_use_closed_commands_and_confirm_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    calls: list[list[str]] = []

    def project(args: list[str], **_: object) -> dict[str, object]:
        calls.append(args)
        if args[1] == "storage-inventory":
            return {
                "manifest_count": 2,
                "snapshot_count": 1,
                "counts_by_kind": {"raw": 1, "normalized": 1},
                "bytes_by_kind": {"raw": 10, "normalized": 20},
                "cache_bytes": 5,
                "staging_count": 0,
                "private_paths_exposed": False,
                "next_action": "Verify storage.",
            }
        if args[1] == "storage-verify":
            return {
                "state": "verified",
                "manifest_count": 2,
                "snapshot_count": 1,
                "research_eligible_snapshot_count": 1,
                "asset_master_count": 0,
                "cache_bytes": 5,
                "private_paths_exposed": False,
                "next_action": "Continue.",
            }
        return {
            "state": "cleaned",
            "removed_bytes": 5,
            "immutable_artifacts_removed": 0,
            "private_paths_exposed": False,
            "next_action": "Run inventory.",
        }

    monkeypatch.setattr(_catalog, "_run_json", project)
    client = TestClient(create_app())

    assert client.get("/api/crypto-data/storage/inventory").status_code == 200
    assert client.post("/api/crypto-data/storage/verify", json={}).status_code == 200
    assert (
        client.post("/api/crypto-data/storage/cache/clean", json={"confirm": True}).status_code
        == 200
    )
    assert (
        client.post("/api/crypto-data/storage/cache/clean", json={"confirm": False}).status_code
        == 422
    )
    assert calls == [
        ["crypto-data", "storage-inventory", "--json"],
        ["crypto-data", "storage-verify", "--json"],
        ["crypto-data", "cache-clean", "--confirm", "--json"],
    ]
