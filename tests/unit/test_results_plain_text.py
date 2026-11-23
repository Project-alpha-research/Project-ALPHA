"""The answer of `alpha test` comes first; `results` prints a table and a one-screen summary."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_cli.main import app
from alpha_cli.results_summary import summary_lines, table
from alpha_cli.test_cmds import _echo_notes
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

ARGS = [
    "--rule", "ma_cross", "--param", "fast=10", "--param", "slow=30", "--asset", "SPY",
    "--quick", "--name", "plain", "--accept-bad-data", "synthetic weekend bars",
]  # fmt: skip


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    path = tmp_path_factory.mktemp("plain")
    mp = pytest.MonkeyPatch()
    mp.setenv("ALPHA_DATA_DIR", str(path))
    mp.setattr(_runner, "execution_fingerprint", lambda: "e" * 64)
    seed_store(path, symbol="SPY", n=1000, seed=3, drift=0.0004, sigma=0.01)
    ParquetStore(path / "store").write_provenance(
        "SPY", source="synthetic", adapter_version="1", parser_version="1"
    )
    yield path
    mp.undo()


@pytest.fixture(scope="module")
def answer(home: Path) -> str:
    result = CliRunner().invoke(app, ["test", *ARGS])
    assert result.exit_code == 0, result.output
    return result.output


def test_the_answer_comes_before_warnings_and_paths(answer: str) -> None:
    lines = answer.splitlines()
    table_at = next(i for i, line in enumerate(lines) if line.startswith("ASSET\tRUN"))
    saved_at = next(i for i, line in enumerate(lines) if "saved to:" in line)
    assert table_at < saved_at
    assert saved_at == len(lines) - 1 or all(
        "saved to:" in x or "Figure" in x for x in lines[saved_at:]
    )


def test_notes_print_warnings_before_paths(capsys: pytest.CaptureFixture[str]) -> None:
    _echo_notes("HTML report saved to: /x/tearsheet.html\nHeld back 3 bars.\nsome metric line\n")
    assert capsys.readouterr().out.splitlines() == [
        "Held back 3 bars.",
        "some metric line",
        "HTML report saved to: /x/tearsheet.html",
    ]


def test_results_show_is_one_screen_and_json_keeps_the_full_output(home: Path, answer: str) -> None:
    runner = CliRunner()
    rows = runner.invoke(app, ["results", "--json"])
    run_id = json.loads(rows.output)["items"][0]["run_id"]
    text = runner.invoke(app, ["results", "show", run_id]).output
    assert len(text.splitlines()) <= 40
    assert "Full detail: alpha results show" in text and '"runs"' not in text
    full = json.loads(runner.invoke(app, ["results", "show", run_id, "--json"]).output)
    assert full["runs"][0]["run_id"] == run_id


def test_results_by_symbol_prints_a_table_with_headers(home: Path, answer: str) -> None:
    out = CliRunner().invoke(app, ["results", "--symbol", "SPY"]).output
    head = out.splitlines()[0]
    assert "symbol" in head and "OOS Sharpe" in head and "labels" in head
    assert "['" not in out and "You have tested 1 idea on SPY" in out


def test_table_and_summary_helpers_show_a_missing_value_as_a_dash() -> None:
    assert table(("a", "b"), [[None, 1.5]]) == ["a  b", "—  1.500"]
    lines = summary_lines({"run_id": "r", "facts": [{"metric": "x_y", "value": None}]})
    assert not any("x y" in line for line in lines)
    assert lines[-1] == "Full detail: alpha results show r --json"


def test_an_empty_table_keeps_its_header() -> None:
    assert table(("a", "bb"), []) == ["a  bb"]


def test_a_setup_reading_and_outcome_are_in_the_summary() -> None:
    lines = summary_lines(
        {"run_id": "r", "reading": "Too few occurrences to read.", "outcome": "inconclusive"}
    )
    assert lines[0] == "Reading: Too few occurrences to read."
    assert lines[1] == "Outcome: inconclusive"


def test_a_failed_asset_of_a_setup_find_is_named_in_the_summary() -> None:
    lines = summary_lines(
        {
            "run_id": "r",
            "assets": [
                {"symbol": "MISSING", "error": {"code": "UNKNOWN_ASSET", "message": "not found"}},
                {"symbol": "SPY", "error": None},
            ],
        }
    )
    assert "Not completed: MISSING: not found" in lines
    assert not any("SPY" in line for line in lines)


def test_a_stored_period_reads_as_two_dates() -> None:
    period = {"first_ts": "1993-01-29T00:00:00+00:00", "last_ts": "2023-12-29T00:00:00+00:00"}
    lines = summary_lines({"run_id": "r", "facts": [{"metric": "data_period", "value": period}]})
    assert "  data period: 1993-01-29 to 2023-12-29" in lines
