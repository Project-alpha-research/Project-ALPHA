"""Known answers from immutable rule-test sidecars through the positional tool command."""

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.ledger import read_trials
from alpha_cli.tool_cmds import tool_app
from alpha_cli.toolbox.runner import run
from tests.unit.test_spine_tools import RUN

DOWNSIDE = "performance.downside_ratios"
DATES = "robustness.start_end_dates"
SIDE = "trades.side_contribution"
CONCENTRATION = "trades.concentration"
START = datetime(2022, 1, 1, tzinfo=UTC)
END = datetime(2024, 7, 1, tzinfo=UTC)
PNL = [8.0, -2.0, 3.0, -1.0, 1.0, 0.0, 2.0, -3.0, 1.0, 1.0]
SIDES = ["BUY", "BUY", "SELL", "SELL", "SELL", "BUY", "BUY", "SELL", "SELL", "BUY"]


def write_trades(folder: Path, pnls: list[float], sides: list[str]) -> None:
    pl.DataFrame(
        {
            "side": sides,
            "realized_pnl": pnls,
            "realized_return": [p / 100 for p in pnls],
            "entry_ts": [START + timedelta(days=i) for i in range(len(pnls))],
            "exit_ts": [START + timedelta(days=i + 1) for i in range(len(pnls))],
        },
        schema_overrides={"side": pl.String, "realized_pnl": pl.Float64},
    ).write_parquet(folder / "trades.parquet")


def stored_run(home: Path, tool: str) -> Path:
    folder = home / "runs" / RUN
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "metadata": {"symbol": "SPY", "last_ts": END.isoformat()},
                "spine": {
                    "store": "home",
                    "labels": [],
                    "annualisation": {"periods_per_year": 365},
                },
                "oos_metrics": {"sharpe": 1.75},
            }
        )
    )
    (folder / "spec.json").write_text(json.dumps({"costs": {"fee_bps": 0, "slippage_bps": 0}}))
    dates = [START + timedelta(days=i) for i in range((END - START).days + 1)]
    jump = datetime(2023, 4, 1, tzinfo=UTC)
    equity = [1.5625 if t == jump else 1.25 for t in dates]
    equity[0] = 1.0
    if tool == DOWNSIDE:
        dates = dates[-5:]
        equity = [2048.0, 2016.0, 2079.0, 2079.0, 2079.0]
    pl.DataFrame({"ts": dates, "equity": equity}).write_parquet(folder / "equity_curve.parquet")
    pl.DataFrame(
        {
            "ts": dates,
            "strategy_equity": [value / equity[0] for value in equity],
            "benchmark_equity": [1.5 if t == END else 1.0 for t in dates],
            "available": [True] * len(dates),
            "benchmark_kind": ["passive_open_to_open_price_only"] * len(dates),
        }
    ).write_parquet(folder / "benchmark_comparison.parquet")
    write_trades(folder, PNL, SIDES)
    return folder


def test_downside_ratios(tmp_path: Path) -> None:
    stored_run(tmp_path, DOWNSIDE)
    values = run(tmp_path, DOWNSIDE, RUN)["values"]
    loss, gain = 1 / 64, 1 / 32
    assert values == pytest.approx(
        {
            "sortino": ((gain - loss) / 4) / (loss / 2) * math.sqrt(365),
            "calmar": (((1 - loss) * (1 + gain)) ** (365 / 4) - 1) / loss,
            "omega": gain / loss,
            "tail_ratio": (0.85 * gain) / (0.85 * loss),
            "sharpe": 1.75,
        }
    )


