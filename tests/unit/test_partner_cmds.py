"""The owner can run the same planted answers without a model or a research home."""

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from alpha_cli import partner_cmds
from alpha_cli.spine.honesty import build_fixture, run_selftest
from alpha_cli.spine.honesty_scenarios import FIXTURES


def test_fixture_contains_only_the_specified_records(tmp_path: Path) -> None:
    build_fixture(tmp_path)
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json")} == {
        f"runs/{run}/{filename}" for run, documents in FIXTURES.items() for filename in documents
    }
    for run, documents in FIXTURES.items():
        for filename, value in documents.items():
            assert json.loads((tmp_path / "runs" / run / filename).read_text()) == value


def test_selftest_json_and_scorecard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "unused-home"
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    app = typer.Typer()
    app.add_typer(partner_cmds.partner_app, name="partner")
    runner = CliRunner()
    result = runner.invoke(app, ["partner", "selftest", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report == run_selftest()
    assert report["ok"] and report["passed"] == report["total"] == 25
    assert all(row["ok"] and row["expected"] == row["got"] for row in report["scenarios"])
    text = runner.invoke(app, ["partner", "selftest"])
    assert text.exit_code == 0
    assert (
        text.stdout.splitlines()[0]
        == "Honesty self-test: 25 of 25 planted answers were judged as expected."
    )
    assert text.stdout.count("PASS  honest answer accepted:") == 8
    assert text.stdout.count("PASS  caught:") == 17
    assert (
        text.stdout.splitlines()[-1]
        == "What this shows: ALPHA's answer checker catches these planted mistakes. "
        "It checks numbers, labels and flags, not reasoning."
    )
    assert not home.exists()


def test_misbehaving_scenarios_exit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed_report() -> dict[str, Any]:
        return {
            "ok": False,
            "passed": 0,
            "total": 2,
            "note": "Fixture note.",
            "scenarios": [
                {
                    "id": "H",
                    "title": "honest",
                    "honest": True,
                    "expected": [],
                    "got": ["VALUE_MISMATCH"],
                    "ok": False,
                },
                {
                    "id": "D",
                    "title": "dishonest",
                    "honest": False,
                    "expected": ["UNTAGGED_NUMBER"],
                    "got": [],
                    "ok": False,
                },
            ],
        }

    monkeypatch.setattr(partner_cmds, "run_selftest", failed_report)
    app = typer.Typer()
    app.add_typer(partner_cmds.partner_app, name="partner")
    runner = CliRunner()
    result = runner.invoke(app, ["partner", "selftest"])
    assert result.exit_code == 1
    assert "FAIL  honest answer rejected: honest (got VALUE_MISMATCH)" in result.stdout
    assert "FAIL  missed: dishonest (expected UNTAGGED_NUMBER, got none)" in result.stdout
    result = runner.invoke(app, ["partner", "selftest", "--json"])
    assert result.exit_code == 1 and json.loads(result.stdout) == failed_report()
