"""A run's reading reaches the browser through ``GET /api/runs/{id}/checks``: the CLI's own.

A real ``alpha test`` writes the run; the web asks the real ``alpha results show``. A new run
carries its stored reading. An old run (a manifest without ``reading``) gets one derived by the CLI.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_web.app import create_app
from tests.fixtures.cli_fixtures import seed_store

WORDS = {"clear of chance", "some evidence", "not clear of chance", "too little to read"}
ARGS = ["--rule", "ma_cross", "--param", "fast=10", "--param", "slow=30", "--asset", "SPY"]


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    from alpha_data.store import ParquetStore

    path = tmp_path_factory.mktemp("web-reading")
    patch = pytest.MonkeyPatch()
    patch.setenv("ALPHA_DATA_DIR", str(path))
    patch.setattr(_runner, "execution_fingerprint", lambda: "e" * 64)
    seed_store(path, symbol="SPY", n=1000, seed=3, drift=0.0004, sigma=0.01)
    ParquetStore(path / "store").write_provenance(
        "SPY", source="synthetic", adapter_version="1", parser_version="1"
    )
    yield path
    patch.undo()


@pytest.fixture(scope="module")
def run_id(home: Path) -> str:
    from alpha_cli.main import app

    result = CliRunner().invoke(app, ["test", *ARGS, "--quick", "--json"])
    assert result.exit_code == 0, result.output
    return str(json.loads(result.stdout)["results"][0]["run_id"])


def _checks(run_id: str) -> dict[str, Any]:
    response = TestClient(create_app()).get(f"/api/runs/{run_id}/checks")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_new_run_reaches_the_client_with_its_stored_reading(home: Path, run_id: str) -> None:
    stored = json.loads((home / "runs" / run_id / "manifest.json").read_text())["reading"]
    body = _checks(run_id)
    assert body["reading"] == stored
    assert body["reading"]["schema"] == "AlphaReadingV1"
    assert body["reading"]["evidence"]["word"] in WORDS
    assert body["reading"]["sentence"]
    assert body["counts"] == {
        "total": 0,
        "declared": 0,
        "exploratory": 0,
        "text": "0 checks run on this result: 0 declared, 0 exploratory",
    }


def test_an_old_run_gets_a_reading_derived_by_the_command_line(home: Path, run_id: str) -> None:
    manifest_path = home / "runs" / run_id / "manifest.json"
    original = manifest_path.read_text()
    stored = json.loads(original)
    del stored["reading"]
    manifest_path.write_text(json.dumps(stored))
    try:
        body = _checks(run_id)
    finally:
        manifest_path.write_text(original)
    derived = body["reading"]
    assert derived is not None and derived["schema"] == "AlphaReadingV1"
    assert derived["evidence"]["word"] in WORDS
    assert derived == json.loads(original)["reading"]