def test_date_windows(tmp_path: Path) -> None:
    stored_run(tmp_path, DATES)
    doc = run(tmp_path, DATES, RUN)
    rows = doc["result"]["windows"]
    assert len(rows) == 25
    assert {(r["start_months"], r["end_months"]) for r in rows} == {
        (s, e) for s in range(0, 13, 3) for e in range(0, 13, 3)
    }
    assert doc["values"]["positive_share"] == 5 / 25
    assert doc["values"]["beat_hold_share"] == 4 / 25
    assert (doc["values"]["total_return_min"], doc["values"]["total_return_max"]) == (0.0, 1 / 4)
    shortest = rows[-1]
    n = (datetime(2023, 7, 1) - datetime(2023, 1, 1)).days
    mean = (1 / 4 - 1 / 5) / n
    variance = ((1 / 4) ** 2 + (1 / 5) ** 2 - n * mean**2) / (n - 1)
    assert shortest["sharpe"] == pytest.approx(mean / math.sqrt(variance) * math.sqrt(365))
    assert shortest["cagr"] == 0
    assert shortest["max_drawdown"] == pytest.approx(-1 / 5)
    assert "non-default-params" in run(tmp_path, DATES, RUN, ["step_months=1"])["labels"]


def test_side_contribution(tmp_path: Path) -> None:
    stored_run(tmp_path, SIDE)
    values = run(tmp_path, SIDE, RUN)["values"]
    assert values["sides"] == "long and short"
    for side, total, wins in (("long", 8 - 2 + 0 + 2 + 1, 3), ("short", 3 - 1 + 1 - 3 + 1, 3)):
        assert values[f"{side}_count"] == 5
        assert values[f"{side}_profit_share"] == pytest.approx(total / (9 + 1))
        assert values[f"{side}_average_pnl"] == pytest.approx(total / 5)
        assert values[f"{side}_win_rate"] == wins / 5


def test_concentration(tmp_path: Path) -> None:
    stored_run(tmp_path, CONCENTRATION)
    assert run(tmp_path, CONCENTRATION, RUN)["values"] == pytest.approx(
        {
            "without_best_1": 3 + 2 + 1 + 1 + 1 + 0 - 1 - 2 - 3,
            "without_best_3": 1 + 1 + 1 + 0 - 1 - 2 - 3,
            "without_best_5": 1 + 0 - 1 - 2 - 3,
            "top_decile_share": 8 / (8 + 3 + 2 + 1 + 1 + 1 + 0 - 1 - 2 - 3),
        }
    )


def test_absent_side_and_small_trade_samples(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, SIDE)
    write_trades(folder, [2.0], ["BUY"])
    doc = run(tmp_path, SIDE, RUN)
    assert "long-only" in doc["reading"]
    for metric in ("count", "profit_share", "win_rate", "average_pnl"):
        assert doc["values"][f"short_{metric}"] is None
        assert doc["reasons"][f"short_{metric}"]
    assert doc["values"]["long_profit_share"] == 1.0
    removed = run(tmp_path, CONCENTRATION, RUN)
    assert all(value is None for value in removed["values"].values())
    assert removed["reasons"]["without_best_1"] == "Removing the best 1 leaves no closed trades."
    assert removed["reasons"]["top_decile_share"] == "Fewer than ten closed trades."
    write_trades(folder, [], [])
    empty = run(tmp_path, SIDE, RUN)
    assert empty["values"]["sides"] == "none"
    assert all(v is None for k, v in empty["values"].items() if k != "sides")
    assert all(v is None for v in run(tmp_path, CONCENTRATION, RUN)["values"].values())


def test_shares_need_positive_total_profit(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, SIDE)
    write_trades(folder, [4.0, -1.0] * 5 + [-20.0], ["BUY", "SELL"] * 5 + ["SELL"])
    sides = run(tmp_path, SIDE, RUN)
    concentrated = run(tmp_path, CONCENTRATION, RUN)
    for doc, key in (
        (sides, "long_profit_share"),
        (sides, "short_profit_share"),
        (concentrated, "top_decile_share"),
    ):
        assert doc["values"][key] is None
        assert doc["reasons"][key] == "Total closed-trade profit is not positive."
    assert sides["values"]["long_average_pnl"] == 4.0
    assert concentrated["values"]["without_best_1"] == 4 * 4 - 1 * 5 - 20


