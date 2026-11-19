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
from alpha_cli.toolbox.inputs import HOLD_KINDS
from alpha_cli.toolbox.runner import run
from tests.unit.test_spine_tools import RUN

COSTS = "costs.break_even"
DOWNSIDE = "performance.downside_ratios"
DATES = "robustness.start_end_dates"
SIDE = "trades.side_contribution"
CONCENTRATION = "trades.concentration"
PRICE_ONLY = "passive_open_to_open_price_only"
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


def stored_run(home: Path, tool: str, kind: str = PRICE_ONLY) -> Path:
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
            "benchmark_kind": [kind] * len(dates),
        }
    ).write_parquet(folder / "benchmark_comparison.parquet")
    write_trades(folder, PNL, SIDES)
    if tool == COSTS:
        write_costs(folder, [0.1], [0.02], 0.04)
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


@pytest.mark.parametrize("kind", sorted(HOLD_KINDS))
def test_date_windows(tmp_path: Path, kind: str) -> None:
    # The dividend-inclusive line is read like the price-only one: same windows, same numbers.
    stored_run(tmp_path, DATES, kind)
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


def test_month_shifts_clip_to_the_last_day() -> None:
    from alpha_cli.toolbox.families.robustness import shift_months

    assert shift_months(datetime(2024, 8, 31, tzinfo=UTC), -6) == datetime(2024, 2, 29, tzinfo=UTC)
    assert shift_months(datetime(2023, 11, 30, tzinfo=UTC), 3) == datetime(2024, 2, 29, tzinfo=UTC)
    assert shift_months(datetime(2023, 1, 15, tzinfo=UTC), -12) == datetime(2022, 1, 15, tzinfo=UTC)


def test_side_contribution(tmp_path: Path) -> None:
    stored_run(tmp_path, SIDE)
    values = run(tmp_path, SIDE, RUN)["values"]
    assert values["sides"] == "long and short"
    for side, total, wins in (("long", 8 - 2 + 0 + 2 + 1, 3), ("short", 3 - 1 + 1 - 3 + 1, 3)):
        assert values[f"{side}_count"] == 5 and type(values[f"{side}_count"]) is int
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
    ("tool", "file"),
    [
        (DOWNSIDE, "equity_curve.parquet"),
        (DATES, "benchmark_comparison.parquet"),
        (COSTS, "equity_curve.parquet"),
        (COSTS, "benchmark_comparison.parquet"),
    ],
)
def test_future_observation_is_rejected(tmp_path: Path, tool: str, file: str) -> None:
    folder = stored_run(tmp_path, tool)
    frame = pl.read_parquet(folder / file)
    frame.vstack(
        frame.tail(1).with_columns(pl.lit(END + timedelta(days=1)).alias("ts"))
    ).write_parquet(folder / file)
    with pytest.raises(SpineError, match="run period"):
        run(tmp_path, tool, RUN)


