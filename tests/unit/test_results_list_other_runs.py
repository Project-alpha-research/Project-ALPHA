"""The default `alpha results` list shows ML, forecast, eval and Monte Carlo runs with a reading."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
import typer
from typer.testing import CliRunner

from alpha_cli.results_cmds import results_app
from alpha_cli.spine.ledger import append_trial

ML, FC, EV, MC = "a" * 16, "b" * 16, "c" * 16, "d" * 16
DAYS = [
    {
        "train_start": "2020-01-01",
        "train_end": "2020-12-31",
        "test_start": "2021-01-01",
        "test_end": "2021-06-30",
    },
]


def _write(rdir: Path, manifest: dict[str, object]) -> None:
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _ml(home: Path) -> None:
    rdir = home / "runs" / ML
    _write(
        rdir,
        {
            "command": "ml_replay",
            "periods_per_year": 252,
            "n_oos_periods": 500,
            "metrics": {"sharpe": 0.8125, "costed_excess_total_return": 0.01},
            "costs": {"fee_bps": 1, "slippage_bps": 2},
            "universe": ["SPY", "QQQ"],
            "label": "Research, not advice",
        },
    )
    pl.DataFrame({"fold": [1], **{k: [v] for k, v in DAYS[0].items()}}).write_parquet(
        rdir / "folds.parquet"
    )
    pl.DataFrame({"benchmark_return": [0.01, -0.02, 0.015, 0.0, 0.005]}).write_parquet(
        rdir / "ml_periods.parquet"
    )


def _forecast(home: Path) -> None:
    _write(
        home / "forecast" / FC,
        {
            "command": "forecast_run",
            "symbol": "SPY",
            "summary": {
                "median_end_return": 0.012,
                "p05_end_return": -0.05,
                "p95_end_return": 0.07,
                "prob_up": 0.6,
            },
        },
    )
    _write(
        home / "forecast" / EV,
        {
            "command": "forecast_eval",
            "symbol": "SPY",
            "origins": {"n": 8},
            "summary": {
                "crps_mean": 0.01,
                "skill_vs_rw": 0.02,
                "skill_vs_bootstrap": -0.01,
                "coverage50": 0.5,
                "coverage80": 0.8,
                "coverage90": 0.9,
                "hit_rate": 0.55,
            },
        },
    )


def _monte_carlo(home: Path) -> None:
    rdir = home / "runs" / MC
    family = {
        "family": "kronos",
        "status": "ok",
        "n_paths": 8,
        "terminal_return_q50": 0.0,
        "terminal_return_q05": -0.1,
        "terminal_return_q95": 0.1,
        "maximum_drawdown_q50": -0.05,
        "maximum_drawdown_q95": -0.2,
        "loss_probability": {"point": 1.0},
    }
    _write(
        rdir,
        {
            "command": "monte_carlo_kronos",
            "symbol": "SPY",
            "families": [family],
            "built_from": {
                "n_returns": 90,
                "first_ts": "2024-01-02T00:00:00+00:00",
                "last_ts": "2024-06-28T00:00:00+00:00",
            },
        },
    )
    pl.DataFrame({"step": [0, 1], "equity": [1.0, 1.1]}).write_parquet(
        rdir / "observed_oos.parquet"
    )
    pl.DataFrame(
        {"family": ["kronos"] * 8, "terminal_return": [-0.1 + 0.02 * i for i in range(8)]}
    ).write_parquet(rdir / "path_metrics.parquet")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    _ml(tmp_path)
    _forecast(tmp_path)
    _monte_carlo(tmp_path)
    append_trial(
        tmp_path,
        {
            "kind": "ml_run",
            "name": "qlib/lightgbm",
            "run_id": ML,
            "labels": [],
            "evidence": "recorded without a reading",
            "assets": ["SPY", "QQQ"],
        },
    )
    return tmp_path


def _items() -> list[dict[str, object]]:
    app = typer.Typer()
    app.add_typer(results_app, name="results")
    out = CliRunner().invoke(app, ["results", "--json"])
    assert out.exit_code == 0, out.output
    return json.loads(out.stdout)["items"]


def test_every_kind_is_in_the_default_list_with_a_reading(home: Path) -> None:
    by_run = {str(row["run_id"]): row for row in _items()}
    assert set(by_run) == {ML, FC, EV, MC}
    for row in by_run.values():
        assert row["evidence"] and row["evidence"] != "recorded without a reading"
    assert by_run[ML]["oos_sharpe"] == pytest.approx(0.8125, rel=1e-9, abs=1e-12)
    assert by_run[ML]["benchmark_sharpe"] is not None
    assert by_run[ML]["evidence"] == "not clear of chance"
    assert "all 8 simulated paths" not in str(by_run[MC]["evidence"]) or "too few" in str(
        by_run[MC]["evidence"]
    )


def test_the_text_list_shows_no_missing_reading(home: Path) -> None:
    app = typer.Typer()
    app.add_typer(results_app, name="results")
    shown = CliRunner().invoke(app, ["results"]).stdout
    assert "recorded without a reading" not in shown
    assert "0.81" in shown