def test_no_losing_days(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, DOWNSIDE)
    pl.DataFrame(
        {"ts": [START + timedelta(days=i) for i in range(3)], "equity": [1.0, 2.0, 3.0]}
    ).write_parquet(folder / "equity_curve.parquet")
    doc = run(tmp_path, DOWNSIDE, RUN)
    for key in ("sortino", "calmar", "omega"):
        assert doc["values"][key] is None and doc["reasons"][key]
    assert doc["values"]["tail_ratio"] is None
    assert doc["reasons"]["tail_ratio"] == "The fifth percentile of returns is not a loss."


def test_single_return_is_not_measurable(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, DOWNSIDE)
    pl.DataFrame(
        {"ts": [START + timedelta(days=i) for i in range(2)], "equity": [2.0, 1.0]}
    ).write_parquet(folder / "equity_curve.parquet")
    doc = run(tmp_path, DOWNSIDE, RUN)
    for key in ("sortino", "calmar", "omega", "tail_ratio"):
        assert doc["values"][key] is None
        assert doc["reasons"][key] == "Fewer than two stored returns."
    assert doc["values"]["sharpe"] == 1.75


@pytest.mark.parametrize(
    ("tool", "file"),
    [
        (DOWNSIDE, "equity_curve.parquet"),
        (DATES, "benchmark_comparison.parquet"),
        (SIDE, "trades.parquet"),
        (CONCENTRATION, "trades.parquet"),
    ],
)
def test_missing_file_after_cached_success(tmp_path: Path, tool: str, file: str) -> None:
    folder = stored_run(tmp_path, tool)
    run(tmp_path, tool, RUN)
    (folder / file).unlink()
    with pytest.raises(SpineError, match=file):
        run(tmp_path, tool, RUN)
    assert [row["outcome"] for row in read_trials(tmp_path)][-2:] == ["attempted", "error"]


@pytest.mark.parametrize(
    ("tool", "file"), [(DOWNSIDE, "equity_curve.parquet"), (DATES, "benchmark_comparison.parquet")]
)
def test_future_observation_is_rejected(tmp_path: Path, tool: str, file: str) -> None:
    folder = stored_run(tmp_path, tool)
    frame = pl.read_parquet(folder / file)
    frame.vstack(
        frame.tail(1).with_columns(pl.lit(END + timedelta(days=1)).alias("ts"))
    ).write_parquet(folder / file)
    with pytest.raises(SpineError, match="run period"):
        run(tmp_path, tool, RUN)


@pytest.mark.parametrize("tool", [DOWNSIDE, DATES, SIDE, CONCENTRATION])
def test_full_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    from tests.unit.test_toolbox_contract import _assert_close

    stored_run(tmp_path, tool)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(tool_app, ["run", tool, RUN, "--json"])
    assert result.exit_code == 0, result.output
    doc: dict[str, Any] = json.loads(result.stdout)
    expected = json.loads(
        (Path(__file__).parents[1] / "fixtures/toolbox_run_level_checks.json").read_text()
    )
    assert all("reserved-period-seen" in fact["labels"] for fact in doc["facts"])
    _assert_close(
        {
            key: doc[key]
            for key in (
                "tool",
                "version",
                "params",
                "result",
                "values",
                "reasons",
                "basis",
                "labels",
                "figure",
                "reading",
                "caveats",
                "reserve_start",
                "settings_tried",
            )
        },
        expected[tool],
    )


def test_annualisation_from_original_run_metadata(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, DOWNSIDE)
    path = folder / "manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["spine"]["annualisation"]
    manifest["metadata"]["periods_per_year"] = 252
    path.write_text(json.dumps(manifest))
    values = run(tmp_path, DOWNSIDE, RUN)["values"]
    assert values["sortino"] == pytest.approx(math.sqrt(252) / 2)
