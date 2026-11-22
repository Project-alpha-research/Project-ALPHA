"""Known answers for the performance-statistics checks on small synthetic stored runs."""

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from scipy import stats

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.runner import run
from tests.unit.test_spine_tools import RUN

START = datetime(2022, 1, 3, tzinfo=UTC)
END = datetime(2022, 12, 30, tzinfo=UTC)
PPY = 252
# 31 equity points: flat at 100, a fall to 90 (a 10% drawdown), then a new peak at 110.
LEVELS = [100.0] * 10 + [90.0] * 5 + [110.0] * 16
# Entry-ordered trade profits and holding days; the zero is a break-even trade.
PNL = [4.0, -2.0, 6.0, -1.0, -3.0, -1.0, 5.0, 0.0, 2.0, -4.0, 1.0, 3.0, -2.0]
DAYS = [1, 2, 3, 1, 5, 2, 4, 1, 10, 2, 3, 1, 6]
ALL = [
    "performance.ulcer",
    "performance.pain",
    "performance.sterling_burke",
    "performance.recovery_factor",
    "performance.gain_to_pain",
    "performance.kappa",
    "performance.lo_sharpe",
    "performance.cornish_fisher_sharpe",
    "performance.worst_windows",
    "performance.payoff_expectancy",
    "performance.streaks",
    "performance.holding_period",
]
TRADE_TOOLS = ALL[-3:]
CAGR = (110 / 100) ** (PPY / 30) - 1


def stored_run(
    home: Path, levels: list[float] | None = None, pnl: list[float] | None = None
) -> Path:
    folder = home / "runs" / RUN
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "metadata": {"symbol": "SPY", "last_ts": END.isoformat(), "starting_cash": 100.0},
                "spine": {
                    "store": "home",
                    "labels": [],
                    "annualisation": {"periods_per_year": PPY},
                },
                "oos_metrics": {"sharpe": 1.0},
            }
        )
    )
    (folder / "spec.json").write_text(json.dumps({"costs": {"fee_bps": 0, "slippage_bps": 0}}))
    equity = LEVELS if levels is None else levels
    dates = [START + timedelta(days=i) for i in range(len(equity))]
    pl.DataFrame({"ts": dates, "equity": equity}).write_parquet(folder / "equity_curve.parquet")
    profits = PNL if pnl is None else pnl
    spans = (DAYS * 3)[: len(profits)]
    pl.DataFrame(
        {
            "side": ["BUY"] * len(profits),
            "realized_pnl": profits,
            "realized_return": [p / 100 for p in profits],
            "entry_ts": [START + timedelta(days=i) for i in range(len(profits))],
            "exit_ts": [START + timedelta(days=i + d) for i, d in enumerate(spans)],
        }
    ).write_parquet(folder / "trades.parquet")
    return folder


def values(home: Path, tool: str, raw: list[str] | None = None) -> dict[str, Any]:
    got: dict[str, Any] = run(home, tool, RUN, raw)["values"]
    return got


def returns() -> np.ndarray:
    levels = np.array(LEVELS)
    out: np.ndarray = levels[1:] / levels[:-1] - 1
    return out


def test_ulcer(tmp_path: Path) -> None:
    # Martin and McCann (1989): ulcer = root of the mean squared percentage drawdown.
    stored_run(tmp_path)
    got = values(tmp_path, "performance.ulcer")
    index = math.sqrt(5 * 0.1**2 / 31)
    assert got == pytest.approx(
        {"ulcer_index": index, "cagr": CAGR, "martin_ratio": CAGR / index}, rel=1e-9, abs=1e-12
    )


def test_pain(tmp_path: Path) -> None:
    stored_run(tmp_path)
    index = 5 * 0.1 / 31
    got = values(tmp_path, "performance.pain")
    assert got == pytest.approx(
        {"pain_index": index, "cagr": CAGR, "pain_ratio": CAGR / index}, rel=1e-9, abs=1e-12
    )


def test_sterling_burke(tmp_path: Path) -> None:
    # One 10% episode: its depth is both the average depth and the root of the sum of squares.
    stored_run(tmp_path)
    got = values(tmp_path, "performance.sterling_burke")
    assert got["episodes"] == 1
    assert got["sterling_ratio"] == pytest.approx(CAGR / 0.1, rel=1e-9, abs=1e-12)
    assert got["burke_ratio"] == pytest.approx(CAGR / 0.1, rel=1e-9, abs=1e-12)
    # Two episodes of 10% and 20%: mean 0.15, root of squares sqrt(0.05).
    levels = [100.0] * 5 + [90.0] * 5 + [110.0] * 5 + [88.0] * 5 + [120.0] * 11
    stored_run(tmp_path / "two", levels)
    two = values(tmp_path / "two", "performance.sterling_burke")
    growth = (120 / 100) ** (PPY / 30) - 1
    assert two["episodes"] == 2
    assert two["sterling_ratio"] == pytest.approx(growth / ((0.1 + 0.2) / 2), rel=1e-9, abs=1e-12)
    assert two["burke_ratio"] == pytest.approx(growth / math.sqrt(0.01 + 0.04), rel=1e-9)
    capped = values(tmp_path / "two", "performance.sterling_burke", ["top=1"])
    assert capped["episodes"] == 1
    assert capped["sterling_ratio"] == pytest.approx(growth / 0.2, rel=1e-9, abs=1e-12)


