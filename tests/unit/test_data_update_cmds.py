"""`alpha data coverage` and `alpha data update` on a synthetic store (M112)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_data.adapters.yfinance_adapter import YFinanceAdapter
from alpha_data.store import ParquetStore

RUNNER = CliRunner()


def _home(tmp_path: Path, source: str = YFinanceAdapter.name) -> Path:
    store = ParquetStore(tmp_path / "store")
    days = [datetime(2024, 1, d, tzinfo=UTC) for d in (2, 3, 4)]
    store.write_bars(
        "AAA",
        pl.DataFrame(
            {
                "ts": days,
                **{k: [10.0, 10.5, 11.0] for k in ("open", "high", "low", "close")},
                "volume": [100.0, 100.0, 100.0],
            }
        ),
    )
    store.write_provenance("AAA", source=source, adapter_version="1", parser_version="1")
    return tmp_path


def _run(home: Path, *args: str) -> tuple[int, str]:
    result = RUNNER.invoke(app, ["data", *args], env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, result.output


def test_coverage_table_and_json(tmp_path: Path) -> None:
    code, out = _run(_home(tmp_path), "coverage")
    assert code == 0
    assert "first date" in out and "health" in out
    assert "AAA" in out and "2024-01-02" in out and "2024-01-04" in out and "unchecked" in out
    code, raw = _run(tmp_path, "coverage", "--json")
    row = json.loads(raw)["symbols"][0]
    assert (row["symbol"], row["first"], row["last"], row["bars"], row["health"]) == (
        "AAA",
        "2024-01-02",
        "2024-01-04",
        3,
        "unchecked",
    )


def test_coverage_of_an_empty_store_says_so(tmp_path: Path) -> None:
    code, out = _run(tmp_path, "coverage")
    assert code == 0 and "No data is stored yet" in out


def test_update_dry_run_prints_the_pull_and_pulls_nothing(tmp_path: Path) -> None:
    home = _home(tmp_path)
    before = (home / "store" / "bars" / "AAA.parquet").read_bytes()
    code, out = _run(home, "update", "--dry-run")
    assert code == 0
    assert "AAA: would run alpha data pull AAA --source yfinance --start 2024-01-02 --end " in out
    assert (home / "store" / "bars" / "AAA.parquet").read_bytes() == before


def test_update_skips_a_symbol_whose_source_has_no_pull_and_fails(tmp_path: Path) -> None:
    code, out = _run(_home(tmp_path, source="vendor"), "update", "--dry-run")
    assert code == 1 and "AAA: skipped" in out


def test_update_help_lists_dry_run() -> None:
    assert "--dry-run" in RUNNER.invoke(app, ["data", "update", "--help"]).output


@pytest.mark.parametrize("name", ["coverage", "update"])
def test_the_commands_are_listed_in_data_help(name: str) -> None:
    assert name in RUNNER.invoke(app, ["data", "--help"]).output


def test_update_runs_the_pull_for_each_symbol_and_reports_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    calls: list[list[str]] = []

    def fake(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 2, "", "provider said no\n")

    monkeypatch.setattr("alpha_cli.data_update_cmds.subprocess.run", fake)
    code, out = _run(_home(tmp_path), "update")
    assert code == 1 and "AAA: failed (exit 2). provider said no" in out
    assert "pull" in calls[0] and "AAA" in calls[0]


def test_update_keeps_the_pull_report_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    out = "pulled AAA: 3 bars\nsnapshot pull-1 kept; 2 bars revised\n"

    def fake(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr("alpha_cli.data_update_cmds.subprocess.run", fake)
    code, text = _run(_home(tmp_path), "update")
    assert code == 0 and "AAA: updated." in text and "2 bars revised" in text
