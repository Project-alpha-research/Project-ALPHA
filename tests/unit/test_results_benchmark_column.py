"""`alpha results` heads the column 'benchmark Sharpe' and names each row's benchmark and period.

The trial ledger is replaced through `results_cmds.read_trials` (the call `list_results` makes)
so that one rule-test row and one ML row are listed; a real forecast folder adds a folder row.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import results_cmds
from alpha_cli.results_cmds import results_app

FC = "b" * 16
RULE_RUN = "e" * 16
ML_RUN = "f" * 16


def _forecast(home: Path) -> None:
    rdir = home / "forecast" / FC
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text(
        json.dumps(
            {
                "command": "forecast_run",
                "symbol": "SPY",
                "summary": {
                    "median_end_return": 0.012,
                    "p05_end_return": -0.05,
                    "p95_end_return": 0.07,
                    "prob_up": 0.6,
                },
            }
        ),
        encoding="utf-8",
    )


def _trials() -> list[dict[str, Any]]:
    return [
        {
            "trial_index": 1,
            "recorded_at": "2026-01-01T00:00:00+00:00",
            "kind": "rule_test",
            "name": "momorule",
            "symbol": "SPY",
            "verdict": None,
            "oos_sharpe": 1.5,
            "benchmark_sharpe": 0.75,
            "labels": [],
            "run_id": RULE_RUN,
            "idea_id": "idea-one",
            "flags": [],
        },
        {
            "trial_index": 2,
            "recorded_at": "2026-01-02T00:00:00+00:00",
            "kind": "ml_run",
            "name": "mlbasket",
            "symbol": "SPY",
            "verdict": None,
            "oos_sharpe": 1.25,
            "benchmark_sharpe": 0.25,
            "labels": [],
            "run_id": ML_RUN,
            "idea_id": "idea-two",
            "flags": [],
        },
    ]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _forecast(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(results_cmds, "read_trials", lambda _home: _trials())
    return tmp_path


def _text(args: list[str]) -> str:
    result = CliRunner().invoke(results_app, args)
    assert result.exit_code == 0, result.output
    return result.output


def _line(out: str, word: str) -> str:
    lines = [line for line in out.splitlines() if word in line]
    assert lines, out
    return lines[0]


def test_header_says_benchmark_sharpe(home: Path) -> None:
    out = _text(["--limit", "20"])
    assert "benchmark Sharpe" in out
    assert "buy-and-hold Sharpe" not in out


def test_rule_row_names_buy_and_hold_full_history(home: Path) -> None:
    out = _text(["--limit", "20"])
    line = _line(out, "momorule")
    assert "buy-and-hold, full history" in line
    assert "equal-weight basket" not in line


def test_ml_row_names_equal_weight_basket_scored_days(home: Path) -> None:
    out = _text(["--limit", "20"])
    line = _line(out, "mlbasket")
    assert "equal-weight basket, scored days" in line
    assert "buy-and-hold" not in line


def test_folder_row_names_no_benchmark(home: Path) -> None:
    out = _text(["--limit", "20"])
    assert "benchmark Sharpe" in out
    line = _line(out, "forecast_run")
    assert "buy-and-hold" not in line
    assert "equal-weight basket" not in line


def test_benchmark_numbers_unchanged(home: Path) -> None:
    out = _text(["--limit", "20"])
    assert "0.75" in _line(out, "momorule")
    assert "0.25" in _line(out, "mlbasket")
    data = json.loads(_text(["--limit", "20", "--json"]))
    by_name = {item["name"]: item for item in data["items"]}
    assert by_name["momorule"]["benchmark_sharpe"] == 0.75
    assert by_name["mlbasket"]["benchmark_sharpe"] == 0.25
    assert by_name["forecast_run"]["benchmark_sharpe"] is None
