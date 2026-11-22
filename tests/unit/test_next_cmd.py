"""`alpha next`: the read-only front door that says where the owner is and what can be done."""

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from tests.fixtures.cli_fixtures import seed_store
from tests.unit.test_trial_record import spine

RUNNER = CliRunner()
JSON_KEYS = ["ideas", "last_night", "notes", "paths", "recent_trials", "stores", "waiting"]


def _run(home: Path, *args: str) -> tuple[int, str]:
    result = RUNNER.invoke(app, ["next", *args], env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, result.output


def _snapshot(home: Path) -> list[tuple[str, int, int]]:
    rows: list[tuple[str, int, int]] = []
    for path in sorted(home.rglob("*")):
        stat = path.stat()
        rows.append((str(path.relative_to(home)), stat.st_size, stat.st_mtime_ns))
    return rows


def _synthetic_home(home: Path) -> None:
    seed_store(home, symbol="SPY", n=60)
    ledger = home / "ledger/trials.jsonl"
    ledger.parent.mkdir(parents=True)
    rows = [
        spine(),
        spine(
            trial_index=2,
            verdict="D",
            name="Breakout idea",
            recorded_at="2026-11-17T09:00:00+00:00",
        ),
    ]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_empty_home_is_helpful_and_exits_zero(tmp_path: Path) -> None:
    code, output = _run(tmp_path / "empty")
    assert code == 0
    assert "alpha data pull" in output
    assert "alpha test" in output
    assert "alpha setup find" in output
    assert "alpha rdagent run --dry-run" in output
    assert "profit" not in output.lower()
    assert "not advice" in output


def test_empty_home_json_is_valid(tmp_path: Path) -> None:
    code, output = _run(tmp_path / "empty", "--json")
    assert code == 0
    data = json.loads(output)
    assert sorted(data) == JSON_KEYS
    assert data["stores"] == [] and data["recent_trials"] == []


def test_synthetic_home_lists_stores_and_trials_in_plain_words(tmp_path: Path) -> None:
    _synthetic_home(tmp_path)
    code, output = _run(tmp_path)
    assert code == 0
    assert "home: 1 asset" in output
    assert "1 not checked" in output and "unchecked" not in output
    assert "no data health report" in output and "alpha data health " in output
    assert "2026-11-17" in output and "Breakout idea" in output
    assert "rule test" in output
    assert "graded D under the old rules" in output
    assert "not supported" not in output
    assert "alpha test --rule ma_cross" in output and "--asset SPY" in output
    assert "profit" not in output.lower()


def test_synthetic_home_json_has_stable_keys(tmp_path: Path) -> None:
    _synthetic_home(tmp_path)
    _, output = _run(tmp_path, "--json")
    data = json.loads(output)
    assert sorted(data) == JSON_KEYS
    assert data["stores"][0]["name"] == "home" and data["stores"][0]["asset_count"] == 1
    assert data["stores"][0]["health"] == {"pass": 0, "warn": 0, "fail": 0, "unchecked": 1}
    assert [t["name"] for t in data["recent_trials"]] == ["Breakout idea", "Trend"]
    assert sorted(data["recent_trials"][0]) == ["date", "kind", "name", "outcome", "reading"]
    assert sorted(data["paths"]) == ["own_chart_setup", "own_rule", "rdagent_idea"]
    assert sorted(data["waiting"]) == ["rdagent_proposals"]


def test_waiting_proposal_is_reported(tmp_path: Path) -> None:
    run = tmp_path / "runs/rdagent/run-1"
    folder = run / "discussion/round-1"
    folder.mkdir(parents=True)
    proposal = {"ideas": [{}, {}], "round": 1, "deadline": "2026-11-19T10:00:00+00:00"}
    (folder / "proposal.json").write_text(json.dumps(proposal))
    _, output = _run(tmp_path, "--json")
    waiting = json.loads(output)["waiting"]["rdagent_proposals"]
    assert waiting == [{"run": "run-1", "round": 1, "ideas": 2, "run_dir": str(run)}]
    assert "run-1" in _run(tmp_path)[1]


def test_next_writes_nothing(tmp_path: Path) -> None:
    _synthetic_home(tmp_path)
    before = _snapshot(tmp_path)
    for args in ((), ("--json",)):
        assert _run(tmp_path, *args)[0] == 0
    assert _snapshot(tmp_path) == before


def test_next_appears_in_help() -> None:
    result = RUNNER.invoke(app, ["--help"])
    assert result.exit_code == 0 and "next" in result.output


@pytest.mark.skipif(os.name != "posix", reason="timing check runs where the CLI is used")
def test_empty_home_is_fast(tmp_path: Path) -> None:
    import time

    start = time.monotonic()
    _run(tmp_path / "empty")
    assert time.monotonic() - start < 2.0


def test_last_night_line_shows_only_when_a_record_exists(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert json.loads(_run(home, "--json")[1])["last_night"] is None
    assert "Last night" not in _run(home)[1]
    folder = home / "nightly" / "2026-11-19-1"
    folder.mkdir(parents=True)
    line = "Last night: 2 of 2 paths worked."
    (folder / "record.json").write_text(json.dumps({"summary_line": line}))
    assert _run(home)[1].splitlines()[0] == line
    assert json.loads(_run(home, "--json")[1])["last_night"] == line


def test_two_recent_tests_point_to_the_correlation_command(tmp_path: Path) -> None:
    _synthetic_home(tmp_path)
    _, output = _run(tmp_path)
    assert "alpha results correlate <run id> <run id>" in output
