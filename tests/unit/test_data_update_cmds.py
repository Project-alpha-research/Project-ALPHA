"""`alpha data coverage` and `alpha data update` on a synthetic store (M112)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
    days = [datetime(2023, 12, d, tzinfo=UTC) for d in (20, 21, 22)]
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
    assert "AAA" in out and "2023-12-20" in out and "2023-12-22" in out and "unchecked" in out
    code, raw = _run(tmp_path, "coverage", "--json")
    row = json.loads(raw)["symbols"][0]
    assert (row["symbol"], row["first"], row["last"], row["bars"], row["health"]) == (
        "AAA",
        "2023-12-20",
        "2023-12-22",
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
    assert "AAA: would run alpha data pull AAA --source yfinance --start 2023-12-20 --end " in out
    assert "re-pulls every day from the first stored bar" in out
    assert (home / "store" / "bars" / "AAA.parquet").read_bytes() == before


def test_update_dry_run_prints_the_pull_note_once_for_many_symbols(tmp_path: Path) -> None:
    home = _home(tmp_path)
    store = ParquetStore(home / "store")
    store.write_bars("BBB", store.read_bars("AAA"))
    store.write_provenance("BBB", source="yfinance", adapter_version="1", parser_version="1")
    code, out = _run(home, "update", "--dry-run")
    assert code == 0
    assert "AAA: would run" in out and "BBB: would run" in out
    assert out.count("re-pulls every day from the first stored bar") == 1


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
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    assert f"The newest day asked for is {yesterday} (UTC). Today's bar arrives" in out


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


def test_coverage_reads_a_series_without_provenance(tmp_path: Path) -> None:
    home = _home(tmp_path)
    (home / "store" / "provenance" / "AAA.json").unlink()
    row = json.loads(_run(home, "coverage", "--json")[1])["symbols"][0]
    assert (row["bars"], row["first"], row["last"]) == (3, "2023-12-20", "2023-12-22")


def test_coverage_says_why_a_series_cannot_be_read_instead_of_showing_zero(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    (home / "store" / "bars" / "AAA.parquet").write_bytes(b"not a parquet file")
    row = json.loads(_run(home, "coverage", "--json")[1])["symbols"][0]
    assert row["bars"] is None and "cannot be read" in row["note"]
    text = _run(home, "coverage")[1]
    assert "cannot be read" in text


def test_coverage_says_the_dates_stop_at_the_held_back_boundary(tmp_path: Path) -> None:
    code, out = _run(_home(tmp_path), "coverage")
    assert code == 0
    assert out.splitlines()[0].startswith("Dates and bars stop before 2024-01-01")


def test_out_of_date_health_says_why() -> None:
    from datetime import date

    from alpha_cli.data_update_cmds import out_of_date_reason

    said = out_of_date_reason({"symbol": "AAA", "last": "2024-01-05"}, date(2024, 1, 9))
    assert "stored bars changed after it was written" in said
    assert "newest stored bar 2024-01-05; today is 2024-01-09" in said