def test_recovery_factor(tmp_path: Path) -> None:
    stored_run(tmp_path)
    got = values(tmp_path, "performance.recovery_factor")
    assert got == {"net_profit": 10.0, "max_drawdown_amount": 10.0, "recovery_factor": 1.0}


def test_gain_to_pain(tmp_path: Path) -> None:
    stored_run(tmp_path)
    got = values(tmp_path, "performance.gain_to_pain")
    gain = 110 / 90 - 1
    assert got["return_sum"] == pytest.approx(gain - 0.1, rel=1e-9, abs=1e-12)
    assert got["loss_sum"] == pytest.approx(-0.1, rel=1e-9, abs=1e-12)
    assert got["gain_to_pain"] == pytest.approx(11 / 9, rel=1e-9, abs=1e-12)


def test_kappa(tmp_path: Path) -> None:
    # Kaplan and Knowles (2004): (mean - tau) / LPM_n^(1/n); n=1 is Omega - 1, n=2 is Sortino.
    stored_run(tmp_path)
    mean = (110 / 90 - 1 - 0.1) / 30
    for order in (1, 2, 3):
        got = values(tmp_path, "performance.kappa", [f"order={order}"])
        moment = 0.1**order / 30
        assert got["lower_partial_moment"] == pytest.approx(moment, rel=1e-9, abs=1e-12)
        assert got["kappa"] == pytest.approx(mean / moment ** (1 / order), rel=1e-9, abs=1e-12)
        upside = (110 / 90 - 1) / 30 / math.sqrt(0.01 / 30)
        assert got["upside_potential_ratio"] == pytest.approx(upside, rel=1e-9, abs=1e-12)
    omega = (110 / 90 - 1) / 0.1
    assert values(tmp_path, "performance.kappa", ["order=1"])["kappa"] == pytest.approx(omega - 1)
    assert values(tmp_path, "performance.kappa", ["threshold=0.01"])["kappa"] == pytest.approx(
        (mean - 0.01) / (math.fsum(max(0.01 - x, 0) ** 3 for x in returns()) / 30) ** (1 / 3)
    )
    stored_run(tmp_path / "up", [100.0 + i for i in range(30)])
    assert values(tmp_path / "up", "performance.kappa")["kappa"] is None
    with pytest.raises(SpineError):
        run(tmp_path, "performance.kappa", RUN, ["threshold=nan"])


def test_lo_sharpe(tmp_path: Path) -> None:
    # Lo (2002): SR(q) = SR * q / sqrt(q + 2 * sum_k (q - k) rho_k), written out lag by lag.
    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, 0.01, 80)
    series = noise.copy()
    for t in range(1, 80):
        series[t] += 0.4 * series[t - 1]
    levels = [100.0, *(100.0 * np.cumprod(1 + series + 0.002)).tolist()]
    stored_run(tmp_path, levels)
    got = values(tmp_path, "performance.lo_sharpe", ["max_lag=5"])
    r = np.array(levels[1:]) / np.array(levels[:-1]) - 1
    mean = sum(r) / len(r)
    var0 = sum((x - mean) ** 2 for x in r)
    rho = [
        sum((r[t] - mean) * (r[t - k] - mean) for t in range(k, len(r))) / var0 for k in range(1, 6)
    ]
    q = PPY
    spread = q + 2 * sum((q - k) * rho[k - 1] for k in range(1, 6))
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / (len(r) - 1))
    assert got["first_autocorrelation"] == pytest.approx(rho[0], rel=1e-9, abs=1e-12)
    assert got["sharpe"] == pytest.approx(mean / sd * math.sqrt(q), rel=1e-9, abs=1e-12)
    assert got["adjusted_sharpe"] == pytest.approx(mean / sd * q / math.sqrt(spread), rel=1e-9)
    assert got["lags_used"] == 5
    assert rho[0] > 0.2 and abs(got["adjusted_sharpe"]) < abs(got["sharpe"])


