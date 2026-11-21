"""Setup Lab's reading reaches the browser from ``alpha setup show``: the CLI's one home.

A real study and a real trade are written by the CLI. The web route must return the same reading
the CLI prints for each; an old record reads as its mapped word; a missing record is a clear error.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_web.api import setup_runs
from alpha_web.app import create_app
from tests.unit import _setup_reading_support as support

RUNNER = CliRunner()


def cli(home: Path, *args: str) -> Any:
    result = RUNNER.invoke(app, [*args, "--json"], env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, json.loads(result.stdout)


def web_detail(home: Path, monkeypatch: pytest.MonkeyPatch, find_id: str) -> dict[str, Any]:
    monkeypatch.setattr(setup_runs, "data_dir", lambda: home)
    response = TestClient(create_app()).get(f"/api/setup/runs/{find_id}")
    assert response.status_code == 200, response.text
    detail: dict[str, Any] = response.json()
    return detail


def as_web(shown: dict[str, Any]) -> dict[str, Any]:
    family = shown["family"]
    return {
        "evidence": shown["evidence"],
        "old_wording": shown["old_wording"],
        "family_position": family["position"],
        "family_count": family["studies"],
    }


@pytest.fixture
def lab(tmp_path: Path) -> tuple[Path, str]:
    support.seed_events(tmp_path, lift=0.004)
    find_id = support.make_find(tmp_path)["find_id"]
    for command in ("study", "trade"):
        assert cli(tmp_path, "setup", command, find_id)[0] == 0
    return tmp_path, find_id


def test_the_web_reading_is_the_command_lines_for_a_study_and_a_trade(
    lab: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    home, find_id = lab
    detail = web_detail(home, monkeypatch, find_id)
    for outcome in (detail["studies"][0], detail["trades"][0]):
        code, shown = cli(home, "setup", "show", outcome["run_id"])
        assert code == 0
        assert shown["evidence"] == "some evidence" and shown["old_wording"] is False
        assert json.dumps(outcome["reading"], sort_keys=True) == json.dumps(
            as_web(shown), sort_keys=True
        )
        assert outcome["reading"]["family_position"] == 1


@pytest.mark.parametrize(
    ("old", "word"),
    [
        ("inconclusive", "too little to read"),
        ("not supported", "not clear of chance"),
        ("supported (exploratory, not confirmed)", "some evidence"),
    ],
)
def test_an_old_record_reads_as_its_mapped_word_and_says_so(
    lab: tuple[Path, str], monkeypatch: pytest.MonkeyPatch, old: str, word: str
) -> None:
    home, find_id = lab
    study = web_detail(home, monkeypatch, find_id)["studies"][0]["run_id"]
    folder = home / "setup-studies" / study
    summary = json.loads((folder / "summary.json").read_text())
    summary.pop("evidence")
    summary["outcome"] = old
    data = json.dumps(summary, allow_nan=False).encode()
    (folder / "summary.json").write_bytes(data)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["files"]["summary.json"] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (folder / "manifest.json").write_text(json.dumps(manifest, allow_nan=False))
    shown = cli(home, "setup", "show", study)[1]
    assert (shown["evidence"], shown["old_wording"]) == (word, True)
    reading = web_detail(home, monkeypatch, find_id)["studies"][0]["reading"]
    assert reading == as_web(shown)


@pytest.mark.parametrize("run_id", ["f" * 16, "../etc", "short"])
def test_a_missing_record_is_a_clear_error(tmp_path: Path, run_id: str) -> None:
    code, shown = cli(tmp_path, "setup", "show", run_id)
    assert code == 1
    assert shown["error"]["code"] == "UNKNOWN_SETUP_OUTCOME"
    assert "alpha setup study" in shown["error"]["next"]
