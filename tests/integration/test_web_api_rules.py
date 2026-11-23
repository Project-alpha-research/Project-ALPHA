"""``/api/rules`` — the saved rule sets, relayed from ``alpha rules``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from alpha_cli.main import app as cli_app

from alpha_web.app import create_app

TREND = {
    "name": "trend",
    "history": 40,
    "long_when": [
        {
            "left": {"indicator": "sma", "params": [5]},
            "op": ">",
            "right": {"indicator": "sma", "params": [20]},
        }
    ],
    "short_when": [],
}


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    return TestClient(create_app())


def test_rules_are_listed_and_the_builder_routes_are_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/rules").json() == {"rules": [], "authority": "none"}
    saved = CliRunner().invoke(
        cli_app, ["rules", "save", "trend", "--spec", json.dumps(TREND), "--json"]
    )
    assert saved.exit_code == 0, saved.output
    listed = client.get("/api/rules").json()["rules"]
    assert [row["name"] for row in listed] == ["trend"]
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths["/api/rules"]) == {"get"}
    assert "/api/rules/evaluate" in paths
    prefixes = ("/api/scans", "/api/alerts", "/api/rules/{name}", "/api/rules/validate")
    assert [path for path in paths if path.startswith(prefixes)] == []
