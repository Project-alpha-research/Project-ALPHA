"""`alpha context show-derived`: the derived series on one asset's daily bars, on synthetic data."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.context_cmds import context_app
from alpha_data.store import ParquetStore
from alpha_data.timeframe import DAILY, store_dir
from tests.unit._context_attach_support import (
    bars,
    cot_rows,
    daily,
    finra_rows,
    store_cot,
    store_finra,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    days = daily(date(2023, 12, 20), 30)  # runs past the reserved day
    ParquetStore(store_dir(tmp_path, DAILY)).write_bars("SPY", bars(days))
    store_finra(
        tmp_path, finra_rows("SPY", [(d, 0.2 + 0.01 * n) for n, d in enumerate(days)]), "SPY"
    )
    store_cot(tmp_path, cot_rows([dict(report_date=date(2023, 12, 19), nl=300, ns=100)]))
    return tmp_path


def invoke(*args: str, ok: bool = True) -> str:
    result = CliRunner().invoke(context_app, ["show-derived", *args])
    assert (result.exit_code == 0) == ok, result.output + str(result.exception)
    return result.output


def test_table_columns_and_a_single_coverage_line(home: Path) -> None:
    out = invoke("--series", "sv_ratio", "--key", "SPY", "--asset", "SPY", "--rows", "0")
    lines = out.splitlines()
    assert lines[0].split() == ["bar_date", "value", "known_from", "age_days", "stale"]
    assert sum(line.startswith("Coverage:") for line in lines) == 1
    assert "2024-01" not in out.split("Coverage:")[0]  # no bar on or after the reserved day
    assert "FINRA facilities only" in out
    assert "pass" not in out.lower() and "fail" not in out.lower()


def test_json_output_names_recipe_and_hashes(home: Path) -> None:
    out = json.loads(
        invoke("--series", "cot_nc_net_oi", "--key", "13874A", "--asset", "SPY", "--json")
    )
    assert out["recipe"] == "context-derived-v1"
    assert out["rows"][-1]["value"] == pytest.approx(0.2, rel=1e-9, abs=1e-12)
    assert out["rows"][-1]["stale"] is False and len(out["used_rows_sha256"]) == 64
    assert max(r["bar_date"] for r in out["rows"]) < "2024-01-01"


def test_breadth_prints_its_label(home: Path) -> None:
    out = invoke("--series", "sv_breadth_z1", "--key", "ALL", "--asset", "SPY")
    assert "1 stored names, not market-wide" in out


def test_unknown_series_and_missing_asset_say_what_to_do(home: Path) -> None:
    assert "unknown context series" in invoke(
        "--series", "x", "--key", "K", "--asset", "SPY", ok=False
    )
    assert "no bars stored" in invoke(
        "--series", "sv_ratio", "--key", "SPY", "--asset", "QQQ", ok=False
    )
