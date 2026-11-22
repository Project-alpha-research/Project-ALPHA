"""No trades in a scored span is a reading, not a fault; the plan says how often the rule traded.

Synthetic prices: a noisy uptrend, then a steady fall from late 2023, so a long-or-flat moving
average cross is flat through the held-back span (2024-01-01 on).
"""

from __future__ import annotations

import warnings
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import confirm_cmds
from alpha_cli.spine.confirm import plan
from alpha_cli.spine.confirm_run import confirm_run
from alpha_cli.spine.reading import TOO_LITTLE, build_reading
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore

NO_TRADES = "The rule made no trades from 2024-01-01 to 2024-05-18"


def _bars(up: int, down: int) -> pl.DataFrame:
    rng = np.random.default_rng(0)
    rise = 100.0 * np.cumprod(1.0 + 0.002 + rng.normal(0.0, 0.01, up))
    fall = rise[-1] * np.cumprod(1.0 - 0.01 + rng.normal(0.0, 0.0005, down))
    start = date(2020, 1, 1)
    rows = [
        {
            "ts": datetime.fromordinal(start.toordinal() + i).replace(tzinfo=UTC),
            **dict.fromkeys(("open", "high", "low", "close"), c),
            "volume": 1000.0,
        }
        for i, c in enumerate(np.concatenate([rise, fall]).tolist())
    ]
    return pl.DataFrame(rows)


def _home(home: Path, up: int, down: int) -> str:
    store = ParquetStore(home / "store")
    store.write_bars("SPY", _bars(up, down))
    store.write_provenance("SPY", source="alpaca", adapter_version="1", parser_version="1")
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    out = run_idea(spec, home=home, quick=True, no_diagnose=True)["results"][0]
    assert out["error"] is None, out
    return str(out["run_id"])


@pytest.fixture
def flat_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    return tmp_path, _home(tmp_path, 1400, 200)


def test_the_plan_states_the_trade_rate_and_warns_before_spending(
    flat_end: tuple[Path, str],
) -> None:
    home, run_id = flat_end
    rate = plan(home, run_id)["trade_rate"]
    assert rate["per_year"] == pytest.approx(rate["trades"] / rate["years"], rel=1e-9, abs=1e-12)
    held_years = (datetime(2024, 5, 18) - datetime(2024, 1, 1)).days / 365.25
    assert rate["expected"] == pytest.approx(rate["per_year"] * held_years, rel=1e-9, abs=1e-12)
    assert rate["expected"] < 5 and "fewer than 5" in rate["warning"]
    shown = CliRunner().invoke(confirm_cmds.confirm_app, ["plan", run_id])
    assert shown.exit_code == 0, shown.output
    assert "Trades per year (earlier period):" in shown.output
    assert rate["warning"] in shown.output
    assert not (home / "control").exists()


def test_no_trades_in_the_held_back_span_is_a_reading_without_warnings(
    flat_end: tuple[Path, str],
) -> None:
    home, run_id = flat_end
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        output = confirm_run(home, run_id)
    assert [w for w in caught if issubclass(w.category, RuntimeWarning)] == []
    reserved = output["reserved"]
    assert reserved["reading"] == TOO_LITTLE
    assert reserved["sentence"].startswith(NO_TRADES)
    assert "nothing can be concluded from this period" in reserved["sentence"]
    assert "Fault" not in reserved["sentence"]


def _manifest(trades: int, vol: float) -> dict[str, Any]:
    scored = {"first_ts": "2024-01-01T00:00:00+00:00", "last_ts": "2024-05-18T00:00:00+00:00"}
    return {
        "oos_metrics": {"sharpe": None, "max_drawdown": 0.0, "annualized_vol": vol},
        "spine": {"periods": {"scored": {**scored, "strategy": {"trades": trades}}}},
    }


def test_a_missing_sharpe_with_trades_or_movement_is_still_a_fault() -> None:
    assert build_reading(_manifest(0, 0.0))["sentence"].startswith(NO_TRADES)
    for trades, vol in ((3, 0.0), (0, 0.1)):
        found = build_reading(_manifest(trades, vol))
        assert found["sentence"].startswith("Fault: the out-of-sample Sharpe could not be computed")


def test_an_ordinary_test_with_no_trades_reads_so_without_warnings(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    closes = 100.0 * np.cumprod(1.0 - 0.001 + rng.normal(0.0, 0.0002, 1400))
    start = date(2020, 1, 1)
    store = ParquetStore(tmp_path / "store")
    store.write_bars(
        "SPY",
        pl.DataFrame(
            [
                {
                    "ts": datetime.fromordinal(start.toordinal() + i).replace(tzinfo=UTC),
                    **dict.fromkeys(("open", "high", "low", "close"), c),
                    "volume": 1000.0,
                }
                for i, c in enumerate(closes.tolist())
            ]
        ),
    )
    store.write_provenance("SPY", source="alpaca", adapter_version="1", parser_version="1")
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        out = run_idea(spec, home=tmp_path, quick=True)["results"][0]
    assert out["error"] is None, out
    assert [w for w in caught if issubclass(w.category, RuntimeWarning)] == []
    reading = (tmp_path / "runs" / out["run_id"] / "manifest.json").read_text(encoding="utf-8")
    assert "The rule made no trades from 2020-" in reading
    assert "could not be computed" not in reading
