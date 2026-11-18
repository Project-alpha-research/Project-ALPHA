"""Exercise the ASGI routes in memory, without TestClient or network sockets."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from alpha_web.api import setup_runs
from alpha_web.app import create_app


def test_setup_routes_are_read_only_and_report_missing_corrupt_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(setup_runs, "data_dir", lambda: tmp_path)

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            listing = await client.get("/api/setup/runs")
            assert listing.status_code == 200
            assert listing.json() == {"items": []}
            find_id = "a" * 16
            missing = await client.get(f"/api/setup/runs/{find_id}")
            assert missing.status_code == 404
            assert missing.json()["request_id"]
            invalid = await client.get("/api/setup/runs/invalid")
            assert invalid.status_code == 422
            mutation = await client.post("/api/setup/runs", json={})
            assert mutation.status_code == 405
            folder = tmp_path / "setups" / find_id
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": "AlphaSetupFindV1",
                        "find_id": find_id,
                        "idea": "Synthetic route fixture",
                        "recorded_at": "2026-11-01T00:00:00Z",
                    }
                )
            )
            success = await client.get(f"/api/setup/runs/{find_id}")
            assert success.status_code == 200
            assert success.json()["run"]["description"] == "Synthetic route fixture"
            assert success.json()["candidates"] is None
            (folder / "summary.json").write_text("broken JSON")
            corrupt = await client.get(f"/api/setup/runs/{find_id}")
            assert corrupt.status_code == 422
            assert corrupt.json()["request_id"]
            assert str(tmp_path) not in corrupt.text

    asyncio.run(exercise())