def test_cornish_fisher_sharpe(tmp_path: Path) -> None:
    # Pezier and White (2008): SR * (1 + S/6 * SR - (K - 3)/24 * SR^2) on the bar Sharpe.
    stored_run(tmp_path)
    got = values(tmp_path, "performance.cornish_fisher_sharpe")
    r = returns()
    sr = float(np.mean(r) / np.std(r, ddof=1))
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r))
    factor = 1 + skew / 6 * sr - kurt / 24 * sr**2
    assert got["skewness"] == pytest.approx(skew, rel=1e-9, abs=1e-12)
    assert got["excess_kurtosis"] == pytest.approx(kurt, rel=1e-9, abs=1e-12)
    assert got["sharpe"] == pytest.approx(sr * math.sqrt(PPY), rel=1e-9, abs=1e-12)
    assert got["adjusted_sharpe"] == pytest.approx(sr * factor * math.sqrt(PPY), rel=1e-9)


def test_worst_windows(tmp_path: Path) -> None:
    stored_run(tmp_path)
    got = values(tmp_path, "performance.worst_windows")
    fall = (START + timedelta(days=10)).date().isoformat()
    assert got["worst_1"] == pytest.approx(-0.1, rel=1e-9, abs=1e-12)
    assert got["worst_1_end"] == fall
    assert got["worst_5"] == pytest.approx(-0.1, rel=1e-9, abs=1e-12)
    # The first 5-bar window that holds the fall ends at the fall itself.
    assert got["worst_5_end"] == fall
    # Every 21-bar window holds the fall and the rebound: the worst one still gained 10%.
    assert got["worst_21"] == pytest.approx(0.1, rel=1e-9, abs=1e-12)


def test_payoff_expectancy(tmp_path: Path) -> None:
    stored_run(tmp_path)
    got = values(tmp_path, "performance.payoff_expectancy")
    assert got["trades"] == 13
    assert got["payoff_ratio"] == pytest.approx(3.5 / (13 / 6), rel=1e-9, abs=1e-12)
    assert got["expectancy"] == pytest.approx(8 / 13, rel=1e-9, abs=1e-12)
    assert got["expectancy_in_average_losses"] == pytest.approx(8 / 13 / (13 / 6), rel=1e-9)
    stored_run(tmp_path / "wins", pnl=[1.0] * 10)
    only = values(tmp_path / "wins", "performance.payoff_expectancy")
    assert only["payoff_ratio"] is None and only["expectancy"] == 1.0


def test_streaks(tmp_path: Path) -> None:
    stored_run(tmp_path)
    got = values(tmp_path, "performance.streaks")
    assert got == {
        "trades": 13,
        "longest_win_streak": 2,
        "longest_loss_streak": 3,
        "loss_streaks": 4,
        "average_loss_streak": 1.5,
    }


def test_holding_period(tmp_path: Path) -> None:
    stored_run(tmp_path)
    got = values(tmp_path, "performance.holding_period")
    assert got == pytest.approx(
        {
            "trades": 13,
            "median_days": 2.0,
            "mean_days": 41 / 13,
            "shortest_days": 1.0,
            "longest_days": 10.0,
            "winners_mean_days": 22 / 6,
            "losers_mean_days": 3.0,
        },
        rel=1e-9,
        abs=1e-12,
    )


@pytest.mark.parametrize("tool", ALL)
def test_too_little_data(tmp_path: Path, tool: str) -> None:
    stored_run(tmp_path, LEVELS[:11], PNL[:9])
    doc = run(tmp_path, tool, RUN)
    unread = [k for k, v in doc["values"].items() if v is None]
    assert unread and all("Too little to read" in doc["reasons"][k] for k in unread)
    if tool in TRADE_TOOLS:
        assert doc["values"]["trades"] == 9


@pytest.mark.parametrize("tool", ALL)
def test_repeat_is_identical(tmp_path: Path, tool: str) -> None:
    results = []
    for name in ("first", "second"):
        stored_run(tmp_path / name)
        results.append(json.dumps(run(tmp_path / name, tool, RUN)["result"], sort_keys=True))
    assert results[0] == results[1]


@pytest.mark.parametrize("tool", ["performance.ulcer", "performance.holding_period"])
def test_future_observation_is_rejected(tmp_path: Path, tool: str) -> None:
    folder = stored_run(tmp_path)
    file, column = (
        ("equity_curve.parquet", "ts")
        if tool == "performance.ulcer"
        else ("trades.parquet", "exit_ts")
    )
    frame = pl.read_parquet(folder / file)
    late = frame.tail(1).with_columns(pl.lit(END + timedelta(days=1)).alias(column))
    if column == "exit_ts":
        late = late.with_columns(pl.lit(END + timedelta(days=1)).alias("exit_ts"))
    frame.vstack(late).write_parquet(folder / file)
    with pytest.raises(SpineError, match="run period"):
        run(tmp_path, tool, RUN)


def test_a_curve_that_never_falls_has_no_ratio(tmp_path: Path) -> None:
    stored_run(tmp_path, [100.0 + i for i in range(30)])
    got = run(tmp_path, "performance.ulcer", RUN)
    assert got["values"]["ulcer_index"] == 0.0 and got["values"]["martin_ratio"] is None
    assert "never fell" in got["reasons"]["martin_ratio"]