@pytest.mark.parametrize("tool", [DOWNSIDE, DATES, SIDE, CONCENTRATION, COSTS])
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
    stored = {**doc, "labels": [word for word in doc["labels"] if word != "exploratory"]}
    _assert_close(
        {
            key: stored[key]
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


def write_costs(
    folder: Path, gross: list[float], cost: list[float], hold: float, kind: str = PRICE_ONLY
) -> None:
    dates = [END - timedelta(days=i) for i in reversed(range(len(gross) + 1))]
    equity = [1.0]
    for g, c in zip(gross, cost, strict=True):
        equity.append(equity[-1] * (1 + g - c))
    pl.DataFrame(
        {
            "ts": dates,
            "equity": equity,
            "gross_return": [0.0, *gross],
            "cost_return": [0.0, *cost],
        }
    ).write_parquet(folder / "equity_curve.parquet")
    pl.DataFrame(
        {
            "ts": dates,
            "strategy_equity": equity,
            "available": [True] * len(dates),
            "benchmark_equity": [1.0] * len(gross) + [1 + hold],
            "benchmark_kind": [kind] * len(dates),
        }
    ).write_parquet(folder / "benchmark_comparison.parquet")


@pytest.mark.parametrize("kind", sorted(HOLD_KINDS))
def test_break_even(tmp_path: Path, kind: str) -> None:
    folder = stored_run(tmp_path, COSTS)
    # Two identical bars: (1.1 - .02k)^2 = 1 at k=5, and = 1.04^2 at k=3.
    # At 100x both factors are negative. Their product cannot revive a bankrupt account.
    write_costs(folder, [0.1, 0.1], [0.02, 0.02], 1.04**2 - 1, kind)
    values = run(tmp_path, COSTS, RUN)["values"]
    assert [values[k] for k in ("zero_multiple", "hold_multiple", "cost_share")] == pytest.approx(
        [5, 3, 0.2], rel=1e-9, abs=1e-12
    )


@pytest.mark.parametrize(
    ("gross", "cost", "multiple", "phrase"),
    [
        (0.01, 0.02, 0.5, "not positive at today's costs"),
        (0.02, 0.02, 1.0, "not positive at today's costs"),
        (-0.01, 0.02, None, "not positive even with no costs"),
        (0.0, 0.02, 0.0, "not positive even with no costs"),
        (0.11, 0.001, None, "still positive at 100 times today's costs"),
        (0.1, 0.001, 100.0, "100"),
        (0.1, 0.0, None, "this run charged no costs"),
    ],
)
def test_cost_limits(
    tmp_path: Path, gross: float, cost: float, multiple: float | None, phrase: str
) -> None:
    folder = stored_run(tmp_path, COSTS)
    write_costs(folder, [gross], [cost], 0.04)
    doc = run(tmp_path, COSTS, RUN)
    assert phrase in doc["reading"].lower()
    if multiple is None:
        assert doc["values"]["zero_multiple"] is None and doc["reasons"]["zero_multiple"]
    else:
        assert doc["values"]["zero_multiple"] == pytest.approx(multiple, rel=1e-9, abs=1e-12)
    if gross <= 0:
        assert doc["values"]["cost_share"] is None and doc["reasons"]["cost_share"]
    if cost == 0:
        assert doc["values"]["hold_multiple"] is None and doc["values"]["cost_share"] == 0


def test_old_cost_layout(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, DOWNSIDE)
    path = folder / "equity_curve.parquet"
    original = path.read_bytes()
    doc = run(tmp_path, COSTS, RUN)
    assert "this run was made before costs were stored per bar" in doc["reading"].lower()
    assert "run the rule test again" in doc["reading"].lower()
    assert all(doc["values"][k] is None for k in ("zero_multiple", "hold_multiple", "cost_share"))
    assert run(tmp_path, DOWNSIDE, RUN)["values"]["sharpe"] == 1.75
    assert path.read_bytes() == original


def test_cost_writer_reconciles_scored_fills(tmp_path: Path) -> None:
    from dataclasses import replace

    import numpy as np

    from alpha_cli import _artifacts, _runner
    from alpha_cli.spine.run import assemble_run_spec
    from alpha_cli.spine.spec import load_spec
    from alpha_cli.validate_cmds import scored_bar_returns
    from alpha_core import DataError
    from tests.unit.test_spine_controls import _bars

    idea = load_spec(
        None,
        rule="ma_cross",
        param=["fast=1", "slow=2"],
        asset=["SPY"],
        fee_bps=10,
        slippage_bps=10,
    )
    spec = replace(assemble_run_spec(idea, "SPY", 252, 100), starting_cash=11000)
    bars = _bars()
    result = _runner.fresh_scored_execution(
        bars, spec, first_scored_index=3, final_scored_index=5, normalize_equity=True
    )
    equity = result.equity_curve
    net = np.diff([v for _, v in equity]) / np.array([v for _, v in equity[:-1]])
    gross, costs = scored_bar_returns(bars, spec, result, net)
    _artifacts.write_run_sidecars(
        tmp_path, equity=equity, trades=result.trades, bar_returns=(gross, costs)
    )
    frame = pl.read_parquet(tmp_path / "equity_curve.parquet")
    # 99 shares on each fill. Buy at the ask 110.11, sell at the bid 119.88, buy at the ask 90.09.
    # The engine values a long at the bid, so a buy costs the whole gap to the bid (109.89, 89.91)
    # in its own bar and the sell costs only its fee. Fees round per fill in quote currency.
    # The terminal sample settles the last TWO fills.
    cash_costs = [0, 99 * 0.22 + 10.90, 11.87 + 99 * 0.18 + 8.92]
    assert frame["cost_return"].to_list() == pytest.approx(
        [0, cash_costs[1] / 11000, cash_costs[2] / 11956.33], rel=1e-9, abs=1e-12
    )
    assert frame["ts"].to_list() == [ts for ts, _ in equity]
    assert (frame["gross_return"] - frame["cost_return"]).to_list() == pytest.approx(
        [0, *net], rel=0, abs=1e-12
    )
    old = tmp_path / "old"
    _artifacts.write_run_sidecars(old, equity=equity, trades=result.trades)
    projected = tmp_path / "projected.parquet"
    frame.drop("gross_return", "cost_return").write_parquet(projected)
    assert projected.read_bytes() == (old / "equity_curve.parquet").read_bytes()
    with pytest.raises(DataError, match="gross_return"):
        _artifacts.write_run_sidecars(
            tmp_path / "bad", equity=equity, trades=[], bar_returns=(gross + 0.01, costs)
        )


def test_cost_timing_matches_engine_equity_over_several_trades() -> None:
    from dataclasses import replace

    import numpy as np
    from nautilus_trader.model.objects import Price

    from alpha_cli import _runner
    from alpha_cli.spine.run import assemble_run_spec
    from alpha_cli.spine.spec import load_spec
    from alpha_cli.validate_cmds import scored_bar_returns
    from alpha_core import Bar

    prices = [100, 100, 110, 115, 120, 90, 95, 100, 105, 101, 97, 104, 108, 99, 103]
    bars = [
        Bar(
            symbol="SPY",
            ts=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=p,
            high=p,
            low=p,
            close=p,
            volume=1000000,
        )
        for i, p in enumerate(prices)
    ]
    idea = load_spec(
        None,
        rule="ma_cross",
        param=["fast=1", "slow=2"],
        asset=["SPY"],
        fee_bps=10,
        slippage_bps=10,
    )
    spec = replace(assemble_run_spec(idea, "SPY", 252, 100), starting_cash=11000)
    result = _runner.fresh_scored_execution(
        bars, spec, first_scored_index=3, final_scored_index=14, normalize_equity=True
    )
    # Three round trips, positions held across several bars, the last sell on the terminal bar.
    assert [f.side for f in result.fill_trace] == ["BUY", "SELL"] * 3
    assert result.fill_trace[-1].ts == result.equity_curve[-1][0]
    dollars = np.array([v for _, v in result.equity_curve]) * spec.starting_cash
    net = np.diff(dollars) / dollars[:-1]
    gross, costs = scored_bar_returns(bars, spec, result, net)
    # Independent of the fills split: before-cost profit is the units held after each open
    # times the move in the bid the engine values them at. The final sell settles in the last bar.
    opens = {bar.ts: bar.open for bar in bars}
    bid = np.array([float(Price(opens[ts] * 0.999, 2)) for ts, _ in result.equity_curve])
    held, units = [], 0.0
    fills = {f.ts: f for f in result.fill_trace}
    for ts, _ in result.equity_curve[:-1]:
        if ts in fills:
            units += fills[ts].quantity if fills[ts].side == "BUY" else -fills[ts].quantity
        held.append(units)
    expected = np.array(held) * np.diff(bid) / dollars[:-1]
    assert gross.tolist() == pytest.approx(expected.tolist(), rel=1e-9, abs=1e-12)
    assert (gross - costs).tolist() == pytest.approx(net.tolist(), rel=0, abs=1e-12)
    assert float(np.prod(1 + gross - costs)) == pytest.approx(dollars[-1] / dollars[0], rel=1e-12)
    # First bar: buy 95 at 115.11 against a bid of 114.89, fee 10.94.
    assert costs[0] == pytest.approx((95 * 0.22 + 10.94) / 11000, rel=1e-9, abs=1e-12)
    assert np.all(costs >= 0) and np.count_nonzero(costs) == 6


def test_hold_matches_gross_at_zero_cost_and_share_uses_capital(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, COSTS)
    write_costs(folder, [0.1, 0.0], [0.0, 0.02], 0.1)
    doc = run(tmp_path, COSTS, RUN)
    assert doc["values"]["hold_multiple"] == pytest.approx(0, rel=1e-9, abs=1e-12)
    # Costs on the second bar use 1.10 of capital. The first bar earned 0.10.
    assert doc["values"]["cost_share"] == pytest.approx(1.10 * 0.02 / 0.10, rel=1e-9, abs=1e-12)


def test_hold_threshold_below_today(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, COSTS)
    # 1.10 - 0.02k = 1.09 at k = 0.5; 1.10 - 0.02k = 1 at k = 5.
    write_costs(folder, [0.1], [0.02], 0.09)
    doc = run(tmp_path, COSTS, RUN)
    assert doc["values"]["hold_multiple"] == pytest.approx(0.5, rel=1e-9, abs=1e-12)
    assert doc["values"]["sentence"] == (
        "The result breaks even at 5 times today's costs. The result does not beat buy and hold"
        " at today's costs. It matches buy and hold at 0.5 times today's costs."
    )
